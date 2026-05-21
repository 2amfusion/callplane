"""
LiveKit Agents worker for Callplane → BiteBuddy voice brain.

Layman's terms:
- LiveKit moves phone audio in a "room".
- This worker joins that room, turns speech into text (Deepgram), sends text to
  BiteBuddy over a WebSocket, streams the reply back, and speaks it (ElevenLabs).

Env (Railway or local):
  LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
  DEEPGRAM_API_KEY, ELEVEN_API_KEY
  BITE_BUDDY_WS_URL       e.g. wss://api.bitebuddy.ai/ai/chat/ws/completions
  AGENT_NAME              default callplane-voice (must match SIP dispatch rule)
  CALLPLANE_API_URL       e.g. http://localhost:8000 (management API for per-number config)

CLI:
  python agent.py download-files
  python agent.py dev
  python agent.py start
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    cli,
    metrics,
    room_io,
)
from livekit.plugins import deepgram, elevenlabs, silero, openai as lk_openai, anthropic as lk_anthropic

from bitebuddy_llm import BiteBuddyLLM
from phone_utils import normalize_e164_us

logger = logging.getLogger("callplane-agents")
load_dotenv()

AGENT_NAME = os.environ.get("AGENT_NAME", "callplane-voice")
AGENT_HTTP_PORT = int(os.environ.get("AGENT_HTTP_PORT", "8081"))
CALLPLANE_API_URL = os.environ.get("CALLPLANE_API_URL", "").rstrip("/")

SIP_ATTR_TRUNK = "sip.trunkPhoneNumber"
SIP_ATTR_CALLER = "sip.phoneNumber"
SIP_ATTR_CALL_ID = "sip.callID"

DEFAULT_INSTRUCTIONS = (
    "You are a phone assistant. "
    "Keep answers concise and natural for speech. No markdown or emojis."
)


async def fetch_agent_config(phone_number: str) -> dict[str, Any] | None:
    """Fetch per-number agent config from the management API. Returns None on any failure."""
    if not CALLPLANE_API_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{CALLPLANE_API_URL}/api/config/by-number/{phone_number}")
            if resp.status_code == 200:
                return resp.json()
            logger.info("No config found for %s (status %s), using defaults", phone_number, resp.status_code)
    except Exception as e:
        logger.warning("Could not fetch agent config for %s: %s — using defaults", phone_number, e)
    return None


class CallplaneAgent(Agent):
    def __init__(self, instructions: str = DEFAULT_INSTRUCTIONS) -> None:
        super().__init__(instructions=instructions)


server = AgentServer(port=AGENT_HTTP_PORT)


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
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

    # Fetch per-number config from management API (falls back to defaults if unavailable)
    agent_config = await fetch_agent_config(business_phone)

    instructions = DEFAULT_INSTRUCTIONS
    tts_voice_id = None
    llm_provider = "bitebuddy"
    llm_model = None

    if agent_config:
        if agent_config.get("system_prompt"):
            instructions = agent_config["system_prompt"]
        if agent_config.get("tts_voice_id"):
            tts_voice_id = agent_config["tts_voice_id"]
        if agent_config.get("llm_provider"):
            llm_provider = agent_config["llm_provider"]
        if agent_config.get("llm_model"):
            llm_model = agent_config["llm_model"]
        logger.info(
            "Loaded agent config for %s: llm=%s, instructions=%s chars, voice=%s",
            business_phone, llm_provider, len(instructions), tts_voice_id or "default",
        )

    # Build LLM based on provider
    if llm_provider == "openai":
        llm = lk_openai.LLM(model=llm_model or "gpt-4o-mini")
    elif llm_provider == "anthropic":
        llm = lk_anthropic.LLM(model=llm_model or "claude-haiku-4-5-20251001")
    else:
        # Default: BiteBuddy
        bite_buddy_ws_url = agent_config.get("bite_buddy_ws_url") if agent_config else None
        llm = BiteBuddyLLM.from_env(
            call_id=call_id,
            business_phone=business_phone,
            customer_phone=caller_phone,
            ws_url=bite_buddy_ws_url,
        )
        await llm.connect()
        ctx.add_shutdown_callback(llm.aclose)

    tts = elevenlabs.TTS(voice_id=tts_voice_id) if tts_voice_id else elevenlabs.TTS()
    stt = deepgram.STT()

    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=ctx.proc.userdata["vad"],
        turn_detection="vad",  # skip adaptive interruption (LiveKit Cloud only)
    )

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        metrics.log_metrics(ev.metrics)

    await session.start(
        agent=CallplaneAgent(instructions=instructions),
        room=ctx.room,
        room_options=room_io.RoomOptions(),
    )

    # Greet the caller — only for non-BiteBuddy LLMs (BiteBuddy sends its own greeting)
    if llm_provider != "bitebuddy":
        await session.say("Hello! How can I help you today?", allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(server)
