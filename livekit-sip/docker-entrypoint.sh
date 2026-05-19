#!/bin/sh
# Railway probes $PORT. livekit/sip serves GET / on health_port only — it does not read PORT.
# This entrypoint injects health_port from $PORT into SIP_CONFIG_BODY, then execs livekit-sip.
# Health returns 200 after Redis connects and logs show "service ready".
set -e

log() {
  printf '[docker-entrypoint] %s\n' "$*" >&2
}

fail() {
  log "ERROR: $*"
  exit 1
}

if [ -z "${SIP_CONFIG_BODY:-}" ]; then
  fail 'SIP_CONFIG_BODY is empty. Paste multiline YAML in Railway Variables (see DEPLOY-SIP.md).'
fi

# Normalize CRLF from pasted Railway variables (common copy/paste issue).
SIP_CONFIG_BODY=$(printf '%s' "$SIP_CONFIG_BODY" | tr -d '\r')

if printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq 'YOUR_(KEY_ID|KEY_SECRET|REDIS_HOST|REDIS_PASSWORD)'; then
  fail 'SIP_CONFIG_BODY still contains YOUR_* placeholders — replace with values from livekit-callplane LIVEKIT_CONFIG.'
fi

if [ -z "${LIVEKIT_API_KEY:-}" ]; then
  printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*api_key:[[:space:]]*.+' \
    || fail 'SIP_CONFIG_BODY missing api_key (or set LIVEKIT_API_KEY).'
fi

if [ -z "${LIVEKIT_API_SECRET:-}" ]; then
  printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*api_secret:[[:space:]]*.+' \
    || fail 'SIP_CONFIG_BODY missing api_secret (or set LIVEKIT_API_SECRET).'
fi

if [ -z "${LIVEKIT_WS_URL:-}" ]; then
  printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*ws_url:[[:space:]]*.+' \
    || fail 'SIP_CONFIG_BODY missing ws_url (wss://… for production, or set LIVEKIT_WS_URL).'
fi

if ! printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*redis:'; then
  fail 'SIP_CONFIG_BODY must include a redis: block (address + password from livekit-callplane LIVEKIT_CONFIG).'
fi

if ! printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*address:[[:space:]]*.+'; then
  fail 'SIP_CONFIG_BODY redis.address missing (use *.railway.internal hostname, not localhost).'
fi

if printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*use_external_ip:[[:space:]]*true'; then
  log 'WARN: use_external_ip: true runs STUN at startup — failure exits before health HTTP binds.'
  log 'WARN: For first Railway deploy use use_external_ip: false (config/railway-sip-minimal.yaml).'
fi

if printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*use_external_ip:[[:space:]]*true' \
  && printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*nat_1_to_1_ip:[[:space:]]*[^[:space:]]'; then
  fail 'use_external_ip: true and nat_1_to_1_ip cannot both be set. Use one NAT mode (see DEPLOY-SIP.md).'
fi

if [ -z "${PORT:-}" ]; then
  PORT=8080
  export PORT
  log 'WARN: PORT unset — defaulting health_port to 8080'
fi

case "$PORT" in
  ''|*[!0-9]*)
    fail "PORT must be a numeric TCP port (got: ${PORT})"
    ;;
esac

if printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*health_port:[[:space:]]*'; then
  SIP_CONFIG_BODY=$(printf '%s\n' "$SIP_CONFIG_BODY" | sed -E "s/^[[:space:]]*health_port:[[:space:]]*.*/health_port: ${PORT}/")
  log "Set health_port to ${PORT} (Railway probes this port)"
else
  SIP_CONFIG_BODY="health_port: ${PORT}
${SIP_CONFIG_BODY}"
  log "Prepended health_port: ${PORT} (Railway probes this port)"
fi
export SIP_CONFIG_BODY

log "Starting livekit-sip (health_port=${PORT}; GET / returns 200 when service ready)"
exec /bin/livekit-sip "$@"
