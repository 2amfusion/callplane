# livekit/sip on Railway (Callplane)

SIP bridge between **Telnyx** (PSTN) and **livekit-callplane** (WebRTC SFU). This folder is a thin Docker wrapper around the official [`livekit/sip`](https://github.com/livekit/sip) image — deploy it as a **third Railway service** in the same project as `livekit-callplane` and Redis.

**LiveKit server (signaling):** `wss://callplane-production.up.railway.app`

---

## What `livekit/sip` needs

| Requirement | Why |
|-------------|-----|
| **Same Redis** as `livekit-server` | Session state + coordination with the SFU |
| **`api_key` / `api_secret`** | Same pair as in `livekit-callplane` `keys:` |
| **`ws_url`** | WebSocket URL of your LiveKit server (`wss://…`) |
| **Public SIP endpoint** | Telnyx sends INVITEs here (signaling) |
| **Public RTP (UDP)** | Telnyx sends audio here (media) — **see Railway UDP caveat below** |

### Ports (container)

| Port | Protocol | Purpose |
|------|----------|---------|
| **5060** | UDP + TCP | SIP signaling (default) |
| **5061** | TCP (TLS) | Optional SIP over TLS |
| **10000–20000** (default) | **UDP** | RTP media (`rtp_port` in config; narrow in template) |
| **`$PORT`** (Railway-injected) | HTTP | Railway health — `health-wrapper.sh` (immediate 200) |
| **8081** | HTTP | livekit/sip real health (`SIP_INTERNAL_HEALTH_PORT`) |

### Config delivery

1. **`SIP_CONFIG_BODY`** — multiline YAML in one Railway variable (recommended).
2. **`SIP_CONFIG_FILE`** — path to a mounted file (not typical on Railway).
3. **Env overrides:** `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_WS_URL` (still need `redis:` in YAML).

**Railway health:** Let Railway inject **`PORT`** (do not set `PORT` unless debugging). Wrapper returns **200** on `GET /` immediately; livekit/sip readiness is on **8081** after `service ready`. See [`DEPLOY-SIP.md`](DEPLOY-SIP.md).

Official reference: [livekit/sip README](https://github.com/livekit/sip/blob/main/README.md).

---

## Railway UDP reality (2025–2026)

| Traffic | Railway public edge |
|---------|---------------------|
| **Outbound UDP** from your container | Supported |
| **Inbound UDP** (SIP 5060/udp, RTP 10000+) | **Not supported** |
| **Inbound TCP** | **TCP Proxy** per port |

Deploy and health checks can succeed; PSTN media may fail until inbound UDP exists. Plan B: Fly.io, VPS, or LiveKit Cloud telephony.

---

## Deploy steps (Railway)

**Full checklist:** [`DEPLOY-SIP.md`](DEPLOY-SIP.md)

1. New service in same project; **Root Directory** = `livekit-sip`.
2. Variables: **`SIP_CONFIG_BODY`** (from [`config/railway-sip.yaml`](config/railway-sip.yaml) or minimal). Do not set **`PORT`** unless Railway support asks — Railway injects it.
3. TCP Proxy on container port **5060**.
4. After healthy: `lk sip inbound create` / `dispatch create` against the SFU URL.

---

## Local smoke test (Docker)

```bash
cd livekit-sip
export PORT=8080
export SIP_CONFIG_BODY="$(cat config/railway-sip-minimal.yaml)"   # replace YOUR_* first
docker build -t callplane-sip .
docker run --rm -e PORT -e SIP_CONFIG_BODY -p 8080:8080 callplane-sip
# after logs show "service ready":
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/
```

On macOS, use `host.docker.internal` in `redis.address` / `ws_url` if Redis/SFU run on the host.

---

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | `FROM livekit/sip:v1.3.0` + entrypoint |
| `docker-entrypoint.sh` | Runs `inject-config.py`, then `livekit-sip` with `SIP_CONFIG_FILE` |
| `inject-config.py` | YAML validate, `health_port` → 8081, writes `/tmp/sip-config.yaml` |
| `railway.json` | Build + healthcheck; **`startCommand`** = `exec /docker-entrypoint.sh` (wrapper binds `$PORT` inside entrypoint) |
| `config/railway-sip.yaml` | Full `SIP_CONFIG_BODY` template |
| `config/railway-sip-minimal.yaml` | Minimal config (`use_external_ip: false`) |
| `DEPLOY-SIP.md` | Railway deploy + troubleshooting |
