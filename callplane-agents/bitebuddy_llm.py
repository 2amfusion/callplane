"""
BiteBuddy WebSocket LLM for LiveKit Agents.

Ports the Volt WebSocketLLMProvider protocol to livekit.agents.llm.LLM so the
voice worker can use bitebuddy-backend at /ai/chat/ws/completions/{call_id}.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from livekit.agents import llm
from livekit.agents._exceptions import APIConnectionError, APIError
from livekit.agents.llm import FunctionToolCall
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)

logger = logging.getLogger("bitebuddy-llm")

_CONNECTION_LOST = object()
_MAX_CANCELLED_TRACKING = 100


class BiteBuddyLLM(llm.LLM):
    """Persistent WebSocket client to bitebuddy-backend completions."""

    def __init__(
        self,
        *,
        ws_url: str,
        call_id: str,
        business_phone: str = "",
        customer_phone: str = "",
        reconnect_attempts: int = 3,
        reconnect_delay: float = 0.5,
        open_timeout: float = 5.0,
        max_total_connect_time: float = 12.0,
        ping_interval: float = 30.0,
        session_ready_timeout: float = 30.0,
    ) -> None:
        super().__init__()
        self._ws_url = ws_url.rstrip("/")
        self._call_id = call_id
        self._business_phone = business_phone
        self._customer_phone = customer_phone
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_delay = reconnect_delay
        self._open_timeout = open_timeout
        self._max_total_connect_time = max_total_connect_time
        self._ping_interval = ping_interval
        self._session_ready_timeout = session_ready_timeout

        self._websocket: Any = None
        self._connected = False
        self._session_ready = asyncio.Event()
        self._init_error: str | None = None
        self._connect_lock = asyncio.Lock()
        self._ws_write_lock = asyncio.Lock()
        self._receive_task: asyncio.Task[None] | None = None
        self._ping_task: asyncio.Task[None] | None = None
        self._close_event = asyncio.Event()
        self._request_counter = 0

        self._response_queues: dict[str, asyncio.Queue[Any]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._cancelled_requests: set[str] = set()
        self._current_request_id: str | None = None

    @property
    def model(self) -> str:
        return "bitebuddy"

    @property
    def provider(self) -> str:
        return "bitebuddy"

    @classmethod
    def from_env(
        cls,
        *,
        call_id: str,
        business_phone: str = "",
        customer_phone: str = "",
    ) -> BiteBuddyLLM:
        ws_url = os.environ.get("BITE_BUDDY_WS_URL", "").strip()
        if not ws_url:
            raise ValueError("BITE_BUDDY_WS_URL is required")
        return cls(
            ws_url=ws_url,
            call_id=call_id,
            business_phone=business_phone,
            customer_phone=customer_phone,
        )

    @property
    def endpoint(self) -> str:
        return f"{self._ws_url}/{self._call_id}"

    async def connect(self) -> None:
        """Connect, send init, and wait for session_ready (or init_error)."""
        async with self._connect_lock:
            if self._connected and self._session_ready.is_set():
                return
            if self._connected:
                await self.aclose()

            self._session_ready.clear()
            self._init_error = None

            start = time.monotonic()
            last_error: Exception | None = None

            for attempt in range(self._reconnect_attempts):
                elapsed = time.monotonic() - start
                if elapsed >= self._max_total_connect_time:
                    break
                timeout = min(self._open_timeout, self._max_total_connect_time - elapsed)
                if timeout <= 0.5:
                    break

                try:
                    self._websocket = await websockets.connect(
                        self.endpoint,
                        open_timeout=timeout,
                        ping_interval=20,
                        ping_timeout=10,
                        close_timeout=5,
                    )
                    self._connected = True
                    self._close_event.clear()
                    self._receive_task = asyncio.create_task(self._receive_loop())
                    self._ping_task = asyncio.create_task(self._ping_loop())

                    if not await self._send_init():
                        raise APIConnectionError("failed to send BiteBuddy init message")

                    try:
                        await asyncio.wait_for(
                            self._session_ready.wait(),
                            timeout=self._session_ready_timeout,
                        )
                    except asyncio.TimeoutError as e:
                        raise APIConnectionError(
                            "timed out waiting for BiteBuddy session_ready"
                        ) from e

                    if self._init_error:
                        raise APIConnectionError(
                            f"BiteBuddy init failed: {self._init_error}"
                        )

                    logger.info(
                        "connected to BiteBuddy WS %s (attempt %d)",
                        self.endpoint,
                        attempt + 1,
                    )
                    return

                except APIConnectionError:
                    raise
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "BiteBuddy connect attempt %d/%d failed: %s",
                        attempt + 1,
                        self._reconnect_attempts,
                        e,
                    )
                    await self._cleanup_connection()

                if attempt < self._reconnect_attempts - 1:
                    await asyncio.sleep(min(self._reconnect_delay * (2**attempt), 2.0))

            msg = f"failed to connect to BiteBuddy after {self._reconnect_attempts} attempts"
            if last_error:
                msg = f"{msg}: {last_error}"
            raise APIConnectionError(msg)

    async def _ensure_connected(self) -> None:
        if self._connected and self._session_ready.is_set():
            return
        await self.connect()

    async def _ws_send(self, data: str) -> bool:
        async with self._ws_write_lock:
            if not self._connected or not self._websocket:
                return False
            try:
                await self._websocket.send(data)
                return True
            except ConnectionClosed:
                self._connected = False
                return False
            except Exception as e:
                logger.warning("BiteBuddy send failed: %s", e)
                return False

    async def _send_init(self) -> bool:
        init_message = {
            "type": "init",
            "call_id": self._call_id,
            "phoneNumber": (
                {"number": self._business_phone} if self._business_phone else {}
            ),
            "call": {
                "customer": (
                    {"number": self._customer_phone} if self._customer_phone else {}
                ),
                "phoneCallProviderId": self._call_id,
            },
        }
        return await self._ws_send(json.dumps(init_message))

    async def _receive_loop(self) -> None:
        try:
            while self._connected and self._websocket:
                try:
                    raw = await self._websocket.recv()
                    data = json.loads(raw)
                except ConnectionClosed:
                    logger.warning("BiteBuddy WebSocket closed")
                    self._connected = False
                    break
                except json.JSONDecodeError as e:
                    logger.error("BiteBuddy invalid JSON: %s", e)
                    continue

                msg_type = data.get("type")
                request_id = data.get("request_id")

                if msg_type == "pong":
                    continue
                if msg_type == "session_ready":
                    logger.info("BiteBuddy session_ready call_id=%s", data.get("call_id"))
                    self._session_ready.set()
                    continue
                if msg_type == "init_error":
                    self._init_error = data.get("error") or "init_error"
                    logger.error("BiteBuddy init_error: %s", self._init_error)
                    self._session_ready.set()
                    continue
                if msg_type == "cancelled":
                    logger.info("BiteBuddy cancelled request_id=%s", request_id)
                    continue

                if request_id and request_id in self._response_queues:
                    await self._response_queues[request_id].put(data)
                elif request_id and request_id in self._cancelled_requests:
                    continue
                elif request_id:
                    logger.debug(
                        "BiteBuddy orphan chunk request_id=%s type=%s",
                        request_id,
                        msg_type,
                    )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("BiteBuddy receive loop error: %s", e)
        finally:
            self._connected = False
            for queue in self._response_queues.values():
                try:
                    queue.put_nowait(_CONNECTION_LOST)
                except asyncio.QueueFull:
                    pass

    async def _ping_loop(self) -> None:
        try:
            while self._connected and self._websocket:
                try:
                    await asyncio.wait_for(
                        self._close_event.wait(), timeout=self._ping_interval
                    )
                    break
                except asyncio.TimeoutError:
                    pass
                if self._connected and self._websocket:
                    if not await self._ws_send(
                        json.dumps({"type": "ping", "timestamp": int(time.time() * 1000)})
                    ):
                        break
        except asyncio.CancelledError:
            pass

    def _next_request_id(self) -> str:
        self._request_counter += 1
        return f"req_{self._call_id}_{self._request_counter}_{int(time.time() * 1000)}"

    async def _cancel_current_request(self) -> None:
        request_id = self._current_request_id
        if not request_id:
            return
        cancel_event = self._cancel_events.get(request_id)
        if cancel_event:
            cancel_event.set()
        if await self._ws_send(
            json.dumps({"type": "cancel", "request_id": request_id})
        ):
            logger.info("sent BiteBuddy cancel for %s", request_id)

    async def _cleanup_connection(self) -> None:
        self._connected = False
        self._close_event.set()

        for task in (self._ping_task, self._receive_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._ping_task = None
        self._receive_task = None

        async with self._ws_write_lock:
            if self._websocket:
                try:
                    await self._websocket.close()
                except Exception:
                    pass
                self._websocket = None

    async def aclose(self) -> None:
        await self._cancel_current_request()
        await self._cleanup_connection()
        self._response_queues.clear()
        self._cancel_events.clear()
        self._cancelled_requests.clear()
        self._current_request_id = None

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[Any] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> BiteBuddyLLMStream:
        if tools:
            logger.debug("BiteBuddy LLM ignoring %d tools (handled server-side)", len(tools))
        return BiteBuddyLLMStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


class BiteBuddyLLMStream(llm.LLMStream):
    def __init__(
        self,
        llm_instance: BiteBuddyLLM,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(
            llm_instance,
            chat_ctx=chat_ctx,
            tools=tools,
            conn_options=conn_options,
        )
        self._bb: BiteBuddyLLM = llm_instance

    async def _run(self) -> None:
        await self._bb._cancel_current_request()
        await self._bb._ensure_connected()

        messages, _ = self._chat_ctx.to_provider_format(format="openai")
        request_id = self._bb._next_request_id()
        self._bb._current_request_id = request_id

        response_queue: asyncio.Queue[Any] = asyncio.Queue()
        cancel_event = asyncio.Event()
        self._bb._response_queues[request_id] = response_queue
        self._bb._cancel_events[request_id] = cancel_event

        payload = {
            "type": "transcript",
            "request_id": request_id,
            "messages": messages,
            "phoneNumber": (
                {"number": self._bb._business_phone} if self._bb._business_phone else {}
            ),
            "call": {
                "phoneCallProviderId": self._bb._call_id,
                "customer": (
                    {"number": self._bb._customer_phone}
                    if self._bb._customer_phone
                    else {}
                ),
            },
        }

        try:
            async with self._bb._ws_write_lock:
                if not self._bb._connected or not self._bb._websocket:
                    raise ConnectionClosed(None, None)
                await self._bb._websocket.send(json.dumps(payload))

            chunk_id = request_id or str(uuid.uuid4())
            total_timeout = max(self._conn_options.timeout, 15.0)
            op_start = time.monotonic()

            while True:
                if cancel_event.is_set():
                    break

                elapsed = time.monotonic() - op_start
                remaining = total_timeout - elapsed
                if remaining <= 0:
                    raise APIConnectionError(
                        f"BiteBuddy request {request_id} timed out"
                    )

                try:
                    data = await asyncio.wait_for(
                        response_queue.get(), timeout=min(10.0, remaining)
                    )
                except asyncio.TimeoutError:
                    raise APIConnectionError(
                        f"BiteBuddy request {request_id} timed out waiting for chunk"
                    )

                if data is _CONNECTION_LOST:
                    raise APIConnectionError("BiteBuddy connection lost during stream")

                if data.get("error"):
                    raise APIError(
                        str(data["error"]),
                        body=data,
                        retryable=False,
                    )

                choices = data.get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason")

                tool_calls_delta = delta.get("tool_calls")
                if tool_calls_delta:
                    tc = tool_calls_delta[0]
                    fn = tc.get("function", {})
                    fn_name = fn.get("name") or ""
                    if not fn_name:
                        continue
                    self._event_ch.send_nowait(
                        llm.ChatChunk(
                            id=chunk_id,
                            delta=llm.ChoiceDelta(
                                tool_calls=[
                                    FunctionToolCall(
                                        name=fn_name,
                                        arguments=fn.get("arguments") or "",
                                        call_id=tc.get("id") or "",
                                    )
                                ]
                            ),
                        )
                    )

                content = delta.get("content")
                if content:
                    self._event_ch.send_nowait(
                        llm.ChatChunk(
                            id=chunk_id,
                            delta=llm.ChoiceDelta(content=content),
                        )
                    )

                if finish_reason in ("stop", "error", "tool_calls"):
                    break

        except ConnectionClosed as e:
            self._bb._connected = False
            raise APIConnectionError("BiteBuddy WebSocket closed during request") from e
        finally:
            self._bb._response_queues.pop(request_id, None)
            self._bb._cancel_events.pop(request_id, None)
            self._bb._cancelled_requests.add(request_id)
            if len(self._bb._cancelled_requests) > _MAX_CANCELLED_TRACKING:
                trim = len(self._bb._cancelled_requests) - _MAX_CANCELLED_TRACKING // 2
                for _ in range(trim):
                    self._bb._cancelled_requests.pop()
            if self._bb._current_request_id == request_id:
                self._bb._current_request_id = None

    async def aclose(self) -> None:
        await self._bb._cancel_current_request()
        await super().aclose()
