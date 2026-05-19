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

- `railway.toml`: `DOCKERFILE` build, start `/livekit-server`, healthcheck `/`, restart `ON_FAILURE`
- Paste filled `config/railway-dev.yaml` into Railway variable **`LIVEKIT_CONFIG`** (multiline)
- **UDP:** Railway does not expose wide UDP port ranges reliably — use `rtc.tcp_port` + `allow_tcp_fallback`; avoid large `port_range_*` on Railway
- Expose TCP **7880** (and **7881** for TCP ICE)

## Feature order (implement in callplane-api, not here yet)

auth → telephony → assistants → billing

## Gotchas

- Do **not** commit secrets; `config/railway-dev.yaml` is placeholders only; `config/.gitignore` blocks `*-local.yaml` / `*-secrets.yaml`
- Do not put Stripe, Postgres, or telephony creds in LiveKit config
- Health: `GET /` → `200 OK` when node stats are fresh; may 406 briefly during startup
