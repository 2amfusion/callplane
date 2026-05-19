# livekit/sip on Railway (Callplane)

SIP bridge between **Telnyx** (PSTN) and **livekit-callplane** (WebRTC SFU). This folder is a thin Docker wrapper around the official [`livekit/sip`](https://github.com/livekit/sip) image — deploy it as a **third Railway service** in the same project as `livekit-callplane` and Redis.

**LiveKit server (signaling):** `wss://callplane-production.up.railway.app`

---

## What `livekit/sip` needs

| Requirement | Why |
|-------------|-----|
| **Same Redis** as `livekit-server` | Session state + coordination with the SFU |
| **`api_key` / `api_secret`** | Same pair as in `livekit-callplane` `keys:` |
| **`ws_url`** | WebSocket URL of your LiveKit server (`wss://…`) |
| **Public SIP endpoint** | Telnyx sends INVITEs here (signaling) |
| **Public RTP (UDP)** | Telnyx sends audio here (media) — **see Railway UDP caveat below** |

### Ports (container)

| Port | Protocol | Purpose |
|------|----------|---------|
| **5060** | UDP + TCP | SIP signaling (default) |
| **5061** | TCP (TLS) | Optional SIP over TLS |
| **10000–20000** (default) | **UDP** | RTP media (`rtp_port` in config; narrow in template) |
| **8080** (you choose) | HTTP | Health checks (`health_port`) |

### Config delivery

Upstream supports either:

1. **`SIP_CONFIG_BODY`** — multiline YAML in one Railway variable (recommended).
2. **`SIP_CONFIG_FILE`** — path to a mounted file (not typical on Railway).
3. **Env overrides** for core LiveKit fields: `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_WS_URL` (still need `redis:` in YAML).

Official reference: [livekit/sip README](https://github.com/livekit/sip/blob/main/README.md), [docker-compose.yaml](https://github.com/livekit/sip/blob/main/docker-compose.yaml).

---

## Railway UDP reality (2025–2026)

| Traffic | Railway public edge |
|---------|---------------------|
| **Outbound UDP** from your container | Supported (STUN, DNS, carrier callbacks you initiate) |
| **Inbound UDP** (SIP 5060/udp, RTP 10000+) | **Not supported** — no dashboard toggle exists |
| **Inbound TCP** | **TCP Proxy** per port (`*.proxy.rlwy.net:xxxxx`) |

**Practical expectation:** You can deploy this service on Railway and pass health checks, but **PSTN calls will likely fail at media setup** until RTP UDP reaches your bridge. Signaling over **SIP/TCP or TLS** via TCP Proxy may partially work; **RTP almost always requires inbound UDP**.

If calls connect but are silent/no audio → RTP is not reaching the container. Plan B: run `livekit/sip` on Fly.io, a VPS, or LiveKit Cloud telephony.

---

## Deploy steps (Railway)

**Copy-paste checklist for the current Railway setup:** [`DEPLOY-SIP.md`](DEPLOY-SIP.md)  
(**Important:** set service variable **`PORT=8080`** so it matches **`health_port`** in `SIP_CONFIG_BODY` — Railway’s health probe always uses `$PORT`.)

### 1. Create the service

1. Same Railway project as **livekit-callplane** + **Redis**.
2. **New service** → Deploy from GitHub → repo `livekit-callplane`.
3. **Settings → Root Directory:** `livekit-sip`
4. **Settings → Config-as-code:** detects `livekit-sip/railway.toml`.

### 2. Variables

| Variable | Purpose |
|----------|---------|
| **`PORT`** | **`8080`** (recommended) — must equal **`health_port`** in your YAML. Railway sends deploy health checks to `http://…:$PORT/` only. |
| **`SIP_CONFIG_BODY`** | Full multiline YAML (see template). Upstream reads this env var by name — no `startCommand` override needed. |

**Option A — `SIP_CONFIG_BODY` (recommended)**

1. Copy [`config/railway-sip.yaml`](config/railway-sip.yaml), replace `YOUR_*`.
2. Railway → **livekit-sip** → **Variables** → `SIP_CONFIG_BODY` → paste full YAML.
3. Set **`PORT=8080`** if `health_port` is 8080.

**Option B — split env vars**

| Variable | Example |
|----------|---------|
| `LIVEKIT_WS_URL` | `wss://callplane-production.up.railway.app` |
| `LIVEKIT_API_KEY` | Key id from server `keys:` |
| `LIVEKIT_API_SECRET` | Matching secret |
| `SIP_CONFIG_BODY` | Minimal YAML with only `redis:`, `health_port`, `sip_port`, `rtp_port`, `use_external_ip` |

Redis **must** match the SFU service (private hostname):

```yaml
redis:
  address: redis.railway.internal:6379
  password: <same as livekit-callplane>
```

### 3. Networking (dashboard)

See **Railway dashboard checklist** in [CALLPLANE.md](../CALLPLANE.md#railway-dashboard-checklist--livekit-sip).

Summary:

1. **Do not** rely on “Generate Domain” HTTPS for SIP — that is HTTP only.
2. Add **TCP Proxy** → application port **5060** (SIP signaling over TCP).
3. Optional second TCP Proxy → **5061** if you enable `tls:` in config.
4. **Health:** `health_port: 8080` in config; `railway.toml` checks `GET /`.
5. **No UDP UI** — you cannot map `10000-20000/udp` like Docker `-p`. Document for future Railway UDP support.

### 4. Advertised IP / hostname

After TCP proxy is created, Railway shows e.g. `shuttle.proxy.rlwy.net:15140`.

- Resolve IP: `dig +short shuttle.proxy.rlwy.net`
- Set in `SIP_CONFIG_BODY`:
  - `nat_1_to_1_ip: <that-ip>` and set **`use_external_ip: false`** (both cannot be true) **or**
  - `sip_hostname: sip.yourdomain.com` with DNS **CNAME** → `shuttle.proxy.rlwy.net` (Telnyx FQDN trunk)

Telnyx must send signaling to **`hostname:proxyPort`**, not `*.railway.app` HTTPS URL.

### 5. LiveKit SIP API resources

Create trunk + dispatch rule against your server (CLI or API), e.g.:

```bash
lk --url wss://callplane-production.up.railway.app \
  --api-key "$LIVEKIT_API_KEY" --api-secret "$LIVEKIT_API_SECRET" \
  sip inbound create \
  --name telnyx-inbound --numbers "+1XXXXXXXXXX"
```

See [LiveKit telephony docs](https://docs.livekit.io/telephony/) and Telnyx section in `CALLPLANE.md`.

Use **global** `lk` flags before `sip` (`--url`, `--api-key`, `--api-secret` — see `lk sip inbound create --help`).

### 6. Deploy and verify

1. Deploy logs: `livekit-sip` connected to Redis, listening on 5060.
2. Health check **200** on `/` — requires **`PORT=8080`** (Railway) matching **`health_port: 8080`** in YAML.
3. From outside Railway: `nc -vz shuttle.proxy.rlwy.net <tcp-proxy-port>` (SIP TCP).
4. Place test call via Telnyx — if signaling OK but no audio, RTP/UDP is the blocker.

---

## Telnyx trunk checklist (Railway hostname)

Use the **TCP proxy hostname + port** from step 3, not the LiveKit WSS URL.

| Step | Telnyx Mission Control | Value |
|------|------------------------|-------|
| 1 | **SIP Connection** → type | **FQDN** |
| 2 | FQDN / SIP URI host | `shuttle.proxy.rlwy.net` (or your CNAME, e.g. `sip.callplane.ai`) |
| 3 | Port | Railway TCP proxy port (e.g. `15140`), **not** 443 |
| 4 | Transport | **TCP** or **TLS** if you exposed 5061 + certs — avoid assuming UDP 5060 on Railway |
| 5 | Outbound auth | Match `inbound_username` / `inbound_password` on LiveKit SIP trunk |
| 6 | Inbound allowed IPs | Telnyx signaling IP ranges + your LiveKit trunk `inbound_addresses` |
| 7 | Outbound Voice Profile | Linked to the connection |
| 8 | Phone number | Assigned to connection / program |
| 9 | LiveKit `SIPInboundTrunk` | `inbound_addresses` includes Telnyx IPs; credentials match Telnyx |
| 10 | LiveKit `SIPDispatchRule` | Room / agent dispatch for inbound calls |
| 11 | Media (RTP) | Telnyx sends UDP to negotiated IP:port — **will fail on Railway** until inbound UDP exists; verify with SIP logs |

Docs: [LiveKit + Telnyx](https://docs.livekit.io/telephony/start/providers/telnyx/), [Telnyx LiveKit guide](https://developers.telnyx.com/docs/voice/sip-trunking/livekit-configuration-guide).

---

## Local smoke test (Docker)

```bash
# Same Redis + keys as dev LiveKit — replace placeholders inside config/railway-sip.yaml first.
cd livekit-sip
export SIP_CONFIG_BODY="$(cat config/railway-sip.yaml)"
docker build -t callplane-sip .
docker run --rm --network host \
  -e SIP_CONFIG_BODY \
  callplane-sip
```

`--network host` helps with wide UDP RTP ranges on Linux. On macOS Docker Desktop, use `host.docker.internal` in `redis.address` / `ws_url` instead of localhost.

---

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | `FROM livekit/sip:v1.3.0` |
| `railway.toml` | Build + health check |
| `config/railway-sip.yaml` | `SIP_CONFIG_BODY` template |
| `DEPLOY-SIP.md` | Railway checklist (PORT, TCP proxy, Telnyx, `lk` commands) |
| `.env.example` | Variable name reference |
