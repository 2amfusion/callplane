"""
Minimal LiveKit Agents worker for Callplane.

Layman's terms:
- LiveKit Server (Railway) hosts the "room" and moves audio packets around.
- This script is a separate worker process that LiveKit dispatches when a session
  needs an AI agent. It joins the room, listens with Deepgram, thinks with an
  LLM, and speaks with ElevenLabs.

Env (Railway or local):
  LIVEKIT_URL       WebSocket URL to your server, e.g. wss://callplane-production.up.railway.app
  LIVEKIT_API_KEY   API key *id* (same id you put under keys: in LIVEKIT_CONFIG)
  LIVEKIT_API_SECRET Secret for that key
  DEEPGRAM_API_KEY  Deepgram STT
  ELEVEN_API_KEY    ElevenLabs TTS (some docs use ELEVENLABS_API_KEY — set ELEVEN_API_KEY per plugin)
  OPENAI_API_KEY    Required below for the LLM step (swap plugin if you prefer another model)

CLI:
  python agent.py download-files   # optional: fetch VAD weights etc.
  python agent.py dev             # local dev
  python agent.py start           # production-style worker
"""

from __future__ import annotations

import logging

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    TurnHandlingOptions,
    cli,
    metrics,
    room_io,
)
from livekit.plugins import deepgram, elevenlabs, openai, silero

logger = logging.getLogger("callplane-agents")
load_dotenv()


class CallplaneAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a short phone-test assistant for Callplane. "
                "Keep answers under two sentences. No markdown or emojis."
            ),
        )

    async def on_enter(self) -> None:
        self.session.generate_reply(
            instructions="Say briefly that the Callplane test agent is online."
        )


server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=elevenlabs.TTS(),
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(),
    )

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        metrics.log_metrics(ev.metrics)

    await session.start(
        agent=CallplaneAgent(),
        room=ctx.room,
        room_options=room_io.RoomOptions(),
    )


if __name__ == "__main__":
    cli.run_app(server)
