#!/bin/sh
# Railway probes $PORT. livekit/sip serves GET / on health_port only — it does not read PORT.
# inject-config.py merges health_port from $PORT, validates YAML, writes SIP_CONFIG_FILE.
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

if ! command -v python3 >/dev/null 2>&1; then
  fail 'python3 not found in image (Dockerfile must install python3 + python3-yaml)'
fi

CONFIG_PATH=$(python3 /inject-config.py) || exit 1
export SIP_CONFIG_FILE="${CONFIG_PATH}"
unset SIP_CONFIG_BODY

log "Starting livekit-sip (SIP_CONFIG_FILE=${SIP_CONFIG_FILE}; Railway GET / on PORT=${PORT:-8080})"
exec /bin/livekit-sip "$@"
