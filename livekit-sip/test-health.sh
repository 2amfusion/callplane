#!/bin/sh
# Local smoke test for health-wrapper (no Docker required).
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
TEST_PORT="${TEST_PORT:-9876}"

cleanup() {
  if [ -n "${WPID:-}" ]; then
    kill "$WPID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

PORT="$TEST_PORT" /bin/sh "$ROOT/health-wrapper.sh" &
WPID=$!

i=0
while [ "$i" -lt 50 ]; do
  if curl -sf "http://127.0.0.1:${TEST_PORT}/" >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 0.1
done

if [ "$i" -ge 50 ]; then
  echo "FAIL: health-wrapper did not respond on :${TEST_PORT}" >&2
  exit 1
fi

code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${TEST_PORT}/")
head_code=$(curl -s -o /dev/null -w '%{http_code}' -I "http://127.0.0.1:${TEST_PORT}/")

if [ "$code" != "200" ] || [ "$head_code" != "200" ]; then
  echo "FAIL: GET=$code HEAD=$head_code (expected 200)" >&2
  exit 1
fi

echo "OK: health-wrapper GET/HEAD 200 on :${TEST_PORT}"
