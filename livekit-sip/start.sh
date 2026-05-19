#!/bin/sh
# Railway: keep health-wrapper as the long-lived process; start SIP in the background.
set -e

PORT="${PORT:-8080}"
export PORT

echo "[start.sh] starting (pid=$$ PORT=$PORT)"

/health-wrapper.sh &
WRAPPER_PID=$!

i=0
while [ "$i" -lt 120 ]; do
  if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
    echo "[start.sh] ERROR: health-wrapper exited before binding"
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
  echo "[start.sh] ERROR: health-wrapper did not respond within 12s"
  exit 1
fi

# Do not exec — if SIP config/Redis fails, the container must stay up for Railway health.
/docker-entrypoint.sh &
echo "[start.sh] livekit-sip starting in background (wrapper pid=$WRAPPER_PID)"

wait "$WRAPPER_PID"
