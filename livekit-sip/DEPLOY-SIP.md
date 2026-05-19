# Railway: deploy `livekit/sip` (this attempt only)

Callplane SFU WebSocket: `wss://callplane-production.up.railway.app`  
SIP bridge root: **`livekit-sip/`** (not repo root).  
**LiveKit CLI (`lk`)** is required **after** the SIP service is healthy — trunks/dispatch rules are created against the **LiveKit server**, not the SIP container.

---

## Health fix (2026): wrapper on `$PORT` + disable probing

**What we ship now**

| Layer | Port | Role |
|-------|------|------|
| **`health-wrapper.sh`** | Railway **`$PORT`** (set **`8080`**) | Starts **before** `livekit-sip`; **`GET /` → 200** + `OK` always |
| **`livekit/sip`** | **`8081`** (`SIP_INTERNAL_HEALTH_PORT`) | Real process health (503 until ready); Railway does **not** probe this |

So deploy health can pass even if SIP is still starting, and **even if Railway keeps probing** because of a wrong root directory or sticky dashboard path.

**Config-as-code (both files in `livekit-sip/`):**

| File | Default (2026) | To disable probing |
|------|----------------|-------------------|
| `railway.toml` | `healthcheckPath = "/"` + `healthcheckTimeout = 300` | `healthcheckPath = ""` |
| `railway.json` | `"healthcheckPath": "/"` | `"healthcheckPath": null` |

