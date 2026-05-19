#!/bin/sh
# Railway health checks probe $PORT. livekit/sip listens on health_port in YAML only
# (it does not read PORT). Sync health_port → PORT before starting the binary.
set -e

log() {
  printf '[docker-entrypoint] %s\n' "$*" >&2
}

if [ -z "${SIP_CONFIG_BODY:-}" ]; then
  log 'ERROR: SIP_CONFIG_BODY is empty. Paste multiline YAML in Railway Variables (see DEPLOY-SIP.md).'
  log 'Optional: LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_WS_URL still require redis: in YAML.'
  exit 1
fi

if [ -n "${PORT:-}" ]; then
  # Normalize CRLF from pasted Railway variables (common copy/paste issue).
  SIP_CONFIG_BODY=$(printf '%s' "$SIP_CONFIG_BODY" | tr -d '\r')

  if printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*health_port:[[:space:]]*'; then
    SIP_CONFIG_BODY=$(printf '%s\n' "$SIP_CONFIG_BODY" | sed -E "s/^[[:space:]]*health_port:[[:space:]]*.*/health_port: ${PORT}/")
    log "Set health_port to PORT=${PORT} (was present in SIP_CONFIG_BODY)"
  else
    SIP_CONFIG_BODY="health_port: ${PORT}
${SIP_CONFIG_BODY}"
    log "Prepended health_port: ${PORT} (was missing from SIP_CONFIG_BODY)"
  fi
  export SIP_CONFIG_BODY
elif printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*health_port:[[:space:]]*'; then
  log 'WARN: health_port is set but PORT is empty — Railway normally sets PORT; health checks may fail.'
else
  log 'WARN: No PORT and no health_port — HTTP health will not listen; Railway deploy health will fail.'
fi

# Upstream image ENTRYPOINT is livekit-sip --config=/sip/config.yaml; we rely on SIP_CONFIG_BODY env.
exec /bin/livekit-sip "$@"
