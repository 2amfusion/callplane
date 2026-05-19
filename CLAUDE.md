# livekit-callplane — agent notes

Callplane media server fork of [livekit/livekit](https://github.com/livekit/livekit). Product docs: `CALLPLANE.md`.

## Stack

- Go 1.26+, Docker multi-stage build → `/livekit-server`
- Config: YAML via `LIVEKIT_CONFIG` env (`--config-body` in `cmd/server/main.go`)

## Commands

```bash
go run ./cmd/server generate-keys   # API key pair for keys: in config
go run ./cmd/server                 # local dev (needs config file or LIVEKIT_CONFIG)
docker build -t livekit-callplane .
```

## Railway (Phase 1)

- `railway.toml`: `DOCKERFILE` build, start bridges `$PORT` → `--port`, healthcheck `GET /`, restart `ON_FAILURE`
- **Option A:** paste filled `config/railway-dev.yaml` into **`LIVEKIT_CONFIG`** (multiline). Omit `port:` — `railway.toml` uses `--port $PORT`.
- **Option B:** `LIVEKIT_KEYS` + `REDIS_HOST` + `REDIS_PASSWORD` (+ `LIVEKIT_RTC_*` as in CALLPLANE.md) — no `LIVEKIT_CONFIG`.
- **`LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` are NOT read by livekit-server** — client/callplane-api names only; server needs `keys:` in YAML or `LIVEKIT_KEYS`.
- Generate keys: `go run ./cmd/server generate-keys`
- **UDP:** Railway does not expose wide UDP port ranges reliably — use `rtc.tcp_port` + `allow_tcp_fallback`; avoid large `port_range_*` on Railway
- Optionally expose TCP **7881** publicly for TCP ICE (`rtc.tcp_port` in config)

### Railway troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| Health check "service unavailable" / connection refused | Process crashed before bind (missing `keys:` / `LIVEKIT_KEYS`, bad YAML) or not on `$PORT` — check deploy logs first |
| Only `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` set | Server ignores these; use `LIVEKIT_CONFIG` `keys:` block or `LIVEKIT_KEYS` |
| Health check never gets 200 (406 "Not Ready") | Redis unreachable — node stats cannot refresh; fix `redis.address` / password |
| `one of key-file or keys must be provided` | `LIVEKIT_CONFIG` missing or has no `keys:` block |
| `could not parse config` | Invalid YAML in `LIVEKIT_CONFIG` (unquoted `:` in secrets, bad indentation) |
| `ip address is required and not set` | RTC IP discovery failed; ensure `rtc.use_external_ip: true` in config |
| `could not register node` / Redis errors | Wrong Redis host (use Railway internal URL, e.g. `${{Redis.REDIS_URL}}` or plugin host:port) |

Health: `GET /` returns **200 OK** when node stats are fresh (<4s). Brief **406** right after listen is normal; Railway retries until 200 or timeout (300s).

## Feature order (implement in callplane-api, not here yet)

auth → telephony → assistants → billing

## Gotchas

- Do **not** commit secrets; `config/railway-dev.yaml` is placeholders only; `config/.gitignore` blocks `*-local.yaml` / `*-secrets.yaml`
- Do not put Stripe, Postgres, or telephony creds in LiveKit config
- Health: `GET /` → `200 OK` when node stats are fresh; may 406 briefly during startup
