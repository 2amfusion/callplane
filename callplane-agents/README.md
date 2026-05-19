# Callplane Agents → BiteBuddy

Separate **Python worker** from LiveKit Server. Phone calls: **Telnyx → livekit/sip → room → this worker** (STT/TTS here; **LLM brain** on bitebuddy-backend WebSocket).

## Environment variables

| Variable | Purpose |
|----------|---------|
| `LIVEKIT_URL` | `wss://…` URL of your LiveKit SFU (e.g. Railway public domain). |
| `LIVEKIT_API_KEY` | Key **id** from server `keys:` map. |
| `LIVEKIT_API_SECRET` | Secret for that key. |
| `DEEPGRAM_API_KEY` | Deepgram STT. |
| `ELEVEN_API_KEY` | ElevenLabs TTS. |
| `BITE_BUDDY_WS_URL` | Base WebSocket URL, e.g. `wss://api.bitebuddy.ai/ai/chat/ws/completions` (no trailing `/{call_id}`). |
| `AGENT_NAME` | Worker registration name; default `callplane-voice`. Must match SIP dispatch `roomConfig.agents[].agentName`. |

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
export BITE_BUDDY_WS_URL=wss://api.bitebuddy.ai/ai/chat/ws/completions
export AGENT_NAME=callplane-voice
python agent.py download-files  # optional first run
python agent.py dev
```

## Railway

1. New service → same GitHub repo → **Root Directory** `callplane-agents`.
2. Uses `callplane-agents/railway.toml` + `Dockerfile` (`python agent.py start`).
3. Set all env vars above. Worker exposes `GET /` for Railway health (LiveKit agents HTTP server on `$PORT`).
4. **Outbound only** to `LIVEKIT_URL` and `BITE_BUDDY_WS_URL` — no inbound UDP on this service.

## SIP dispatch (after trunk exists)

Register explicit agent dispatch so inbound PSTN jobs route to this worker (`AGENT_NAME`):

```bash
lk --url "wss://YOUR_LIVEKIT_HOST" \
  --api-key "YOUR_KEY_ID" \
  --api-secret "YOUR_KEY_SECRET" \
  sip dispatch create dispatch-callplane-voice.json
```

`dispatch-callplane-voice.json`:

```json
{
  "dispatchRule": {
    "name": "callplane-voice-inbound",
    "trunkIds": ["<your-inbound-trunk-id>"],
    "rule": {
      "dispatchRuleIndividual": {
        "roomPrefix": "call-"
      }
    },
    "roomConfig": {
      "agents": [
        {
          "agentName": "callplane-voice",
          "metadata": "telnyx-inbound"
        }
      ]
    }
  }
}
```

Or CLI flags only (no agent — add JSON for `agentName`):

```bash
lk --url "wss://YOUR_LIVEKIT_HOST" \
  --api-key "YOUR_KEY_ID" \
  --api-secret "YOUR_KEY_SECRET" \
  sip dispatch create \
  --name callplane-voice-inbound \
  --trunks "<inbound-trunk-id>" \
  --individual "call-" \
  --randomize
```

For agent dispatch you need the JSON file (or API) with `roomConfig.agents`.

See also `CALLPLANE.md` and `livekit-sip/DEPLOY-SIP.md`.
