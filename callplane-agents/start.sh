#!/bin/sh
# Railway: health-wrapper binds $PORT immediately; agent worker runs on AGENT_HTTP_PORT.
set -e

PORT="${PORT:-8080}"
export PORT PYTHONUNBUFFERED=1

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"

echo "[start.sh] Railway deploy starting pid=$$ PORT=$PORT HEALTH_ONLY=${HEALTH_ONLY:-0}"

if [ "${HEALTH_ONLY:-}" = "1" ]; then
  echo "[start.sh] HEALTH_ONLY=1 — wrapper only (debug Railway health; no agent worker)"
  exec python3 -u "${SCRIPT_DIR}/health-wrapper.py"
fi

python3 -u "${SCRIPT_DIR}/health-wrapper.py" &
WRAPPER_PID=$!

i=0
while [ "$i" -lt 120 ]; do
  if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
    echo "[start.sh] ERROR: health-wrapper exited before binding — see [health-wrapper] lines above"
    exit 1
  fi
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/', timeout=1)" 2>/dev/null; then
    echo "[start.sh] health-wrapper ready on PORT=$PORT"
    break
  fi
  i=$((i + 1))
  sleep 0.1
done

if [ "$i" -ge 120 ]; then
  echo "[start.sh] ERROR: health-wrapper did not respond on PORT=$PORT within 12s"
  exit 1
fi

echo "[start.sh] starting LiveKit agent worker (wrapper pid=$WRAPPER_PID)"
exec python3 -u "${SCRIPT_DIR}/agent.py" start
