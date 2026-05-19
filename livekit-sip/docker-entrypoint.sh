#!/bin/sh
# Railway health checks always probe $PORT. livekit/sip listens on health_port in YAML only
# (it does not read PORT). Sync health_port → PORT when both are present so deploy health passes.
set -e

if [ -n "${PORT:-}" ] && [ -n "${SIP_CONFIG_BODY:-}" ]; then
  if printf '%s\n' "$SIP_CONFIG_BODY" | grep -Eq '^[[:space:]]*health_port:[[:space:]]*'; then
    SIP_CONFIG_BODY=$(printf '%s\n' "$SIP_CONFIG_BODY" | sed -E "s/^[[:space:]]*health_port:[[:space:]]*.*/health_port: ${PORT}/")
  else
    SIP_CONFIG_BODY="health_port: ${PORT}
${SIP_CONFIG_BODY}"
  fi
  export SIP_CONFIG_BODY
fi

exec livekit-sip "$@"
