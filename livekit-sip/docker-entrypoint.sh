#!/bin/sh
# Railway probes $PORT (health-wrapper → 200 immediately).
# livekit/sip serves real readiness on SIP_INTERNAL_HEALTH_PORT (default 8081).
set -e

log() {
  printf '[docker-entrypoint] %s\n' "$*" >&2
}

fail() {
  log "ERROR: $*"
  exit 1
}

log "entrypoint start (PORT=${PORT:-8080} SIP_INTERNAL_HEALTH_PORT=${SIP_INTERNAL_HEALTH_PORT:-8081})"

if [ -z "${SIP_CONFIG_BODY:-}" ]; then
  fail 'SIP_CONFIG_BODY is empty. Paste multiline YAML in Railway Variables (see DEPLOY-SIP.md).'
fi

if ! command -v python3 >/dev/null 2>&1; then
  fail 'python3 not found in image (Dockerfile must install python3 + python3-yaml)'
fi

if [ -z "${PORT:-}" ]; then
  PORT=8080
  export PORT
  log 'WARN: PORT unset — defaulting to 8080'
fi

/health-wrapper.sh &
WRAPPER_PID=$!
log "Started health-wrapper on PORT=${PORT} (pid ${WRAPPER_PID})"

i=0
while [ "$i" -lt 50 ]; do
  if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
    fail 'health-wrapper exited before binding — check deploy logs for [health-wrapper]'
  fi
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/', timeout=1)" 2>/dev/null; then
    log "health-wrapper ready on PORT=${PORT} (Railway GET / will succeed)"
    break
  fi
  i=$((i + 1))
  sleep 0.1
done
if [ "$i" -ge 50 ]; then
  fail "health-wrapper did not respond on PORT=${PORT} within 5s"
fi

CONFIG_PATH=$(python3 /inject-config.py) || exit 1
export SIP_CONFIG_FILE="${CONFIG_PATH}"
unset SIP_CONFIG_BODY

log "Starting livekit-sip --config=${SIP_CONFIG_FILE} (internal health on ${SIP_INTERNAL_HEALTH_PORT:-8081})"
exec /bin/livekit-sip --config="${SIP_CONFIG_FILE}"
