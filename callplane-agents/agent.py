"""
LiveKit Agents worker for Callplane → BiteBuddy voice brain.

Layman's terms:
- LiveKit moves phone audio in a "room".
- This worker joins that room, turns speech into text (Deepgram), sends text to
  BiteBuddy over a WebSocket, streams the reply back, and speaks it (ElevenLabs).

Env (Railway or local):
  LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
  DEEPGRAM_API_KEY, ELEVEN_API_KEY
  BITE_BUDDY_WS_URL   e.g. wss://api.bitebuddy.ai/ai/chat/ws/completions
  AGENT_NAME          default callplane-voice (must match SIP dispatch rule)

CLI:
  python agent.py download-files
  python agent.py dev
  python agent.py start
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from livekit import rtc
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
from livekit.plugins import deepgram, elevenlabs, silero

from bitebuddy_llm import BiteBuddyLLM
from phone_utils import normalize_e164_us

logger = logging.getLogger("callplane-agents")
load_dotenv()

AGENT_NAME = os.environ.get("AGENT_NAME", "callplane-voice")
# LiveKit worker health HTTP (GET /) — not Railway's $PORT; see health-wrapper.py + start.sh.
AGENT_HTTP_PORT = int(os.environ.get("AGENT_HTTP_PORT", "8081"))

SIP_ATTR_TRUNK = "sip.trunkPhoneNumber"
SIP_ATTR_CALLER = "sip.phoneNumber"
SIP_ATTR_CALL_ID = "sip.callID"


class CallplaneAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a phone assistant for a restaurant. "
                "Keep answers concise and natural for speech. No markdown or emojis."
            ),
        )

    # BiteBuddy sends the first spoken message; do not greet from the agent scaffold.


server = AgentServer(port=AGENT_HTTP_PORT)


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    try:
        sip_participant = await ctx.wait_for_participant(
            kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP
        )
        attrs = dict(sip_participant.attributes)
    except Exception:
        logger.warning("timed out waiting for SIP participant; falling back to room metadata")
        attrs = {}

    call_id = attrs.get(SIP_ATTR_CALL_ID) or ctx.room.name
    business_phone_raw = attrs.get(SIP_ATTR_TRUNK, "")
    caller_phone_raw = attrs.get(SIP_ATTR_CALLER, "")
    # BiteBuddy DB lookup is exact match; SIP often sends 1218... without +1.
    business_phone = normalize_e164_us(business_phone_raw)
    caller_phone = normalize_e164_us(caller_phone_raw)

    ctx.log_context_fields = {
        "room": ctx.room.name,
        "call_id": call_id,
        "agent": AGENT_NAME,
    }

    logger.info(
        "SIP call_id=%s business=%s (raw=%s) caller=%s (raw=%s)",
        call_id,
        business_phone,
        business_phone_raw,
        caller_phone,
        caller_phone_raw,
    )

    bitebuddy_llm = BiteBuddyLLM.from_env(
        call_id=call_id,
        business_phone=business_phone,
        customer_phone=caller_phone,
    )
    await bitebuddy_llm.connect()
    ctx.add_shutdown_callback(bitebuddy_llm.aclose)

    session = AgentSession(
        stt=deepgram.STT(),
        llm=bitebuddy_llm,
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
