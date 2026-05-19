# Railway: deploy `livekit/sip` (Callplane)

Callplane SFU WebSocket: `wss://callplane-production.up.railway.app`  
SIP bridge root: **`livekit-sip/`** (not repo root).  
**LiveKit CLI (`lk`)** is required **after** the SIP service is healthy — trunks/dispatch rules are created against the **LiveKit server**, not the SIP container.

---

## How health works

| Layer | Port | Role |
|-------|------|------|
| **`health-wrapper.sh`** | Railway **`$PORT`** (injected) | Binds **before** livekit-sip; **`GET /` → 200** immediately |
| **`livekit/sip`** | **`8081`** (`SIP_INTERNAL_HEALTH_PORT`) | Real SIP readiness (200 after `service ready` in logs) |

Railway only probes **`$PORT`**. livekit/sip does **not** read `PORT`; the entrypoint sets `health_port` to the internal port so the wrapper can own `$PORT`.

| Symptom | Meaning |
|---------|---------|
| **Health #1 instant fail, no `[docker-entrypoint]`** | Wrong Root Directory (parent SFU `railway.toml`) or custom **startCommand** on this service |
| **Health #1 instant fail, no `[health-wrapper]`** | Old image or entrypoint never ran — redeploy latest `main` |
| **Wrapper OK, SIP crashes** | Redis/YAML/STUN — check logs after `[health-wrapper] Listening` |

Startup order: wrapper on `$PORT` → YAML/Redis → SIP (STUN if `use_external_ip`) → internal health on **8081**. Use **`host:6379`** for Redis (not `redis://` in YAML). Link Redis in the same project or copy `redis.railway.internal` from SFU `LIVEKIT_CONFIG`.

**Do not** use `use_external_ip: true` on first deploy — STUN failure exits before SIP health binds. Use [`config/railway-sip-minimal.yaml`](config/railway-sip-minimal.yaml).

---

## 1) New Railway service

1. Open the **same Railway project** as **livekit-callplane** and **Redis**.
2. **New** → **GitHub** → select the **`livekit-callplane`** repo.
3. **Settings → Root Directory:** `livekit-sip` (exactly).
4. Confirm **Config-as-code** picks up `livekit-sip/railway.json` (`"startCommand": null`, `healthcheckPath = "/"`). Do **not** use `startCommand = ""` — empty string is not null and can prevent `/docker-entrypoint.sh` from running.
5. **Settings → Deploy:** Start Command should show as unset/null (Dockerfile `ENTRYPOINT` only). If it still shows the SFU command (`livekit-server --port …`), redeploy after pulling latest `main`.

### Wrong service / root directory

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Root Directory = **repo root** | Wrong config/Dockerfile (SFU image) | Set Root Directory = **`livekit-sip`** |
| Editing **livekit-callplane** (SFU) instead of **livekit-sip** | Variables don't match SIP image | Open the SIP service whose root is `livekit-sip` |

---

## 2) Required Railway variables

| Variable | Value / action |
|----------|----------------|
| **`PORT`** | **Do not set manually** — Railway injects it; `health-wrapper` binds to that value. Only add `PORT=8080` if support asks you to pin it. |
| **`SIP_CONFIG_BODY`** | Multiline YAML — use template in **§3** (replace `YOUR_*`) |
| **`SIP_INTERNAL_HEALTH_PORT`** | Optional; default **`8081`** (livekit/sip monitor; not probed by Railway) |

Optional split (still need `redis:` in YAML):

- `LIVEKIT_WS_URL` = `wss://callplane-production.up.railway.app`
- `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` — same id/secret as SFU `keys:`

Do **not** set `LIVEKIT_CONFIG` on this service — that is for **livekit-callplane** only.

---

## 3) `SIP_CONFIG_BODY` template

```yaml
api_key: YOUR_KEY_ID
api_secret: YOUR_KEY_SECRET
ws_url: wss://callplane-production.up.railway.app

redis:
  address: YOUR_REDIS_HOST:6379
  password: YOUR_REDIS_PASSWORD

sip_port: 5060
rtp_port: 10000-10100
use_external_ip: false

logging:
  level: info
```

**Do not** set `health_port` in YAML — the entrypoint sets it to **`8081`** (internal). Railway uses **`$PORT`** via the wrapper.

| Placeholder | Source |
|-------------|--------|
| `YOUR_KEY_ID` / `YOUR_KEY_SECRET` | **livekit-callplane** → `LIVEKIT_CONFIG` → `keys:` (map key = id, value = secret) |
| `YOUR_REDIS_HOST` / `YOUR_REDIS_PASSWORD` | Same `LIVEKIT_CONFIG` → `redis.address` / `redis.password` (`*.railway.internal`) |

**YAML tips:** Quote Redis password if it contains `:` or `#`: `password: '...'`.

---

