"""`MessageDispatcher` (Phase 9.4; JT808 Technical Design §7). Routes a decoded `InboundMessage`
(Phase 9.3's `PacketParser` output) to the handler registered for its `message_id`
(`HandlerRegistry`), or to `UnknownMessageHandler` if none is registered. Per-connection
ordering is already guaranteed upstream — `connection/connection.py`'s read loop `await`s each
frame's `on_frame` callback (which reaches `dispatch()`) before reading the next chunk, and
each connection is its own independent `asyncio.Task` — so `dispatch()` itself needs no extra
sequencing machinery; it only needs to be a well-behaved single coroutine call.

**A handler raising an exception never crashes the connection or the dispatcher** — caught
broadly here (Backend LLD §6's "never crash the connection" principle, applied to the
handler-execution step exactly as Phase 9.3 applies it to malformed frames) and reported via
`on_handler_error`.

**"Automatic general response" (§7):** if the handler's `HandlerResult` carries a
`response_message_id`/`response_body`, the dispatcher encodes it (`protocol/encoder.py`) and
sends it back over the *same* connection (`send`, injected — resolved to
`ConnectionManager.send_to_connection`, a Phase 9.4 addition to Phase 9.1's connection layer)
using the platform's own outbound serial-number counter (`_OutboundSerialCounter` — a single
counter shared across every connection; JT/T 808-2013 §4.4.3's "从0开始循环累加" ("cyclically
accumulate from 0") is a per-*sender* rule with no documented requirement that different
terminals be tracked separately, so one shared, 16-bit-wrapping counter is the simplest
protocol-plausible choice, not a per-connection state/cleanup problem this phase invents).

**Metrics/hooks:** `on_dispatched`/`on_unknown_message`/`on_handler_error` are injected
callbacks, defaulting to structured logging — the same "framework only, no real metrics
export" stance `connection/manager.py`'s idle-timeout sweep and `session/device_session_
manager.py`'s session-lifecycle hooks already take. Together they cover Phase 3.4 §19's
documented observability intent ("messages/sec by type... parse-error rate") without a metrics
backend this phase has no approved library for.

**`close_connection` (Phase 9.5 addition):** resolves to `ConnectionManager.close_connection`
(already existed, Phase 9.2) — invoked *after* sending the response, when `HandlerResult.
close_connection_after` is set (JT808 Technical Design §4: a rejected registration or a failed
authentication is "reject + audit + close," response first, then close).
"""

from __future__ import annotations

from typing import Awaitable, Callable

from src.dispatcher.handler import HandlerContext, MessageHandler
from src.dispatcher.registry import HandlerRegistry
from src.logging_setup import get_logger, log_with_fields
from src.protocol.encoder import build_frame
from src.protocol.message import InboundMessage
from src.session.device_session_manager import DeviceSessionManager

logger = get_logger("jt808.dispatcher")

SendFrame = Callable[[str, bytes], Awaitable[None]]
CloseConnection = Callable[[str, str], Awaitable[None]]
OnDispatched = Callable[[InboundMessage], None]
OnUnknownMessage = Callable[[InboundMessage], None]
OnHandlerError = Callable[[InboundMessage, Exception], None]

_SERIAL_NO_WRAP = 0x10000  # WORD — 16 bits


class _OutboundSerialCounter:
    def __init__(self) -> None:
        self._next = 0

    def next(self) -> int:
        value = self._next
        self._next = (self._next + 1) % _SERIAL_NO_WRAP
        return value


def _default_on_dispatched(message: InboundMessage) -> None:
    log_with_fields(
        logger,
        10,
        "message_dispatched",
        message_id=f"0x{message.message_id:04x}",
        terminal_id=message.terminal_id,
    )


def _default_on_unknown_message(message: InboundMessage) -> None:
    log_with_fields(
        logger,
        30,
        "unknown_message_dispatched",
        message_id=f"0x{message.message_id:04x}",
        terminal_id=message.terminal_id,
    )


def _default_on_handler_error(message: InboundMessage, exc: Exception) -> None:
    log_with_fields(
        logger,
        40,
        "handler_error",
        message_id=f"0x{message.message_id:04x}",
        terminal_id=message.terminal_id,
        error=str(exc),
    )


class MessageDispatcher:
    def __init__(
        self,
        *,
        registry: HandlerRegistry,
        unknown_handler: MessageHandler,
        device_sessions: DeviceSessionManager,
        send: SendFrame,
        close_connection: CloseConnection,
        on_dispatched: OnDispatched | None = None,
        on_unknown_message: OnUnknownMessage | None = None,
        on_handler_error: OnHandlerError | None = None,
    ) -> None:
        self._registry = registry
        self._unknown_handler = unknown_handler
        self._device_sessions = device_sessions
        self._send = send
        self._close_connection = close_connection
        self._on_dispatched = on_dispatched or _default_on_dispatched
        self._on_unknown_message = on_unknown_message or _default_on_unknown_message
        self._on_handler_error = on_handler_error or _default_on_handler_error
        self._serial_counter = _OutboundSerialCounter()

    async def dispatch(self, connection_id: str, message: InboundMessage) -> None:
        handler = self._registry.resolve(message.message_id)
        is_known = handler is not None
        if handler is None:
            handler = self._unknown_handler

        context = HandlerContext(
            connection_id=connection_id, device_sessions=self._device_sessions
        )
        try:
            result = await handler.handle(message, context)
        except (
            Exception
        ) as exc:  # noqa: BLE001 - a handler bug must not crash the connection
            self._on_handler_error(message, exc)
            return

        if is_known:
            self._on_dispatched(message)
        else:
            self._on_unknown_message(message)

        if result.response_message_id is not None and result.response_body is not None:
            frame = build_frame(
                message_id=result.response_message_id,
                terminal_phone=message.terminal_id,
                serial_no=self._serial_counter.next(),
                body=result.response_body,
            )
            await self._send(connection_id, frame)

        if result.close_connection_after:
            await self._close_connection(
                connection_id, result.close_reason or "handler_requested_close"
            )
