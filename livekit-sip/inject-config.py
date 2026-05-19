#!/usr/bin/env python3
"""Merge SIP_CONFIG_BODY; set health_port for livekit/sip; write SIP_CONFIG_FILE."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import yaml
except ImportError as e:
    print(f"[inject-config] ERROR: PyYAML required ({e})", file=sys.stderr)
    sys.exit(1)

OUT_PATH = Path(os.environ.get("SIP_CONFIG_FILE", "/tmp/sip-config.yaml"))
PLACEHOLDER_RE = re.compile(r"YOUR_(KEY_ID|KEY_SECRET|REDIS_HOST|REDIS_PASSWORD)")


def log(msg: str) -> None:
    print(f"[inject-config] {msg}", file=sys.stderr)


def fail(msg: str, cfg: dict[str, Any] | None = None) -> None:
    log(f"ERROR: {msg}")
    if cfg is not None:
        log("--- merged config (passwords redacted) ---")
        redacted = redact(cfg)
        print(yaml.safe_dump(redacted, default_flow_style=False, sort_keys=False), file=sys.stderr)
    sys.exit(1)


def redact(cfg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in cfg.items():
        if k == "redis" and isinstance(v, dict):
            r = dict(v)
            if r.get("password"):
                r["password"] = "***"
            out[k] = r
        elif k in ("api_secret",) and v:
            out[k] = "***"
        else:
            out[k] = v
    return out


def normalize_redis_address(addr: str) -> str:
    addr = (addr or "").strip()
    if not addr:
        fail("redis.address is empty")
    if addr.startswith("redis://") or addr.startswith("rediss://"):
        parsed = urlparse(addr)
        host = parsed.hostname
        port = parsed.port or 6379
        if not host:
            fail(
                f"redis.address URL missing host: {addr!r}. "
                "Use host:port (e.g. redis.railway.internal:6379), not redis:// on Railway."
            )
        log(
            f"WARN: redis.address was a URL; normalized to {host}:{port}. "
            "Prefer host:port in SIP_CONFIG_BODY."
        )
        return f"{host}:{port}"
    if "://" in addr:
        fail(f"redis.address has unsupported scheme: {addr!r}. Use hostname:6379")
    if ":" not in addr:
        log("WARN: redis.address has no port; appending :6379")
        return f"{addr}:6379"
    return addr


def apply_redis_env(cfg: dict[str, Any]) -> None:
    """Fill redis block from Railway Redis plugin vars when YAML omits them."""
    redis = cfg.setdefault("redis", {})
    if not isinstance(redis, dict):
        fail("redis: must be a mapping", cfg)

    url = os.environ.get("REDIS_URL", "").strip()
    if url and not redis.get("address"):
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or 6379
        if host:
            redis["address"] = f"{host}:{port}"
            if parsed.password and not redis.get("password"):
                redis["password"] = parsed.password
            log(f"redis.address from REDIS_URL → {redis['address']}")

    if os.environ.get("REDIS_PASSWORD") and not redis.get("password"):
        redis["password"] = os.environ["REDIS_PASSWORD"]

    host = os.environ.get("REDIS_HOST", "").strip()
    if host and not redis.get("address"):
        port = os.environ.get("REDIS_PORT", "6379").strip() or "6379"
        redis["address"] = f"{host}:{port}"
        log(f"redis.address from REDIS_HOST → {redis['address']}")


def load_body() -> dict[str, Any]:
    raw = os.environ.get("SIP_CONFIG_BODY", "")
    if not raw.strip():
        fail("SIP_CONFIG_BODY is empty. Paste multiline YAML in Railway Variables.")
    raw = raw.replace("\r", "")
    if "\\n" in raw and raw.count("\n") < 3:
        log("WARN: SIP_CONFIG_BODY looks like a single line with \\n — converting to newlines")
        raw = raw.replace("\\n", "\n")
    if PLACEHOLDER_RE.search(raw):
        fail("SIP_CONFIG_BODY still contains YOUR_* placeholders.")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        fail(f"invalid YAML in SIP_CONFIG_BODY: {e}")
    if not isinstance(data, dict):
        fail(f"SIP_CONFIG_BODY must be a YAML mapping, got {type(data).__name__}")
    return data


def apply_env_overrides(cfg: dict[str, Any]) -> None:
    if os.environ.get("LIVEKIT_API_KEY") and not cfg.get("api_key"):
        cfg["api_key"] = os.environ["LIVEKIT_API_KEY"]
    if os.environ.get("LIVEKIT_API_SECRET") and not cfg.get("api_secret"):
        cfg["api_secret"] = os.environ["LIVEKIT_API_SECRET"]
    if os.environ.get("LIVEKIT_WS_URL") and not cfg.get("ws_url"):
        cfg["ws_url"] = os.environ["LIVEKIT_WS_URL"]


def validate(cfg: dict[str, Any]) -> None:
    if "keys" in cfg and not cfg.get("api_key"):
        fail(
            "SIP_CONFIG_BODY has keys: (livekit-callplane format) but livekit/sip needs "
            "api_key and api_secret at the top level — see config/railway-sip-minimal.yaml",
            cfg,
        )
    if not cfg.get("api_key"):
        fail("missing api_key (set in YAML or LIVEKIT_API_KEY)", cfg)
    if not cfg.get("api_secret"):
        fail("missing api_secret (set in YAML or LIVEKIT_API_SECRET)", cfg)
    if not cfg.get("ws_url"):
        fail("missing ws_url (set in YAML or LIVEKIT_WS_URL)", cfg)
    redis = cfg.get("redis")
    if not isinstance(redis, dict):
        fail("missing redis: block (address + password required)", cfg)
    addr = redis.get("address")
    if not addr:
        fail(
            "redis.address missing — use host:6379 (e.g. redis.railway.internal:6379) "
            "or link Redis and set REDIS_URL on this service",
            cfg,
        )
    redis["address"] = normalize_redis_address(str(addr))
    if cfg.get("use_external_ip") is True and cfg.get("nat_1_to_1_ip"):
        fail("use_external_ip: true and nat_1_to_1_ip cannot both be set", cfg)
    if cfg.get("use_external_ip") is True:
        log(
            "WARN: use_external_ip: true runs STUN at startup — failure exits before SIP health binds. "
            "Use use_external_ip: false for first deploy (config/railway-sip-minimal.yaml)."
        )


def internal_health_port() -> int:
    raw = os.environ.get("SIP_INTERNAL_HEALTH_PORT", "8081").strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 65535):
        fail(f"SIP_INTERNAL_HEALTH_PORT must be 1-65535 (got: {raw!r})")
    internal = int(raw)
    port_s = os.environ.get("PORT", "8080").strip()
    if port_s.isdigit() and int(port_s) == internal:
        fail(
            f"SIP_INTERNAL_HEALTH_PORT ({internal}) must differ from Railway PORT ({port_s}). "
            "health-wrapper uses PORT; livekit/sip uses SIP_INTERNAL_HEALTH_PORT."
        )
    return internal


def main() -> None:
    internal = internal_health_port()

    cfg = load_body()
    apply_env_overrides(cfg)
    apply_redis_env(cfg)
    validate(cfg)

    # livekit/sip monitor — not probed by Railway (wrapper owns $PORT).
    cfg["health_port"] = internal

    try:
        rendered = yaml.safe_dump(cfg, default_flow_style=False, sort_keys=False)
        yaml.safe_load(rendered)
    except yaml.YAMLError as e:
        fail(f"rendered config is invalid YAML: {e}", cfg)

    OUT_PATH.write_text(rendered, encoding="utf-8")
    railway_port = os.environ.get("PORT", "8080")
    log(
        f"Wrote {OUT_PATH} (health_port={internal} for livekit/sip; "
        f"Railway probes PORT={railway_port} via health-wrapper; redis={cfg['redis']['address']})"
    )
    print(str(OUT_PATH))


if __name__ == "__main__":
    main()
