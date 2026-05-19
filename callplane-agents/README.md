# Callplane Agents (skeleton)

Separate **Python worker** from LiveKit Server. Railway runs one container per service: use one Railway service for `livekit-callplane` (this repo’s Go server) and **another** service built from this folder for agents.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `LIVEKIT_URL` | `wss://…` URL of your LiveKit deploy (e.g. Railway public domain). |
| `LIVEKIT_API_KEY` | Key **id** from server `keys:` map (not the secret name alone). |
| `LIVEKIT_API_SECRET` | Secret for that key. |
| `DEEPGRAM_API_KEY` | Deepgram. |
| `ELEVEN_API_KEY` | ElevenLabs (PyPI plugin expects this name). |
| `OPENAI_API_KEY` | Used by `livekit-plugins-openai` for the LLM in `agent.py`; swap code if you use another LLM. |

## Local quick run

```bash
cd callplane-agents
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export LIVEKIT_URL=wss://your-host
export LIVEKIT_API_KEY=...
export LIVEKIT_API_SECRET=...
export DEEPGRAM_API_KEY=...
export ELEVEN_API_KEY=...
export OPENAI_API_KEY=...
python agent.py download-files  # optional first run
python agent.py dev
```

## Railway

- New service → deploy from same repo with **Root Directory** `callplane-agents` (or paste Dockerfile path).
- Set variables above; **do not** reuse `LIVEKIT_CONFIG` here — that is only for the Go media server.
- Agents open **outbound** WebSockets to `LIVEKIT_URL`; no inbound UDP needed on the worker service.

Replace `agent.py` with your production prompts, tools, and model choices.
