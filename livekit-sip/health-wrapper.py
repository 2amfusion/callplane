#!/usr/bin/env python3
"""Immediate HTTP 200 on Railway $PORT — independent of livekit-sip startup."""
from __future__ import annotations

import http.server
import os
import socket
import socketserver
import sys


def port_from_env() -> int:
    raw = (os.environ.get("PORT") or "8080").strip()
    try:
        port = int(raw)
    except ValueError:
        print(f"[health-wrapper] ERROR: PORT must be an integer (got {raw!r})")
        sys.exit(1)
    if port < 1 or port > 65535:
        print(f"[health-wrapper] ERROR: PORT out of range (got {port})")
        sys.exit(1)
    return port


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def _ok(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b"OK\n")

    def do_GET(self) -> None:
        self._ok()

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Connection", "close")
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[health-wrapper] %s - %s\n" % (self.address_string(), fmt % args))


class ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def main() -> None:
    port = port_from_env()
    print(f"[health-wrapper] starting")
    print(f"[health-wrapper] PORT={port} (from env)")

    try:
        httpd = ReuseTCPServer(("0.0.0.0", port), HealthHandler)
    except OSError as exc:
        if exc.errno in (socket.EADDRINUSE, 98):
            print(
                f"[health-wrapper] PORT={port} already bound — assuming another wrapper is running",
            )
            return
        print(f"[health-wrapper] ERROR: bind failed on 0.0.0.0:{port}: {exc}")
        sys.exit(1)

    with httpd:
        print(f"[health-wrapper] Listening on 0.0.0.0:{port} (Railway probe target)")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
