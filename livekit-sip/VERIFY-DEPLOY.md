# Verify livekit-sip Railway deploy

Use this when **livekit-callplane (SFU) is healthy** but **livekit-sip** healthcheck shows **"service unavailable"**.

---

## 1) Confirm commits are on GitHub

```bash
cd livekit-callplane
git log -3 --oneline
git status   # should say "up to date with origin/main"
```

Railway only builds what is pushed. If `git status` shows unpushed commits, push `main` and **Redeploy** the SIP service.

---

## 2) Confirm Railway built **livekit-sip** (not the SFU)

Open the **livekit-sip** service (not livekit-callplane) → **Deployments** → latest deploy → **Build logs**.

| Build log must include | Meaning |
|------------------------|---------|
| `COPY health-wrapper.sh /health-wrapper.sh` | Correct Dockerfile from `livekit-sip/` |
| `COPY docker-entrypoint.sh /docker-entrypoint.sh` | SIP image, not repo-root SFU |
| `apt-get install ... python3 python3-yaml` | Health wrapper can bind `$PORT` |

If build logs show **`livekit-server`** or **no `health-wrapper.sh` COPY**, Root Directory is wrong.

| Setting | livekit-sip (SIP) | livekit-callplane (SFU) |
|---------|-------------------|---------------------------|
| **Root Directory** | `livekit-sip` | *(empty / repo root)* |
| **Config file** | `livekit-sip/railway.json` | `railway.toml` |
| **Start Command** | `/bin/sh -c '/health-wrapper.sh & sleep 2; exec /docker-entrypoint.sh'` | `/bin/sh -c 'exec /livekit-server --port "${PORT:-7880}"'` |
| **Main env var** | `SIP_CONFIG_BODY` | `LIVEKIT_CONFIG` |
| **Deploy log prefix** | `[health-wrapper]` / `[docker-entrypoint]` | LiveKit server startup |

---

## 3) Deploy logs — first 15 lines

After deploy, open **Deploy logs** (runtime, not build).

**Healthy SIP service (in order):**

1. `[health-wrapper] starting`
2. `[health-wrapper] PORT=<number>` — must match Railway-injected `$PORT`
3. `[health-wrapper] Listening on 0.0.0.0:<same number>`
4. `[docker-entrypoint] entrypoint start (PORT=<same> …)`
5. `[docker-entrypoint] health already responding on PORT=…` **or** `health-wrapper ready on PORT=…`

| Log pattern | Most likely cause | Action |
|-------------|-------------------|--------|
| **No logs at all** | Wrong service selected, build failed, or Root Directory = repo root | Fix Root Directory → `livekit-sip`; redeploy |
| **`livekit-server`** / `--port` in logs | SFU image running on SIP service | Root Directory = `livekit-sip`; clear custom Start Command in dashboard |
| **No `[health-wrapper]`** | Old image or Start Command bypasses wrapper | Redeploy latest `main`; Start Command must match `railway.json` |
| **`python3 not found`** | Stale build without Dockerfile python install | Redeploy (force rebuild) |
| **`SIP_CONFIG_BODY is empty`** | Missing variable | Paste YAML in Railway Variables (see `DEPLOY-SIP.md`) |
| Wrapper listens, health still fails | Manual `PORT=8080` overrides Railway `$PORT` | **Delete** manual `PORT` variable; redeploy |

---

## 4) Optional Railway variable

If health flaps during slow SIP startup, add on the **livekit-sip** service:

| Variable | Value |
|----------|-------|
| `RAILWAY_HEALTHCHECK_TIMEOUT_SEC` | `300` |

`livekit-sip/railway.json` already sets `healthcheckTimeout: 300`; the env var is a belt-and-suspenders override if the dashboard disagrees.

---

## 5) Dashboard checklist (screenshot these)

**Settings → Source**

- Root Directory: **`livekit-sip`**

**Settings → Deploy**

- Start Command: `/bin/sh -c '/health-wrapper.sh & sleep 2; exec /docker-entrypoint.sh'`
- Healthcheck path: `/`
- Healthcheck timeout: `300`

**Variables**

- `SIP_CONFIG_BODY` — multiline YAML (see `config/railway-sip-minimal.yaml`)
- **Do not** set `LIVEKIT_CONFIG` on this service
- **Do not** set manual `PORT` unless Railway support asks

---

## 6) When to delete and recreate the service

Recreate only if:

- Root Directory was wrong for multiple deploys and dashboard **Start Command** is stuck on `livekit-server …`
- Config-as-code never picks up `livekit-sip/railway.json` after fixing root
- You accidentally edited the SFU service instead of creating a third service

Steps:

1. Note down `SIP_CONFIG_BODY` and TCP proxy settings.
2. **New** service → same repo → Root Directory **`livekit-sip`**.
3. Paste variables; add TCP proxy on **5060**.
4. Deploy; confirm build log has `COPY health-wrapper.sh`.

---

## 7) Paste this if still failing

Copy from Railway and paste in support / chat:

1. Service name (exact title in Railway UI)
2. Root Directory screenshot
3. Start Command field (Deploy settings)
4. First **15 lines** of **Deploy logs** (runtime)
5. First **10 lines** of **Build logs** (look for `COPY health-wrapper`)

Without deploy logs, the usual answer is: **wrong Root Directory or wrong service** — not a code bug.
