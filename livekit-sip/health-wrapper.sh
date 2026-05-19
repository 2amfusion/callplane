#!/bin/sh
# Binds Railway $PORT immediately and returns HTTP 200 on every GET (any path).
# livekit/sip uses health_port on a separate internal port (see docker-entrypoint.sh).
PORT="${PORT:-8080}"
export PORT

if ! command -v python3 >/dev/null 2>&1; then
  printf '[health-wrapper] ERROR: python3 not found (image must install python3-minimal)\n' >&2
  exit 1
fi

exec python3 -u - <<'PYEOF'
import http.server
import os
import socketserver
import sys

port = int(os.environ.get("PORT", "8080"))


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b"OK\n")

    def log_message(self, fmt, *args):
        sys.stderr.write("[health-wrapper] %s - %s\n" % (self.address_string(), fmt % args))


class ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


with ReuseTCPServer(("0.0.0.0", port), HealthHandler) as httpd:
    sys.stderr.write("[health-wrapper] Listening on 0.0.0.0:%d (always 200 OK)\n" % port)
    httpd.serve_forever()
PYEOF
