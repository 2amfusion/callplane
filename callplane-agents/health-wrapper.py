#!/usr/bin/env python3
"""Immediate HTTP 200 on Railway $PORT — independent of agent worker startup."""
from __future__ import annotations

import http.server
import os
import socket
import socketserver
import sys
import urllib.error
import urllib.request


def log(msg: str) -> None:
    print(msg, flush=True)


def port_from_env() -> int:
    raw = (os.environ.get("PORT") or "8080").strip()
    try:
        port = int(raw)
    except ValueError:
        log(f"[health-wrapper] ERROR: PORT must be an integer (got {raw!r})")
        sys.exit(1)
    if port < 1 or port > 65535:
        log(f"[health-wrapper] ERROR: PORT out of range (got {port})")
        sys.exit(1)
    return port


def probe_local_health(port: int) -> bool:
    for url in (f"http://127.0.0.1:{port}/", f"http://[::1]:{port}/"):
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            continue
    return False


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
        log("[health-wrapper] %s - %s" % (self.address_string(), fmt % args))


class ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class DualStackTCPServer(socketserver.TCPServer):
    address_family = socket.AF_INET6
    allow_reuse_address = True

    def server_bind(self) -> None:
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except OSError:
            pass
        super().server_bind()


def bind_httpd(port: int) -> tuple[socketserver.TCPServer, str]:
    if probe_local_health(port):
        log(f"[health-wrapper] PORT={port} already serving 200 — exiting (another wrapper)")
        sys.exit(0)

    for label, host, cls in (
        ("[::] (dual-stack)", "::", DualStackTCPServer),
        ("0.0.0.0", "0.0.0.0", ReuseTCPServer),
    ):
        try:
            httpd = cls((host, port), HealthHandler)
            return httpd, label
        except OSError as exc:
            if exc.errno in (socket.EADDRINUSE, 98) and probe_local_health(port):
                log(f"[health-wrapper] PORT={port} in use but health OK — exiting")
                sys.exit(0)
            if host == "::":
                log(f"[health-wrapper] WARN: {label} bind failed ({exc}); trying IPv4")
                continue
            log(f"[health-wrapper] ERROR: bind failed on {label}:{port}: {exc}")
            sys.exit(1)

    log(f"[health-wrapper] ERROR: could not bind port {port}")
    sys.exit(1)


def main() -> None:
    port = port_from_env()
    log("[health-wrapper] starting")
    log(f"[health-wrapper] PORT={port} (from env)")

    httpd, label = bind_httpd(port)
    with httpd:
        log(f"[health-wrapper] Listening on {label}:{port} (Railway probe target)")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
