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

# After TCP proxy exists: EITHER keep use_external_ip OR set nat_1_to_1_ip / sip_hostname —
# do NOT set use_external_ip: true and nat_1_to_1_ip at the same time (sip will error).
use_external_ip: true
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

Railway marks the deploy failed when **`GET $PORT/`** never returns **200** within the timeout (`healthcheckTimeout = 300` in `railway.toml`, or `RAILWAY_HEALTHCHECK_TIMEOUT_SEC`).

### How livekit/sip health works (v1.3.0)

| Topic | Behavior |
|-------|----------|
| **Config env** | **`SIP_CONFIG_BODY`** (multiline YAML) or **`SIP_CONFIG_FILE`** — official upstream names |
| **`PORT` env** | **Not read** by livekit/sip — only **`health_port`** in YAML opens the HTTP listener |
| **Health server** | Starts only when **`health_port > 0`** — listens on **`0.0.0.0:health_port`** |
| **`GET /`** | **200** + body **`OK`** when healthy; **503** if not started / shutting down; **429** if under CPU load |
| **Startup order** | Parse YAML → connect **Redis** (fail = exit, no health port) → start SIP → bind health HTTP |

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
5. **Still failing?** Temporarily remove **`healthcheckPath`** from `livekit-sip/railway.toml` (or clear Health Check Path in dashboard), redeploy, read **Deploy logs** — re-enable once process stays up.

### Deploy logs — what to look for

| Log / error | Meaning | Fix |
|-------------|---------|-----|
| `could not parse config` / YAML error | Bad **`SIP_CONFIG_BODY`** | Fix indentation; quote special chars in passwords |
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
