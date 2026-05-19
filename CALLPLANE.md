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
- Start: `/livekit-server` (reads `LIVEKIT_CONFIG` automatically)
- Health check: `GET /` → `200 OK` when the node is ready
- Restart: `ON_FAILURE`

Template config (placeholders only): [`config/railway-dev.yaml`](config/railway-dev.yaml).

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
4. **Variables:** Create `LIVEKIT_CONFIG` — paste full YAML from `config/railway-dev.yaml` after replacing all `YOUR_*` placeholders (Redis host/password, API key/secret).
5. **Networking:** Ensure the service exposes **TCP 7880** (and **7881** if you use TCP ICE). Railway does not reliably expose large UDP ranges; the template enables TCP fallback.
6. **Deploy** and confirm health check passes (`/` returns `OK`).

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
