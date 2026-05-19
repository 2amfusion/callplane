#!/bin/sh
# Railway probes $PORT via health-wrapper (immediate GET / → 200).
# livekit/sip readiness is on SIP_INTERNAL_HEALTH_PORT (default 8081).
set -e

log() {
  printf '[docker-entrypoint] %s\n' "$*" >&2
}

fail() {
  log "ERROR: $*"
  exit 1
}

# Railway injects PORT; bind the health wrapper before any slow SIP work.
PORT="${PORT:-8080}"
export PORT

log "entrypoint start (PORT=${PORT} SIP_INTERNAL_HEALTH_PORT=${SIP_INTERNAL_HEALTH_PORT:-8081})"

if ! command -v python3 >/dev/null 2>&1; then
  fail 'python3 not found in image (Dockerfile must install python3 + python3-yaml)'
fi

/health-wrapper.sh &
WRAPPER_PID=$!
log "Started health-wrapper on PORT=${PORT} (pid ${WRAPPER_PID})"

i=0
while [ "$i" -lt 100 ]; do
  if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
    fail 'health-wrapper exited before binding — check deploy logs for [health-wrapper]'
  fi
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/', timeout=1)" 2>/dev/null; then
    log "health-wrapper ready on PORT=${PORT} (Railway GET / will succeed)"
    break
  fi
  i=$((i + 1))
  sleep 0.05
done
if [ "$i" -ge 100 ]; then
  fail "health-wrapper did not respond on PORT=${PORT} within 5s"
fi

if [ -z "${SIP_CONFIG_BODY:-}" ]; then
  fail 'SIP_CONFIG_BODY is empty. Paste multiline YAML in Railway Variables (see DEPLOY-SIP.md).'
fi

CONFIG_PATH=$(python3 /inject-config.py) || exit 1
export SIP_CONFIG_FILE="${CONFIG_PATH}"
unset SIP_CONFIG_BODY

log "Starting livekit-sip --config=${SIP_CONFIG_FILE} (internal health on ${SIP_INTERNAL_HEALTH_PORT:-8081})"

cleanup() {
  kill "$WRAPPER_PID" 2>/dev/null || true
}
trap cleanup TERM INT

# Foreground SIP; shell stays PID 1 so the background health-wrapper keeps serving $PORT.
/bin/livekit-sip --config="${SIP_CONFIG_FILE}" &
SIP_PID=$!
wait "$SIP_PID"
EXIT=$?
cleanup
exit "$EXIT"
