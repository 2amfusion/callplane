#!/bin/sh
# Single Railway/Docker start path: health on $PORT first, then SIP entrypoint.
set -e

PORT="${PORT:-8080}"
export PORT

/health-wrapper.sh &
WRAPPER_PID=$!

i=0
while [ "$i" -lt 100 ]; do
  if ! kill -0 "$WRAPPER_PID" 2>/dev/null; then
    printf '[start.sh] ERROR: health-wrapper exited before binding — check logs for [health-wrapper]\n' >&2
    exit 1
  fi
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/', timeout=1)" 2>/dev/null; then
    printf '[start.sh] health-wrapper ready on PORT=%s\n' "$PORT" >&2
    break
  fi
  i=$((i + 1))
  sleep 0.05
done

if [ "$i" -ge 100 ]; then
  printf '[start.sh] ERROR: health-wrapper did not respond on PORT=%s within 5s\n' "$PORT" >&2
  exit 1
fi

exec /docker-entrypoint.sh
