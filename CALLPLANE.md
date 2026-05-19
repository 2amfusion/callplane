# Callplane — LiveKit media server fork

This repo (`livekit-callplane`) is **Callplane’s WebRTC media server**: a fork of [LiveKit Server](https://github.com/livekit/livekit). It handles real-time audio/video rooms (SFU). It does **not** replace the Callplane API, dashboard, billing, or telephony logic — those live elsewhere.

## Architecture (target)

```
burki-frontend (dashboard)  →  callplane-api (future)  →  livekit-callplane (this repo)
                                      ↓
                              Postgres, Stripe, telephony providers, etc.
```

| Component | Repo | Role |
|-----------|------|------|
| Media server | **livekit-callplane** (this) | WebRTC SFU, rooms, tracks |
| API / product logic | **callplane-api** (future) | Auth, telephony, assistants, billing, JWT issuance |
| Dashboard | **burki-frontend** | Operator UI |

Phase 1 deploys **only** this fork on Railway, largely unmodified, so you have a working media layer before product features land in `callplane-api`.

---

## Phase 1: Deploy fork on Railway

**Goal:** Build from the repo `Dockerfile` (not a pre-built image), run with config supplied via the `LIVEKIT_CONFIG` environment variable.

### How config is loaded

In `cmd/server/main.go`, the `--config-body` flag is wired to the **`LIVEKIT_CONFIG`** environment variable. When that variable is set, LiveKit parses the YAML string directly — you do **not** need a config file on disk or `--config-body` on the command line.

Railway settings are in [`railway.toml`](railway.toml):

- Build: `DOCKERFILE` → root `Dockerfile`
- Start: `/livekit-server --port $PORT` (reads `LIVEKIT_CONFIG` automatically; **must** listen on Railway's `$PORT` for health checks)
- Health check: `GET /` → `200 OK` when the node is ready (406 "Not Ready" is transient during startup)
- Restart: `ON_FAILURE`

Template config (placeholders only): [`config/railway-dev.yaml`](config/railway-dev.yaml). Do **not** hardcode `port:` for Railway — omit it from `LIVEKIT_CONFIG`.

### Railway environment variables (exact)

The livekit-server binary reads config from **`cmd/server/main.go`** flags. It does **not** support `LIVEKIT_API_KEY` or `LIVEKIT_API_SECRET` — those variable names are used by **client SDKs** and future **callplane-api** when issuing JWTs. Setting only those on Railway will leave the server with **no keys** and it will exit before binding a port → health check **"service unavailable"**.

| Variable | Required? | Purpose |
|----------|-------------|---------|
| `LIVEKIT_CONFIG` | **Option A:** yes | Full config YAML (`--config-body`). Recommended on Railway. |
| `LIVEKIT_KEYS` | **Option B:** yes (if no `keys:` in config) | API key map as YAML snippet, e.g. `APIxxxxx: your-secret-at-least-32-chars` (space after `:`). |
| `REDIS_HOST` | Option B (or in YAML) | Redis `host:port` — use Railway Redis **private** hostname. |
| `REDIS_PASSWORD` | Option B (or in YAML) | Redis password. |
| `PORT` | Auto-injected by Railway | Do not set manually. `railway.toml` runs `--port $PORT` so health checks hit the listener. |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | **Not used by server** | For apps connecting *to* LiveKit (volt, burki-frontend, etc.). Put the same values inside `keys:` in `LIVEKIT_CONFIG` instead. |

**Option A — `LIVEKIT_CONFIG` (recommended)**

1. Fill [`config/railway-dev.yaml`](config/railway-dev.yaml) locally (replace all `YOUR_*`).
2. Railway → Variables → **New variable** → name `LIVEKIT_CONFIG` → paste the **whole YAML** as a multiline value.
3. Do not add a `port:` line. Ensure `keys:` and `redis:` blocks are present with real values.
4. YAML tips: quote passwords containing `:` or `#`; use spaces not tabs; no `YOUR_*` left.

**Option B — `LIVEKIT_KEYS` + Redis env vars (no `LIVEKIT_CONFIG`)**

Use when you want small Railway variables instead of one YAML blob:

```bash
# Example Railway variables (replace values)
LIVEKIT_KEYS=APIabcdef1234567890: your-generated-secret-at-least-32-characters-long
REDIS_HOST=redis.railway.internal:6379
REDIS_PASSWORD=<from Railway Redis plugin>
LIVEKIT_RTC_USE_EXTERNAL_IP=true
LIVEKIT_RTC_TCP_PORT=7881
LIVEKIT_RTC_ALLOW_TCP_FALLBACK=true
```

`railway.toml` still supplies `--port $PORT`. You can also set `LIVEKIT_REDIS_ADDRESS` / `LIVEKIT_REDIS_PASSWORD` instead of `REDIS_HOST` / `REDIS_PASSWORD` (both work; see `cmd/server/main.go`).

**What clients need later (not on this service):** `LIVEKIT_URL` (wss://your-railway-domain), plus the same **key id** and **secret** you put under `keys:` — often named `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` in application env.

### Generate API keys (local, before deploy)

From this repo root:

```bash
go run ./cmd/server generate-keys
```

Copy the printed key and secret into your config under `keys:` (then into Railway `LIVEKIT_CONFIG`). Never commit real keys.

### Manual steps (you do these)

1. **Push this repo to GitHub** (if not already).
2. **Railway:** New Project → Deploy from GitHub → select `livekit-callplane`.
3. **Redis:** Add Railway Redis (or external Redis). Note host, port, password.
4. **Variables:** Use **Option A** (`LIVEKIT_CONFIG` YAML) or **Option B** (`LIVEKIT_KEYS` + `REDIS_HOST` + `REDIS_PASSWORD`) — see table above. Do **not** rely on `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` alone.
5. **Networking:** Railway assigns `$PORT` automatically — the start command binds to it. Add a **TCP proxy** for **`rtc.tcp_port`** (see “Railway dashboard checklist — TCP ICE”). Do **not** expect inbound UDP port ranges on Railway; see “Railway networking (UDP vs TCP)”.
6. **Deploy** and confirm health check passes (`/` returns `OK`).

### Railway dashboard checklist

Use this when a deploy fails health checks or crashes on start:

1. **Keys:** Either `LIVEKIT_CONFIG` includes a `keys:` block, or `LIVEKIT_KEYS` is set. `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` alone do nothing for the server.
2. **Variables → `LIVEKIT_CONFIG` (Option A):** Valid YAML, all `YOUR_*` replaced, no `port:` line. Multiline paste in Railway UI (not a file path).
3. **Redis:** Plugin or external Redis running; `redis.address` / `REDIS_HOST` uses the **private** Railway hostname (not `localhost`). Password matches the Redis service.
4. **Logs (Deploy):** Look for `starting LiveKit server` with `portHttp` matching Railway's `$PORT`. If you see `7880` while `$PORT` differs, redeploy with current `railway.toml` (`--port $PORT`).
5. **Logs (errors):** `one of key-file or keys must be provided` → add `keys:` or `LIVEKIT_KEYS`. `could not parse config` → fix YAML. `could not register node` / Redis dial → fix Redis host/password. `ip address is required` → `rtc.use_external_ip: true` or `LIVEKIT_RTC_USE_EXTERNAL_IP=true`.
6. **Health check:** Path `/`. **503 / service unavailable** → process not listening (crash or wrong port). **406 Not Ready** → server up but node stats stale (usually Redis). **200 OK** + body `OK` = healthy.
7. **Public networking:** HTTP/WebSocket on Railway's public URL. TCP ICE only works if you **add a TCP proxy** for `rtc.tcp_port` (see checklist below).
8. **WebRTC media path:** If participants connect but audio/video never flows, confirm ICE-TCP port is exposed and `allow_tcp_fallback: true` is set.

---

## Railway networking (UDP vs TCP, 2025–2026)

**Bottom line:** Railway’s **public edge is HTTP/TLS-first**. Official guidance for LiveKit on Railway is **TCP-only WebRTC media**, not a wide inbound UDP port range.

| Topic | What Railway does | Implication for LiveKit |
|-------|-------------------|-------------------------|
| **Inbound UDP to your service** | Not supported for arbitrary UDP ports / RTP port ranges (community + official LiveKit template wording). | Do **not** rely on `port_range_start` / `port_range_end` or SIP/RTP UDP reaching your container through Railway’s public network. |
| **Outbound UDP** | Generally works from the container to the internet. | Helpful for Redis, APIs, STUN queries — **not** a substitute for carriers sending RTP inbound to you. |
| **Inbound TCP** | Supported via public networking / TCP proxies (single-port forwarding per mapping). | Use **`rtc.tcp_port` + `allow_tcp_fallback: true`** and expose that TCP port publicly. |

**Primary sources:** [Railway LiveKit deploy template](https://railway.com/deploy/livekit) (“runs LiveKit in **TCP-only mode** since Railway does not support UDP”, TCP proxy on application port **7882** in their template); [Railway public networking docs](https://docs.railway.com/reference/public-networking) (HTTPS edge — use TCP proxies where offered for extra ports).

**`LIVEKIT_CONFIG` pattern for Railway (no inbound UDP):**

- Keep **`rtc.tcp_port`** set to a fixed port (this repo’s template uses **7881**; Railway’s upstream template often uses **7882** — either is fine if it matches the TCP proxy you expose).
- Set **`rtc.allow_tcp_fallback: true`** so clients can fall back to ICE-TCP when UDP is unavailable.
- Set **`rtc.use_external_ip: true`** so ICE candidates advertise a reachable address.
- **Omit** wide **`port_range_*`** for a Railway-only SFU — they imply RTP over UDP that callers cannot reach through Railway’s edge.
- **Optional — external TURN over TLS:** You can point `rtc.turn_servers` at a hosted TURN provider (often **443/TLS**) so relay traffic does not depend on Railway UDP. That is separate infra from Railway itself.

### Railway dashboard checklist — TCP ICE (second public port)

Use this **after** the main HTTPS/WSS domain works (`wss://…railway.app`).

1. Open the **livekit-callplane** service → **Settings** → **Networking** → **Public Networking**.
2. Keep the default **HTTPS** domain for signaling (`--port $PORT` — WebSocket to LiveKit).
3. Add a **TCP Proxy** (wording may appear as “TCP” / “Additional port” depending on UI revision):
   - **Application port:** same integer as `rtc.tcp_port` in `LIVEKIT_CONFIG` (e.g. **7881**).
   - Railway shows a **hostname + port** — clients must receive ICE candidates that include this endpoint (LiveKit usually handles this when `tcp_port` and external IP discovery succeed).
4. Redeploy if you changed `LIVEKIT_CONFIG` — ICE TCP listens only when config matches process startup.
5. **Firewall / Telnyx:** No Railway step opens UDP `50000–60000` to your container; do not assume Telnyx RTP will land on Railway.

There is **nothing to configure** in Railway for “UDP port range” analogous to AWS security groups — that’s exactly the gap.

---

## LiveKit Agents worker (Deepgram + ElevenLabs) on Railway

The Python **Agents** process is **not** the Go `livekit-server`. Run it as a **second Railway service** (same project is fine).

| Piece | Railway service | Notes |
|-------|-----------------|-------|
| **livekit-callplane** | Service A | Docker build from repo root (`railway.toml`). Env: `LIVEKIT_CONFIG`, Redis, `$PORT`. |
| **callplane-agents** | Service B | Docker build with root directory **`callplane-agents/`** (uses `callplane-agents/Dockerfile`). |

**Agents environment variables**

| Variable | Example |
|----------|---------|
| `LIVEKIT_URL` | `wss://callplane-production.up.railway.app` |
| `LIVEKIT_API_KEY` | Key **id** from server `keys:` |
| `LIVEKIT_API_SECRET` | Matching secret |
| `DEEPGRAM_API_KEY` | From Deepgram |
| `ELEVEN_API_KEY` | ElevenLabs API key (PyPI `livekit-plugins-elevenlabs`) |
| `OPENAI_API_KEY` | Required by the skeleton `agent.py` LLM (`livekit-plugins-openai`) unless you change code |

Agents connect **outbound** to `LIVEKIT_URL` — no inbound UDP or extra public ports required on the worker service.

Skeleton code: [`callplane-agents/`](callplane-agents/).

---

## Phone → Telnyx → livekit/sip on Railway

Target call path:

```
PSTN / Phone → Telnyx SIP trunk → livekit/sip (Railway) → Redis ↔ livekit-callplane (WSS)
                                                      → LiveKit room → Agents / participants
```

| Service | Railway service | Root directory | Public ports |
|---------|-----------------|----------------|--------------|
| **livekit-server** | `livekit-callplane` | repo root | HTTPS/WSS on `$PORT`; **TCP proxy** for `rtc.tcp_port` (e.g. 7881) |
| **livekit/sip** | `livekit-sip` | `livekit-sip/` | **TCP proxy** for SIP 5060 (and 5061 if TLS); health HTTP 8080 |
| **Redis** | plugin / shared | — | private `redis.railway.internal` only |

Deploy scaffolding: [`livekit-sip/`](livekit-sip/) (`Dockerfile`, `railway.json`, `config/railway-sip.yaml`, README).

**Your LiveKit URL:** `wss://callplane-production.up.railway.app` — set as `ws_url` / `LIVEKIT_WS_URL` on the SIP service (same API keys as the SFU `keys:` block).

### Railway UDP vs TCP (honest, 2025–2026)

| Layer | Railway support | For `livekit/sip` |
|-------|-----------------|-------------------|
| **HTTPS / WSS** | Default public domain | Used by **livekit-server** only |
| **Inbound TCP** | **TCP Proxy** per port | Use for **SIP signaling** (5060 TCP, 5061 TLS) |
| **Inbound UDP** | **Not available** on public edge (Railway staff, [feedback thread](https://station.railway.com/feedback/allow-outbound-udp-traffic-0f74101c)) | **SIP 5060/udp** and **RTP 10000+** from Telnyx will not reach the container like `docker -p …/udp` |
| **Outbound UDP** | Works | Not a substitute for carrier → you RTP |

**What you can still do on Railway:** run the official `livekit/sip` container, share Redis with the SFU, expose **SIP over TCP/TLS** via TCP Proxy, and pass deploy health checks. **Full PSTN audio** usually needs inbound RTP UDP — expect **signaling-only success** or silent calls until UDP ingress exists or SIP runs on a UDP-capable host (VPS, Fly.io, LiveKit Cloud).

### Deploy `livekit/sip` (third service)

1. Railway project already has **livekit-callplane** + **Redis**.
2. **New service** → same GitHub repo → **Root Directory:** `livekit-sip`.
3. **Variables:** multiline `SIP_CONFIG_BODY` from [`livekit-sip/config/railway-sip.yaml`](livekit-sip/config/railway-sip.yaml) (replace `YOUR_*`, same Redis as SFU). Railway injects `PORT` for health — do not set `PORT` manually. Step-by-step: [`livekit-sip/DEPLOY-SIP.md`](livekit-sip/DEPLOY-SIP.md).
4. **Networking:** add TCP proxies (below); do **not** point Telnyx at `callplane-production.up.railway.app` — that is WebSocket, not SIP.
5. Create LiveKit **SIP inbound trunk** + **dispatch rule** (CLI/API) — [Telnyx provider doc](https://docs.livekit.io/telephony/start/providers/telnyx/).
6. Configure Telnyx FQDN to the **SIP TCP proxy** host:port.

Details: [`livekit-sip/README.md`](livekit-sip/README.md).

### Railway dashboard checklist — livekit/sip

Use with **livekit-sip** service after Redis and **livekit-callplane** are healthy.

1. **Root directory:** `livekit-sip` (not repo root).
2. **Variables → `PORT`:** `8080` — must equal `health_port` in `SIP_CONFIG_BODY` (Railway only probes `$PORT`).
3. **Variables → `SIP_CONFIG_BODY`:** Full YAML; `ws_url: wss://callplane-production.up.railway.app`; `redis.address` = **private** Redis host; `api_key` / `api_secret` match SFU `keys:` map (`LIVEKIT_CONFIG` → `keys:`).
4. **Variables (optional split):** `LIVEKIT_WS_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` instead of embedding in YAML — Redis block still required in `SIP_CONFIG_BODY`.
5. **Health:** `health-wrapper` on Railway `$PORT` (`GET /` → 200); livekit/sip `health_port` is **8081** (set by entrypoint). `livekit-sip/railway.json` has `"startCommand": null`.
6. **Public networking → TCP Proxy #1:** application port **5060** → note `shuttle.proxy.rlwy.net:XXXXX` for Telnyx.
7. **TCP Proxy #2 (optional):** application port **5061** if using `tls:` in config with certs mounted.
8. **Do not expect a UDP section** — there is no Railway UI to open `5060/udp` or `10000-20000/udp` (unlike AWS security groups). Watch [Railway feedback](https://station.railway.com/feedback/adding-inbound-udp-fad19847) if you need this later.
9. **Advertised address:** if using `nat_1_to_1_ip`, set `use_external_ip: false` (sip rejects both). Or use `sip_hostname` + DNS CNAME to the proxy domain (see livekit-sip README).
10. **Logs:** Redis dial errors → wrong private host/password. No INVITEs → Telnyx pointed at wrong host/port or transport UDP-only.
11. **Test call:** INVITE without audio → RTP/UDP blocked; move `livekit/sip` to UDP-capable infra for production PSTN.

### Railway dashboard checklist — livekit-callplane (SFU) with telephony

Same project; WebRTC clients and Agents still use the **HTTPS** domain:

1. **`LIVEKIT_CONFIG`** with `keys:` + `redis:` + `rtc.tcp_port` + `allow_tcp_fallback: true` (see earlier checklist).
2. **TCP Proxy** for **`rtc.tcp_port`** (e.g. 7881) — browsers/phones for WebRTC, separate from SIP TCP proxy.
3. **Agents / API** use `LIVEKIT_URL=wss://callplane-production.up.railway.app` — not the SIP TCP proxy.

### Telnyx trunk checklist (Railway TCP proxy hostname)

Point Telnyx at the **SIP TCP proxy**, not the WSS URL.

| # | Setting | Value |
|---|---------|--------|
| 1 | Connection type | **FQDN** |
| 2 | FQDN / host | `shuttle.proxy.rlwy.net` or CNAME e.g. `sip.callplane.ai` → proxy domain |
| 3 | Port | Railway-assigned TCP proxy port (e.g. `15140`) |
| 4 | Transport | **TCP** or **TLS** (if 5061 proxy + certs) — avoid UDP-only on Railway |
| 5 | Outbound auth | Credentials matching LiveKit `SIPInboundTrunk` |
| 6 | Inbound IP allowlist | Telnyx signaling ranges in LiveKit trunk `inbound_addresses` |
| 7 | Phone number | On connection + LiveKit trunk numbers |
| 8 | LiveKit dispatch rule | Target room / agent for inbound calls |
| 9 | Media (RTP) | UDP to negotiated ports — **verify on Railway**; plan VPS/Fly if no audio |

Docs: [LiveKit Telnyx](https://docs.livekit.io/telephony/start/providers/telnyx/), [Telnyx LiveKit guide](https://developers.telnyx.com/docs/voice/sip-trunking/livekit-configuration-guide).

### If Railway UDP never works for production PSTN

| Component | Recommendation |
|-----------|----------------|
| **livekit-server** | Stay on Railway (TCP ICE) or move SFU to UDP-capable host |
| **livekit/sip** | VPS / Fly.io / LiveKit Cloud telephony with `docker -p 5060:5060/udp` and RTP UDP range |
| **Agents** | Railway OK (outbound to `LIVEKIT_URL`) |

```bash
# VPS pattern (full UDP) — contrast with Railway TCP-only proxies
docker run --rm --network host \
  -e SIP_CONFIG_BODY="$(cat config.yaml)" \
  livekit/sip:v1.3.0
```

---

## Feature rollout order (document only — not implemented yet)

Build product features in **`callplane-api`** in this order. This fork stays focused on media unless a feature truly requires server changes.

| Order | Feature | callplane-api | livekit-callplane (fork) |
|-------|---------|---------------|---------------------------|
| 1 | **Auth** | Users, orgs, JWT/session for dashboard and API | Unchanged; validates JWTs using `keys` in config |
| 2 | **Telephony** | SIP/PSTN providers, call routing, webhooks | Unchanged; receives calls bridged via API |
| 3 | **Assistants** | LLM agents, tools, conversation state | Possible agent/worker hooks later; default fork behavior first |
| 4 | **Billing** | Stripe, usage metering, plans | Unchanged; no billing in media server |

---

## What does **not** belong in LiveKit config

Keep these out of `LIVEKIT_CONFIG` / LiveKit YAML:

- Stripe keys or webhooks
- Postgres / application database URLs
- Dashboard auth secrets (NextAuth, etc.)
- Telephony provider credentials (Twilio, etc.) — those belong in **callplane-api**

LiveKit config should cover: **port**, **redis**, **keys**, **rtc**, **logging**, and other [LiveKit server options](https://docs.livekit.io/home/self-hosting/deployment/) only.

---

## Upstream

- **Upstream remote:** `https://github.com/livekit/livekit`
- Periodically merge upstream fixes; keep Callplane-specific changes small and documented.

---

## Related files

| File | Purpose |
|------|---------|
| `railway.toml` | Railway build/deploy settings |
| `config/railway-dev.yaml` | Placeholder YAML template for `LIVEKIT_CONFIG` |
| `callplane-agents/` | Minimal Agents worker (Dockerfile + `agent.py`) for Railway service #2 |
| `livekit-sip/` | Official `livekit/sip` wrapper for Railway service #3 (Telnyx PSTN) |
| `config-sample.yaml` | Upstream LiveKit sample (full options) |
| `CLAUDE.md` | Agent gotchas for this repo |