Per [`railway.schema.json`](https://railway.com/railway.schema.json), `healthcheckPath` is `string | null`. **Empty string** (TOML) and **`null`** (JSON) mean “no path”. **Omitting** the key does **not** clear a sticky dashboard `/` — you must set `""` or `null` in config-as-code, or clear the dashboard field.

There is **no** `healthcheckDisabled` flag. **Default is `"/"`** because many projects cannot clear dashboard probing; **`health-wrapper.sh` always returns 200 on `$PORT`** so deploy health passes even while SIP is still starting.

### Stop healthcheck probing NOW (dashboard)

Do these on the **livekit-sip** service (not **livekit-callplane** SFU):

| Step | Where | Action |
|------|--------|--------|
| 1 | **Settings → Source** | **Root Directory** = `livekit-sip` → **Save** |
| 2 | **Settings → Deploy** (or **Health Check**) | **Health Check Path** → **clear completely** (blank, not `/`) → **Save** |
| 3 | **Variables** | **`PORT`** = `8080` |
| 4 | **Deployments** | Cancel stuck **Healthcheck** deploy if needed → **Redeploy** after git push with wrapper image |
| 5 | Latest deploy → **Details** | Config source = `livekit-sip/railway.toml` or `railway.json`; path empty **or** probing `/` is OK (wrapper still returns 200) |

### Wrong service / cloned service (common)

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Root Directory = **repo root** | Uses parent `livekit-callplane/railway.toml` → `healthcheckPath = "/"` for SFU | Set Root Directory = **`livekit-sip`** |
| Editing **livekit-callplane** (SFU) instead of **livekit-sip** | Variables/`PORT`/health path don’t match SIP Dockerfile | Open the **third** service whose root is `livekit-sip` |
| **Duplicate** GitHub service (clone) still on old commit | No `[health-wrapper]` in logs | Delete duplicate or point it at `livekit-sip` + latest branch; redeploy |
| Service display name ≠ folder | Confusing but OK if Root Directory is `livekit-sip` | Trust **Root Directory** + **Details → config file path**, not the service title |

---

## 1) New Railway service

1. Open the **same Railway project** as **livekit-callplane** and **Redis**.
2. **New** → **GitHub** → select the **`livekit-callplane`** repo.
3. **Settings → Root Directory:** `livekit-sip` (exactly).
4. Confirm **Config-as-code** picks up `livekit-sip/railway.toml` and/or `livekit-sip/railway.json`.

---

## 2) Variables (order matters conceptually — set all before first deploy)

| Variable | Value / action |
|----------|----------------|
| **`PORT`** | **`8080`** (required for stable probes). Railway always hits **`$PORT`**. Our **`health-wrapper.sh`** binds here and returns **200** immediately; **`livekit/sip`** does not use `PORT` (internal **`health_port`** → **8081** via entrypoint). |
| **`SIP_INTERNAL_HEALTH_PORT`** | Optional; default **`8081`**. livekit/sip HTTP monitor only — not probed by Railway. |
| **`SIP_CONFIG_BODY`** | Multiline YAML — use the template in **§3** (replace placeholders). Official upstream name is **`SIP_CONFIG_BODY`** ([livekit/sip README](https://github.com/livekit/sip/blob/main/README.md)); the image reads it from the environment — **no** custom `startCommand` is required. |

Optional split (still need `redis` in YAML):

- `LIVEKIT_WS_URL` = `wss://callplane-production.up.railway.app`
- `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` — same id/secret as the SFU `keys:` map

---

## 3) `SIP_CONFIG_BODY` template (copy → paste → replace `YOUR_*`)

```yaml
# Do not set health_port: 8080 — conflicts with wrapper on $PORT. Entrypoint uses 8081 internally.
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
- Health: **`curl http://$PORT/`** → **200** + `OK` from **`health-wrapper`** (logs: `[health-wrapper] Listening on 0.0.0.0:8080`).
- From laptop: `nc -vz <tcp-proxy-host> <tcp-proxy-port>` succeeds.

---

## 9) Health check failed — troubleshooting

**Default (2026):** `health-wrapper.sh` on **`$PORT`** + `healthcheckPath = "/"` in `railway.toml` / `railway.json`. Probing **`GET $PORT/`** returns **200** before SIP starts. To turn off Railway HTTP probes, set `healthcheckPath = ""` / `null` instead.

When `healthcheckPath = "/"` is enabled, Railway fails the deploy if **`GET $PORT/`** never returns **200** within the timeout. With the wrapper image, that should succeed unless **`PORT`** is wrong or the wrapper did not start.

### How health works (v1.3.0 + our wrapper)

| Topic | Behavior |
|-------|----------|
| **Railway probe** | **`$PORT`** only (set **`8080`**) → **`health-wrapper.sh`** → always **200** + `OK` |
| **livekit/sip `health_port`** | Rewritten to **`8081`** (or `SIP_INTERNAL_HEALTH_PORT`) — **not** Railway’s `$PORT` |
| **`PORT` env** | **Not read** by livekit/sip |
| **SIP `GET /` on 8081** | **200** when ready; **503** / **429** per upstream — use for debugging, not Railway |
| **Startup order** | Wrapper starts → YAML parse → Redis → SIP/STUN → SIP health on 8081 in `svc.Run()` |

Deploy logs should show **`[health-wrapper] Listening`** then **`[docker-entrypoint] Started health wrapper`** before Redis/SIP lines.

### Disable health check — dashboard (screenshot-level)

Railway UI labels move between **Deploy** and **Health Check**; use the field named **Health Check Path**.

| Step | Where | Action |
|------|--------|--------|
| 1 | **Project** → service **livekit-sip** | Open the SIP service (not livekit-callplane SFU). |
| 2 | **Settings** → **Source** | **Root Directory** = `livekit-sip` → **Save**. |
| 3 | **Settings** → **Deploy** (or **Health Check**) | Find **Health Check Path** → delete `/` so the input is **blank** → **Save**. |
| 4 | **Settings** → **Config-as-code** (if shown) | Path should be `livekit-sip/railway.toml` (or default under root). |
| 5 | **Deployments** | **Redeploy** (or cancel stuck deploy, then redeploy). |
| 6 | Latest deployment → **Details** | **Health Check Path** should show empty / none. If it still shows `/`, check Root Directory (step 2) or push git with `healthcheckPath = ""`. |

**Config-as-code vs dashboard:** Values **in** `railway.toml` / `railway.json` **override** the dashboard for that deploy. Keys **omitted** from the file still use dashboard settings. To disable from git without relying on the dashboard:

```toml
# livekit-sip/railway.toml
[deploy]
healthcheckPath = ""
```

Or `railway.json` (there is **no** `healthcheckDisabled` in the schema):

```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "deploy": {
    "healthcheckPath": null,
    "healthcheckTimeout": null
  }
}
```

**Dockerfile `HEALTHCHECK`:** Railway deploy health checks are **not** driven by Docker `HEALTHCHECK` instructions. Our `Dockerfile` has none. Disabling is only about Railway’s **Health Check Path** / `healthcheckPath`.

### Immediate dashboard actions (do in order)

1. **Settings → Deploy → Health Check Path:** **clear** (empty) → **Save** — see table above.
2. **Settings → Source → Root Directory:** **`livekit-sip`** (avoids parent `railway.toml` with `healthcheckPath = "/"`).
3. **Variables → `PORT`:** set **`8080`** (stable; entrypoint aligns `health_port`).
4. **Variables → `SIP_CONFIG_BODY`:** confirm multiline YAML — not empty, not JSON, placeholders replaced:
   - `api_key` / `api_secret` — same as **livekit-callplane** `LIVEKIT_CONFIG` → `keys:`
   - `ws_url: wss://callplane-production.up.railway.app`
   - `redis.address` — private hostname (`*.railway.internal`), **not** `localhost`
   - `redis.password` — quote if it contains `:` or `#`
   - **Do not** set **`health_port: 8080`** (conflicts with wrapper; entrypoint uses **8081**)
   - **Do not** set **`use_external_ip: true`** and **`nat_1_to_1_ip`** together (process exits on config error)
5. **Redeploy** after steps 1–4; read **Deploy logs** until `service ready`.
6. **Still probing after clear + redeploy?** Push/pull `healthcheckPath = ""` in `livekit-sip/railway.toml` and redeploy; on deployment **Details**, confirm the path is empty and config source is `livekit-sip/railway.toml`.

### Deploy logs — grep patterns

In Railway → **livekit-sip** → **Deployments** → latest → **View logs**, search for:

| Pattern | If found |
|---------|----------|
| `[health-wrapper] Listening` | Wrapper bound `$PORT` — Railway probe should get 200 |
| `[docker-entrypoint] Set health_port` / `Started health wrapper` | Entrypoint ran; sip on 8081, wrapper on `$PORT` |
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
| `service ready` but health fails | Old image (no wrapper) or **`PORT`** unset | Push latest `livekit-sip/`, set **`PORT=8080`**, grep `[health-wrapper]` in logs |
| `Address already in use` on 8080 | **`health_port: 8080`** in YAML fights wrapper | Remove `health_port` from YAML; let entrypoint set **8081** |
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

## 10) If health check STILL fails (nuclear options)

Work through this list in order.

### If STILL probing after `healthcheckPath=""` + redeploy

1. **Confirm service:** Project → service whose **Settings → Source → Root Directory** = `livekit-sip` (not the SFU).
2. **Deployment Details:** Config file path must be under `livekit-sip/` (`railway.toml` or `railway.json`). If it shows repo-root `railway.toml`, fix Root Directory and redeploy.
3. **Push this repo** so the image includes `health-wrapper.sh` + `python3-minimal`. Logs must contain `[health-wrapper] Listening`.
4. **Variables:** `PORT=8080`; remove `health_port: 8080` from `SIP_CONFIG_BODY` if present.
5. **Dashboard:** Clear **Health Check Path** anyway → Save → **Redeploy** (not just Restart).
6. **Nuclear A — new service:** **New** → same GitHub repo → Root Directory `livekit-sip` → copy variables from old service → delete old duplicate service.
7. **Nuclear B — allow probing:** Leave path as `/` on dashboard; with wrapper, **`GET $PORT/`** should still return **200** once the new image is live.
8. **Nuclear C — Railway support:** If Details shows probing but config-as-code has `null`/`""` and Root Directory is correct, attach deployment ID (platform bug / stale config).

### If deploy fails for other reasons (not probing)

Most failures are **process exit before SIP is useful**, not health path.

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
sip_port: 5060
rtp_port: 10000-10100
use_external_ip: false
logging:
  level: info
```

Set **`PORT=8080`**. Do **not** add `health_port: 8080` (entrypoint sets internal **8081**).

### C. Field names (verified vs livekit/sip v1.3.0)

| YAML key | Correct? | Notes |
|----------|----------|-------|
| `api_key` | Yes | Or env `LIVEKIT_API_KEY` |
| `api_secret` | Yes | Or env `LIVEKIT_API_SECRET` |
| `ws_url` | Yes | Must be `wss://…` for production SFU |
| `redis.address` / `password` | Yes | Use `*.railway.internal`, not `localhost` |
| `health_port` | Optional | Entrypoint sets **8081**; omit or avoid **8080** |
| `log_level` (root) | Legacy | Prefer `logging: level: info` |

`SIP_CONFIG_FILE` works on VPS/volumes; on Railway use **`SIP_CONFIG_BODY`** only.

### D. Health check strategy

| Strategy | When |
|----------|------|
| **`health-wrapper` on `$PORT`** (current default) | Probing always passes on `$PORT`; SIP can still exit on Redis/STUN |
| **`healthcheckPath = "/"`** + wrapper (default) | Deploy health passes; wrapper returns 200 even while SIP starts |
| **`healthcheckPath = ""`** + **`railway.json` null** | Turn off Railway HTTP probes entirely |
| **Dashboard path cleared** + redeploy | No git; may still probe until config-as-code deploy |
| **Omitting `healthcheckPath` from toml** | Does **not** disable checks — dashboard path still applies |

**503 on `$PORT/`** should not happen with the wrapper (always 200). **503 on `:8081/`** means SIP monitor not ready. **Connection refused on `$PORT`** means wrapper failed to start (check build logs, `python3`, port conflict).

### E. Re-enable Railway health check (optional)

In `livekit-sip/railway.toml` under `[deploy]`:

```toml
healthcheckPath = "/"
healthcheckTimeout = 300
```

Commit, push, redeploy. Dashboard-only changes apply only for keys **omitted** from `railway.toml`; if the file sets `healthcheckPath = ""`, push an updated toml (or remove that line and set `/` in the dashboard) before re-enabling.

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
