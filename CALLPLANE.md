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
5. **Networking:** Railway assigns `$PORT` automatically — the start command binds to it. Optionally expose **7881** for TCP ICE (`rtc.tcp_port`). Railway does not reliably expose large UDP ranges; the template enables TCP fallback.
6. **Deploy** and confirm health check passes (`/` returns `OK`).

### Railway dashboard checklist

Use this when a deploy fails health checks or crashes on start:

1. **Keys:** Either `LIVEKIT_CONFIG` includes a `keys:` block, or `LIVEKIT_KEYS` is set. `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` alone do nothing for the server.
2. **Variables → `LIVEKIT_CONFIG` (Option A):** Valid YAML, all `YOUR_*` replaced, no `port:` line. Multiline paste in Railway UI (not a file path).
3. **Redis:** Plugin or external Redis running; `redis.address` / `REDIS_HOST` uses the **private** Railway hostname (not `localhost`). Password matches the Redis service.
4. **Logs (Deploy):** Look for `starting LiveKit server` with `portHttp` matching Railway's `$PORT`. If you see `7880` while `$PORT` differs, redeploy with current `railway.toml` (`--port $PORT`).
5. **Logs (errors):** `one of key-file or keys must be provided` → add `keys:` or `LIVEKIT_KEYS`. `could not parse config` → fix YAML. `could not register node` / Redis dial → fix Redis host/password. `ip address is required` → `rtc.use_external_ip: true` or `LIVEKIT_RTC_USE_EXTERNAL_IP=true`.
6. **Health check:** Path `/`. **503 / service unavailable** → process not listening (crash or wrong port). **406 Not Ready** → server up but node stats stale (usually Redis). **200 OK** + body `OK` = healthy.
7. **Public networking:** HTTP/WebSocket on Railway's public URL. TCP ICE on 7881 only if you expose that port separately.

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
| `config-sample.yaml` | Upstream LiveKit sample (full options) |
| `CLAUDE.md` | Agent gotchas for this repo |
