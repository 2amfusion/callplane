#!/bin/sh
# Railway: health-wrapper must stay alive (PID 1 waits on it). SIP runs in background.
set -e

PORT="${PORT:-8080}"
export PORT PYTHONUNBUFFERED=1

echo "[start.sh] Railway deploy starting pid=$$ PORT=$PORT HEALTH_ONLY=${HEALTH_ONLY:-0}"

if [ "${HEALTH_ONLY:-}" = "1" ]; then
  echo "[start.sh] HEALTH_ONLY=1 — wrapper only (debug Railway health; no livekit-sip)"
  exec python3 -u /health-wrapper.py
fi

python3 -u /health-wrapper.py &
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

/docker-entrypoint.sh &
echo "[start.sh] livekit-sip starting in background (wrapper pid=$WRAPPER_PID)"

wait "$WRAPPER_PID"
