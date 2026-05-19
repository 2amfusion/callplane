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
| **Build logs only, no runtime lines** | Open **Deploy logs** (runtime tab), not Build logs — all startup logs go to **stdout** |
| **Wrapper OK, SIP crashes** | Redis/YAML/STUN — check **Deploy logs** after `[health-wrapper] Listening` |

Startup order: wrapper on `$PORT` → YAML/Redis → SIP (STUN if `use_external_ip`) → internal health on **8081**. Use **`host:6379`** for Redis (not `redis://` in YAML). Link Redis in the same project or copy `redis.railway.internal` from SFU `LIVEKIT_CONFIG`.

**Do not** use `use_external_ip: true` on first deploy — STUN failure exits before SIP health binds. Use [`config/railway-sip-minimal.yaml`](config/railway-sip-minimal.yaml).

---

## 1) New Railway service

1. Open the **same Railway project** as **livekit-callplane** and **Redis**.
2. **New** → **GitHub** → select the **`livekit-callplane`** repo.
3. **Settings → Root Directory:** `livekit-sip` (exactly).
4. Confirm **Config-as-code** picks up `livekit-sip/railway.json` (`startCommand` = **null** → Dockerfile `ENTRYPOINT ["/start.sh"]`). Do **not** set a custom Start Command to `livekit-server …` or `/start.sh` in the dashboard unless null fails to clear a stale value.
5. **Settings → Deploy:** Start Command should be **empty / inherited from Dockerfile** (`/start.sh` via `ENTRYPOINT`). If the dashboard still shows `livekit-server --port …`, fix Root Directory and redeploy latest `main`. See **`VERIFY-DEPLOY.md`** if health still fails.

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
| No logs at all | Wrong tab (Build vs Deploy), wrong root, or build failed | **Deploy logs** tab; Root Directory = `livekit-sip` |
| Health #1 instant fail, no `[docker-entrypoint]` | Parent `railway.toml` / wrong Dockerfile | Root Directory must be **`livekit-sip`** |
| Instant fail, `livekit-sip` usage error in logs | SFU `startCommand` copied to this service | Root = `livekit-sip`; startCommand matches `railway.json` (see §10, `VERIFY-DEPLOY.md`) |
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

## 10) If health still fails after pushing latest `main`

Check in order:

1. **`git log -1 --oneline`** on GitHub `main` includes the latest `fix(livekit-sip):` commit — Railway only builds pushed commits.
2. **Root Directory** = `livekit-sip` (build log must show `COPY health-wrapper.py`).
3. **Deploy logs** (runtime), not Build logs — first line should be `[start.sh] Railway deploy starting`.
4. **Start Command** in dashboard is **empty** (inherits Dockerfile `ENTRYPOINT`). If it shows `livekit-server`, clear it and redeploy.
5. **Delete manual `PORT` variable** — Railway injects `$PORT`; a pinned `8080` can desync the probe.
6. **Debug wrapper only:** set `HEALTH_ONLY=1` on the service, redeploy. If health passes, the wrapper works — fix `SIP_CONFIG_BODY` / Redis next. Remove `HEALTH_ONLY` after.
7. If `HEALTH_ONLY=1` still fails: wrong service, wrong image, or networking — paste first 15 **Deploy log** lines in support.

**Railway logging:** Startup scripts log to **stdout** (not stderr) so lines appear in Deploy logs.

---

## 11) Railway deploy UI checklist (screenshot these)

Open the **livekit-sip** service (not livekit-callplane SFU) → **Settings**:

| UI field | Expected value |
|----------|----------------|
| **Root Directory** | `livekit-sip` (exactly) |
| **Builder** | Dockerfile |
| **Dockerfile path** | `Dockerfile` (relative to root — not repo-root SFU Dockerfile) |
| **Config-as-code** | `livekit-sip/railway.json` detected |
| **Start Command** | Empty (null — uses Dockerfile `ENTRYPOINT /start.sh`) |
| **Healthcheck path** | null in `railway.json` (Railway default) or `/` if you re-enable HTTP probe |
| **Healthcheck timeout** | `300` |

**Deploy logs** (runtime tab — not Build logs) — first lines should include (in order):

1. `[start.sh] Railway deploy starting pid=… PORT=…`
2. `[health-wrapper] starting`
3. `[health-wrapper] PORT=…` (must match Railway-injected `$PORT`, not a hardcoded guess)
4. `[health-wrapper] Listening on …` (`[::]` dual-stack or `0.0.0.0`)
5. `[docker-entrypoint] entrypoint start (PORT=…`
6. `[docker-entrypoint] health responding on PORT=…`

| Log pattern | Meaning |
|-------------|---------|
| **Empty logs** or no `[docker-entrypoint]` | Wrong image (SFU Dockerfile) or build failed — check Root Directory |
| **`[health-wrapper]` missing** | Stale SFU startCommand or old image — redeploy latest `main` |
| **Wrapper listens, health still fails** | `PORT` mismatch — remove manual `PORT=8080` variable; wrapper must use injected `$PORT` |
| **Wrapper OK, then inject-config ERROR** | Health may still pass; fix `SIP_CONFIG_BODY` / Redis |

If health still fails after a green build, paste the **first 15 deploy log lines** when opening a support thread.

---

## 9) Railway UDP reality

Inbound UDP (SIP 5060/udp, RTP) is not available on Railway's public edge. Signaling over **SIP/TCP** via TCP Proxy may work; **RTP often fails** without inbound UDP. See `README.md` and `CALLPLANE.md`.

## Telnyx inbound trunk — auth gotcha

For **inbound** calls on a Telnyx FQDN trunk, you can leave **Inbound authentication** disabled on the Telnyx connection (no username/password on the Telnyx side) and rely on **IP allowlisting** plus LiveKit `SIPInboundTrunk` `inbound_addresses` (Telnyx signaling IPs). Outbound credentials on the trunk still apply when LiveKit places outbound calls. If Telnyx requires inbound digest auth, set matching `auth-user` / `auth-pass` on both `lk sip inbound create` and the Telnyx connection — mismatched or Telnyx-only auth often shows as INVITEs that never reach a dispatch rule or fail with `401`/`403` before the agent worker runs.
