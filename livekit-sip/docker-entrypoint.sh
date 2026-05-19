#!/bin/sh
# Railway probes $PORT. livekit/sip only listens on health_port in YAML (not PORT).
# 1) health-wrapper.sh binds $PORT immediately (always 200 OK).
# 2) livekit/sip health_port is moved to SIP_INTERNAL_HEALTH_PORT (default 8081).
set -e

log() {
  printf '[docker-entrypoint] %s\n' "$*" >&2
}

if [ -z "${SIP_CONFIG_BODY:-}" ]; then
  log 'ERROR: SIP_CONFIG_BODY is empty. Paste multiline YAML in Railway Variables (see DEPLOY-SIP.md).'
  log 'Optional: LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_WS_URL still require redis: in YAML.'
  exit 1
fi

# Normalize CRLF from pasted Railway variables (common copy/paste issue).
SIP_CONFIG_BODY=$(printf '%s' "$SIP_CONFIG_BODY" | tr -d '\r')

INTERNAL="${SIP_INTERNAL_HEALTH_PORT:-8081}"

if printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*health_port:[[:space:]]*'; then
  SIP_CONFIG_BODY=$(printf '%s\n' "$SIP_CONFIG_BODY" | sed -E "s/^[[:space:]]*health_port:[[:space:]]*.*/health_port: ${INTERNAL}/")
  log "Set health_port to internal ${INTERNAL} (livekit/sip monitor; Railway uses wrapper on PORT)"
else
  SIP_CONFIG_BODY="health_port: ${INTERNAL}
${SIP_CONFIG_BODY}"
  log "Prepended health_port: ${INTERNAL} (livekit/sip monitor)"
fi
export SIP_CONFIG_BODY

if [ -z "${PORT:-}" ]; then
  PORT=8080
  export PORT
  log 'WARN: PORT unset — defaulting health wrapper to 8080'
fi

/health-wrapper.sh &
WRAPPER_PID=$!
log "Started health wrapper on PORT=${PORT} (pid ${WRAPPER_PID})"

# Block until wrapper answers (Railway may probe $PORT during sip startup).
i=0
while [ "$i" -lt 50 ]; do
  if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
    log 'ERROR: health wrapper exited before binding — check python3 in image'
    exit 1
  fi
  if wget -q -O /dev/null "http://127.0.0.1:${PORT}/" 2>/dev/null; then
    log "Health wrapper ready on PORT=${PORT}"
    break
  fi
  i=$((i + 1))
  sleep 0.1
done
if [ "$i" -ge 50 ]; then
  log "ERROR: health wrapper did not respond on PORT=${PORT} within 5s"
  exit 1
fi

# Upstream image ENTRYPOINT is livekit-sip --config=/sip/config.yaml; we rely on SIP_CONFIG_BODY env.
exec /bin/livekit-sip "$@"
