# Railway: deploy `livekit/sip` (this attempt only)

Callplane SFU WebSocket: `wss://callplane-production.up.railway.app`  
SIP bridge root: **`livekit-sip/`** (not repo root).  
**LiveKit CLI (`lk`)** is required **after** the SIP service is healthy — trunks/dispatch rules are created against the **LiveKit server**, not the SIP container.

---

## 1) New Railway service

1. Open the **same Railway project** as **livekit-callplane** and **Redis**.
2. **New** → **GitHub** → select the **`livekit-callplane`** repo.
3. **Settings → Root Directory:** `livekit-sip` (exactly).
4. Confirm **Config-as-code** picks up `livekit-sip/railway.toml`.

---

## 2) Variables (order matters conceptually — set all before first deploy)

| Variable | Value / action |
|----------|----------------|
| **`PORT`** | **`8080`** (recommended). Railway health checks always hit `$PORT`. **`livekit/sip` ignores `PORT`** and only listens on **`health_port`** in YAML — our **`docker-entrypoint.sh`** rewrites `health_port` to match `$PORT` at container start. Without redeploying that wrapper, you must set **`PORT=8080`** and the same value as **`health_port`** manually. |
| **`SIP_CONFIG_BODY`** | Multiline YAML — use the template in **§3** (replace placeholders). Official upstream name is **`SIP_CONFIG_BODY`** ([livekit/sip README](https://github.com/livekit/sip/blob/main/README.md)); the image reads it from the environment — **no** custom `startCommand` is required. |

Optional split (still need `redis` in YAML):

- `LIVEKIT_WS_URL` = `wss://callplane-production.up.railway.app`
- `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` — same id/secret as the SFU `keys:` map

---

## 3) `SIP_CONFIG_BODY` template (copy → paste → replace `YOUR_*`)

```yaml
# health_port is rewritten to Railway $PORT by docker-entrypoint.sh (set PORT=8080 recommended).
health_port: 8080

api_key: YOUR_KEY_ID
api_secret: YOUR_KEY_SECRET
ws_url: wss://callplane-production.up.railway.app

redis:
  address: YOUR_REDIS_HOST:6379
  password: YOUR_REDIS_PASSWORD

sip_port: 5060

# Narrow RTP range (Railway still cannot map arbitrary inbound UDP for media).
rtp_port: 10000-10100

# First deploy: omit use_external_ip (see config/railway-sip-minimal.yaml).
# STUN (use_external_ip: true) can fail on Railway and exit before health HTTP starts.
# After TCP proxy: set nat_1_to_1_ip OR sip_hostname with use_external_ip: false —
# do NOT set use_external_ip: true and nat_1_to_1_ip together (sip will error).
# use_external_ip: false
# nat_1_to_1_ip: YOUR_TCP_PROXY_PUBLIC_IP
# sip_hostname: sip.example.com

logging:
  level: info
```

**Placeholders**

| Placeholder | Where to copy from |
|-------------|-------------------|
| `YOUR_KEY_ID` / `YOUR_KEY_SECRET` | **livekit-callplane** service → **`LIVEKIT_CONFIG`** YAML → `keys:` — the **map key** is the API key id, the **map value** is the secret. Same pair the SFU uses. |
| `YOUR_REDIS_HOST` / `YOUR_REDIS_PASSWORD` | Same **`LIVEKIT_CONFIG`** YAML block `redis.address` / `redis.password` (Railway **private** Redis hostname, e.g. `*.railway.internal`, not `localhost`). |

**YAML tips:** If Redis password contains `:` or `#`, quote it: `password: '...'`.

---

## 4) TCP proxy for SIP signaling (5060)

1. Railway → **livekit-sip** service → **Networking** (or **Public Networking**).
2. Add **TCP Proxy** → **application / container port `5060`** (SIP signaling over TCP).
3. Note the public host (e.g. `*.proxy.rlwy.net`) and **assigned port** (often not `5060` on the edge). **Telnyx must use this host + port** — not `*.up.railway.app` and not `wss://…`.

Optional later: second TCP proxy on **5061** only if you enable `tls:` in config and have certs.

---

## 5) Post-deploy: advertised IP / hostname (for SDP / Telnyx)

1. From the TCP proxy hostname: `dig +short <proxy-hostname>` → public IP.
2. In **`SIP_CONFIG_BODY`**, either:
   - set **`nat_1_to_1_ip`** to that IP and set **`use_external_ip: false`**, or  
   - set **`sip_hostname`** to a DNS name (CNAME → proxy hostname).

---

## 6) Post-deploy: trunk + dispatch (LiveKit CLI — requires `lk` installed)

Commands talk to the **SFU** URL and API key/secret (same as `ws_url` / `keys:`).

```bash
# --url / --api-key / --api-secret are global lk flags (before the "sip" subcommand).
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
  --trunks "<inbound-trunk-id-from-previous-command>" \
  --direct "my-sip-room"
```

For fields not exposed by flags (e.g. full allowed address lists), use **JSON** with the CLI’s request support — see `lk sip inbound create --help` and [Inbound trunk](https://docs.livekit.io/sip/trunk-inbound/).

**HTTP alternative:** SIP admin APIs are on the **LiveKit server** — same host as `ws_url`, with server API auth; see [LiveKit telephony / SIP trunk setup](https://docs.livekit.io/telephony/start/sip-trunk-setup/).

---

## 7) Telnyx (Mission Control) — FQDN connection

| Field | What to enter |
|------|----------------|
| Connection type | **FQDN** |
| FQDN / host | Railway **TCP proxy** hostname (or your **CNAME** to that hostname) |
| Port | Railway’s **TCP proxy port** (dashboard), **not** 443 / not 5060 unless Railway shows 5060 |
| Transport | **TCP** (TLS only if you exposed 5061 + TLS in SIP config) |
| Auth | Match **`auth-user` / `auth-pass`** (or JSON) on the LiveKit **inbound** trunk |
| Allowed IPs | Telnyx signaling ranges + any IPs LiveKit trunk configuration requires |

Docs: [Telnyx + LiveKit](https://docs.livekit.io/telephony/start/providers/telnyx/), [Telnyx LiveKit guide](https://developers.telnyx.com/docs/voice/sip-trunking/livekit-configuration-guide).

---

## 8) Reality check (Railway)

- **Inbound UDP** (5060/udp, RTP) is **not** generally available on Railway’s public edge. Signaling over **S**IP **/ TCP** via the proxy may work; **one-way audio / no audio** often means **RTP UDP** never reaches the bridge. See **`livekit-sip/README.md`** and **`CALLPLANE.md`**.

---

## Verify

- Deploy logs: SIP listening on **5060**, Redis connected, WebSocket to **callplane-production** OK.
- Health: Railway gets **200** on **`/`** with body **`OK`** (because **`health_port`** matches **`$PORT`**).
- From laptop: `nc -vz <tcp-proxy-host> <tcp-proxy-port>` succeeds.

---

## 9) Health check failed — troubleshooting

**Default (2026):** `livekit-sip/railway.toml` ships **without** `healthcheckPath` so deploys are not marked failed while you read logs. Re-enable health checks only after logs show **`service ready`**.

When `healthcheckPath = "/"` is enabled, Railway marks the deploy failed when **`GET $PORT/`** never returns **200** within the timeout (`healthcheckTimeout` in `railway.toml`, or `RAILWAY_HEALTHCHECK_TIMEOUT_SEC`).

### How livekit/sip health works (v1.3.0)

| Topic | Behavior |
|-------|----------|
| **Config env** | **`SIP_CONFIG_BODY`** (multiline YAML) or **`SIP_CONFIG_FILE`** — official upstream names |
| **`PORT` env** | **Not read** by livekit/sip — only **`health_port`** in YAML opens the HTTP listener |
| **Health server** | Starts only when **`health_port > 0`** — listens on **`0.0.0.0:health_port`** |
| **`GET /`** | **200** + body **`OK`** when healthy; **503** if not started / shutting down; **429** if under CPU load |
| **Startup order** | Parse YAML → connect **Redis** (fail = exit) → SIP + STUN if `use_external_ip` (fail = exit) → bind health HTTP in `svc.Run()` |

Our **`docker-entrypoint.sh`** injects/overwrites **`health_port:`** from Railway’s **`$PORT`** before the binary starts — redeploy after pulling this fix if health failed with “service unavailable” and logs showed SIP running on 8080 but Railway probed a different port.

### Immediate dashboard actions (do in order)

1. **Variables → `PORT`:** set **`8080`** (stable, matches docs; entrypoint will align `health_port`).
2. **Variables → `SIP_CONFIG_BODY`:** confirm multiline YAML — not empty, not JSON, placeholders replaced:
   - `api_key` / `api_secret` — same as **livekit-callplane** `LIVEKIT_CONFIG` → `keys:`
   - `ws_url: wss://callplane-production.up.railway.app`
   - `redis.address` — private hostname (`*.railway.internal`), **not** `localhost`
   - `redis.password` — quote if it contains `:` or `#`
   - **`health_port: 8080`** (optional if entrypoint wrapper is deployed)
   - **Do not** set **`use_external_ip: true`** and **`nat_1_to_1_ip`** together (process exits on config error)
3. **Settings → Root Directory:** **`livekit-sip`**
4. **Redeploy** after variable fixes.
5. **Still failing with healthcheck enabled?** Remove **`healthcheckPath`** from `livekit-sip/railway.toml` (or clear Health Check Path in dashboard), redeploy, read **Deploy logs** — re-enable once process stays up.

### Deploy logs — grep patterns

In Railway → **livekit-sip** → **Deployments** → latest → **View logs**, search for:

| Pattern | If found |
|---------|----------|
| `[docker-entrypoint] Set health_port` or `Prepended health_port` | Entrypoint ran; probe port should match `$PORT` |
| `SIP_CONFIG_BODY is empty` | Variable missing, wrong name, or not multiline YAML |
| `SIP_CONFIG_BODY or SIP_CONFIG_FILE is required` | Upstream binary started without config (should not happen with our entrypoint) |
| `could not parse config` | Fix YAML indentation / quoting |
| `redis configuration is required` | Add `redis:` block |
| `could not resolve external IP` | Set `use_external_ip: false` or use minimal config |
| `use_external_ip and nat_1_to_1_ip` | Pick one NAT mode only |
| `service ready` | Process up — safe to re-enable `healthcheckPath = "/"` |
| `connection refused` (Redis) | Wrong `redis.address` / password |
| *(no logs)* | Wrong **Root Directory** or build failed |

### Deploy logs — what to look for

| Log / error | Meaning | Fix |
|-------------|---------|-----|
| `could not parse config` / YAML error | Bad **`SIP_CONFIG_BODY`** | Fix indentation; quote special chars in passwords |
| `could not resolve external IP` | **`use_external_ip: true`** + STUN blocked/failed | Use [`config/railway-sip-minimal.yaml`](config/railway-sip-minimal.yaml) (no STUN) for first boot |
| `use_external_ip and nat_1_to_1_ip can not both be set` | Conflicting NAT flags | Use one: `use_external_ip: true` **or** `nat_1_to_1_ip` + `use_external_ip: false` |
| `redis configuration is required` | Missing `redis:` block | Add `redis.address` + `password` |
| Redis connection refused / timeout | Wrong host or password | Copy from SFU service; use `*.railway.internal` |
| Process exits before `sip service ready` | API keys / ws_url / SIP bind error | Fix keys; check `ws_url` is `wss://…` not `https://` |
| `sip service ready` / `service ready` but health fails | **`PORT` ≠ `health_port`** (pre-entrypoint image) | Set **`PORT=8080`**, redeploy with **`docker-entrypoint.sh`**, or match ports manually |
| No log lines at all | Build/start crash | Confirm Dockerfile build, root directory `livekit-sip` |

### Exact Railway variables (copy checklist)

| Variable | Example / source |
|----------|------------------|
| **`PORT`** | `8080` |
| **`SIP_CONFIG_BODY`** | Full YAML from [`config/railway-sip.yaml`](config/railway-sip.yaml) with `YOUR_*` replaced |
| *(optional)* **`RAILWAY_HEALTHCHECK_TIMEOUT_SEC`** | `300` — only if startup is slow (Redis cold start) |

Do **not** set `LIVEKIT_CONFIG` on this service — that is for **livekit-callplane** only. SIP uses **`SIP_CONFIG_BODY`**.

### Quick local sanity check

```bash
cd livekit-sip
export PORT=8080
export SIP_CONFIG_BODY="$(cat config/railway-sip.yaml)"   # after replacing YOUR_*
docker build -t callplane-sip .
docker run --rm -e PORT -e SIP_CONFIG_BODY -p 8080:8080 callplane-sip
# another terminal:
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/   # expect 200
```

---

## 10) If health check STILL fails (after PORT + SIP_CONFIG_BODY)

Work through this list in order. Most failures are **process exit before HTTP**, not a wrong health path.

### A. Confirm deploy surface

| Check | Expected |
|-------|----------|
| **Root Directory** | `livekit-sip` (not repo root) |
| **Branch** | Branch that contains `docker-entrypoint.sh` + latest `railway.toml` |
| **Build** | Dockerfile build succeeds (image `FROM livekit/sip:v1.3.0`) |
| **Variables** | `PORT=8080`, multiline **`SIP_CONFIG_BODY`** (not `LIVEKIT_CONFIG`) |

**Redeploy:** Deployments → **Redeploy** after any variable or git change (restart alone may not rebuild).

### B. Isolate config with minimal YAML

Paste [`config/railway-sip-minimal.yaml`](config/railway-sip-minimal.yaml) into **`SIP_CONFIG_BODY`** (replace `YOUR_*` only). It omits **`use_external_ip`** so STUN cannot abort startup.

```yaml
api_key: YOUR_KEY_ID
api_secret: YOUR_KEY_SECRET
ws_url: wss://callplane-production.up.railway.app
redis:
  address: YOUR_REDIS_HOST:6379
  password: YOUR_REDIS_PASSWORD
health_port: 8080
sip_port: 5060
rtp_port: 10000-10100
use_external_ip: false
logging:
  level: info
```

Set **`PORT=8080`**. Entrypoint overwrites `health_port` to match `$PORT` if present.

### C. Field names (verified vs livekit/sip v1.3.0)

| YAML key | Correct? | Notes |
|----------|----------|-------|
| `api_key` | Yes | Or env `LIVEKIT_API_KEY` |
| `api_secret` | Yes | Or env `LIVEKIT_API_SECRET` |
| `ws_url` | Yes | Must be `wss://…` for production SFU |
| `redis.address` / `password` | Yes | Use `*.railway.internal`, not `localhost` |
| `health_port` | Yes | Synced from `$PORT` by entrypoint |
| `log_level` (root) | Legacy | Prefer `logging: level: info` |

`SIP_CONFIG_FILE` works on VPS/volumes; on Railway use **`SIP_CONFIG_BODY`** only.

### D. Health check strategy

| Strategy | When |
|----------|------|
| **No `healthcheckPath`** (current default in git) | Debugging; read logs until `service ready` |
| **`healthcheckPath = "/"`** + `PORT=8080` | After logs prove process stays up |
| Dashboard **Health Check Path** | Can override `railway.toml` — if deploy still fails after git removed healthcheck, **clear** path in **Settings → Deploy** and redeploy |

**503 on `/`** means HTTP is up but monitor not ready (rare after `service ready`). **Connection refused** means wrong port or crash before `svc.Run()`.

### E. Re-enable Railway health check (optional)

In `livekit-sip/railway.toml` under `[deploy]`:

```toml
healthcheckPath = "/"
healthcheckTimeout = 300
```

Commit, push, redeploy. Or set **Health Check Path** = `/` in the dashboard (overrides toml if conflicting).

### F. Exact Railway actions (checklist)

1. **Settings → Root Directory** → `livekit-sip` → Save  
2. **Variables** → `PORT` = `8080`  
3. **Variables** → `SIP_CONFIG_BODY` → minimal YAML (§B) with real Redis + keys from **livekit-callplane** `LIVEKIT_CONFIG`  
4. **Deployments** → **Redeploy** (wait for build)  
5. **Logs** → grep `service ready` / errors from table in §9  
6. If stable → add TCP proxy **5060**, then set `nat_1_to_1_ip` or `sip_hostname` (with `use_external_ip: false`)  
7. Optional → enable `healthcheckPath` and redeploy again  

### G. `SIP_CONFIG_BODY` paste pitfalls

- Do **not** wrap the whole blob in quotes in Railway (paste raw YAML).  
- Quote Redis password if it contains `:` or `#`: `password: '...'`  
- No `YOUR_*` placeholders left in production values.  
- Keys must match SFU `keys:` — **map key** = `api_key`, **map value** = `api_secret`.
