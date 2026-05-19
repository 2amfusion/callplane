#!/bin/sh
# Railway probes $PORT via health-wrapper (started by start.sh before this runs).
# livekit/sip readiness is on SIP_INTERNAL_HEALTH_PORT (default 8081).
set -e

log() {
  printf '[docker-entrypoint] %s\n' "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

PORT="${PORT:-8080}"
export PORT

log "entrypoint start (PORT=${PORT} SIP_INTERNAL_HEALTH_PORT=${SIP_INTERNAL_HEALTH_PORT:-8081})"

if ! command -v python3 >/dev/null 2>&1; then
  fail 'python3 not found in image (Dockerfile must install python3 + python3-yaml)'
fi

health_responds() {
  python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/', timeout=1)" 2>/dev/null
}

if health_responds; then
  log "health responding on PORT=${PORT} (start.sh started health-wrapper)"
else
  fail "nothing listening on PORT=${PORT} — start.sh must run before docker-entrypoint.sh"
fi

if [ -z "${SIP_CONFIG_BODY:-}" ]; then
  fail 'SIP_CONFIG_BODY is empty. Paste multiline YAML in Railway Variables (see DEPLOY-SIP.md).'
fi

# inject-config.py prints ONLY the file path on stdout; logs go to stderr (visible in Railway).
CONFIG_PATH=$(python3 /inject-config.py | tr -d '\r' | tail -n 1) || exit 1
if [ -z "${CONFIG_PATH}" ] || [ ! -f "${CONFIG_PATH}" ]; then
  fail "inject-config did not produce a config file (check stderr above for [inject-config] errors)"
fi
export SIP_CONFIG_FILE="${CONFIG_PATH}"
unset SIP_CONFIG_BODY

log "Starting livekit-sip --config=${SIP_CONFIG_FILE} (internal health on ${SIP_INTERNAL_HEALTH_PORT:-8081})"

exec /bin/livekit-sip --config="${SIP_CONFIG_FILE}"
