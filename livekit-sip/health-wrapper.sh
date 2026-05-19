#!/bin/sh
# Binds Railway $PORT immediately; every GET/HEAD returns 200 OK.
# livekit/sip health_port is on SIP_INTERNAL_HEALTH_PORT (see docker-entrypoint.sh).
PORT="${PORT:-8080}"
export PORT

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  printf '[health-wrapper] ERROR: python3 not found\n' >&2
  exit 1
fi

exec python3 -u "${SCRIPT_DIR}/health-wrapper.py"