## 4) TCP proxy for SIP signaling (5060)

1. **livekit-sip** service → **Networking** → **TCP Proxy** → container port **`5060`**.
2. Telnyx must use the **proxy hostname + port** — not `*.up.railway.app` or `wss://…`.

After proxy exists, set `nat_1_to_1_ip` or `sip_hostname` with **`use_external_ip: false`**.

---

## 5) Post-deploy: trunk + dispatch (`lk`)

```bash
lk --url "wss://callplane-production.up.railway.app" \
  --api-key "YOUR_KEY_ID" \
  --api-secret "YOUR_KEY_SECRET" \
  sip inbound create \
  --name telnyx-inbound \
  --numbers "+1XXXXXXXXXX" \
  --auth-user "YOUR_TRUNK_USER" \
  --auth-pass "YOUR_TRUNK_PASS"

lk --url "wss://callplane-production.up.railway.app" \
  --api-key "YOUR_KEY_ID" \
  --api-secret "YOUR_KEY_SECRET" \
  sip dispatch create \
  --name default-inbound \
  --trunks "<inbound-trunk-id>" \
  --direct "my-sip-room"
```

---

## 6) Telnyx (FQDN connection)

| Field | Value |
|-------|-------|
| Type | **FQDN** |
| Host | TCP proxy hostname (or CNAME) |
| Port | Railway TCP proxy port (dashboard) |
| Transport | **TCP** |
| Auth | Match LiveKit inbound trunk credentials |

---

## 7) Verify

- Deploy logs: Redis connected, **`service ready`**, SIP on **5060**.
- Health: `curl http://$PORT/` → **200** + `OK` (wrapper). After `service ready`: `curl http://127.0.0.1:8081/` → **200** (livekit/sip).
- `nc -vz <tcp-proxy-host> <tcp-proxy-port>` succeeds from outside.

---

## 8) Health check failed — troubleshooting

Railway fails if **`GET $PORT/`** never returns **200** within **300s**.

### Deploy logs — common errors

| Log / error | Meaning | Fix |
|-------------|---------|-----|
| `SIP_CONFIG_BODY is empty` | Variable missing | Paste multiline YAML |
| `still contains YOUR_*` | Placeholders not replaced | Copy keys/Redis from SFU |
| `redis configuration is required` | Missing `redis:` block | Add `redis.address` + `password` |
| `could not parse config` | Bad YAML | Fix indentation; quote special chars |
| `could not resolve external IP` | `use_external_ip: true` + STUN failed | Set `use_external_ip: false` |
| `use_external_ip and nat_1_to_1_ip` | Conflicting NAT | Use one mode only |
| `connection refused` (Redis) | Wrong host/password or `redis://` URL | Use `host:6379` (e.g. `redis.railway.internal:6379`), not `redis://…` |
| `invalid YAML` / inject-config error | Bad paste, tabs, smart quotes | Re-paste template; check deploy log for redacted config dump |
| No logs at all | Wrong root directory or build failed | Root Directory = `livekit-sip` |
| Health #1 instant fail, no `[docker-entrypoint]` | Parent `railway.toml` / wrong Dockerfile | Root Directory must be **`livekit-sip`** |
| Instant fail, `livekit-sip` usage error in logs | SFU `startCommand` copied to this service | `railway.json` must have `"startCommand": null`; redeploy — never `""` |
| Deploy passes but no SIP / no `service ready` | Redis or STUN | Fix `redis.address`; keep `use_external_ip: false` |
| `keys:` in YAML but no `api_key` | Pasted **LIVEKIT_CONFIG** into **SIP_CONFIG_BODY** | Use `api_key` / `api_secret` (see §3 template) |

### Field names (livekit/sip v1.3.0)

| YAML key | Notes |
|----------|-------|
| `api_key` | Or env `LIVEKIT_API_KEY` |
| `api_secret` | Or env `LIVEKIT_API_SECRET` |
| `ws_url` | `wss://…` for production |
| `redis.address` / `redis.password` | Required |
| `health_port` | Set by entrypoint to `8081` — omit in YAML |
| `logging.level` | Prefer over legacy root `log_level` |

### Local smoke test

```bash
cd livekit-sip
export PORT=8080
# Replace YOUR_* in config first, or use minimal yaml with real Redis:
export SIP_CONFIG_BODY="$(cat config/railway-sip-minimal.yaml)"
docker build -t callplane-sip .
docker run --rm -e PORT -e SIP_CONFIG_BODY -p 8080:8080 callplane-sip
# another terminal (after "service ready" in logs):
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/   # expect 200
```

---

## 9) Railway UDP reality

Inbound UDP (SIP 5060/udp, RTP) is not available on Railway's public edge. Signaling over **SIP/TCP** via TCP Proxy may work; **RTP often fails** without inbound UDP. See `README.md` and `CALLPLANE.md`.
