"""`MdvrMessageDispatcher` — the vendor-protocol equivalent of `src.dispatcher.dispatcher.
MessageDispatcher`. Routes a parsed `MdvrInboundMessage` to the handler registered for its
`keyword`, encodes and sends any response the handler asks for, and closes the connection
afterward if requested — the exact same "handler owns protocol behavior, dispatcher owns
routing/response encoding/close timing" split the parent package's dispatcher already
establishes.

**No "unsupported command" response exists for this vendor protocol** — unlike JT/T 808's
`0x8001` general response, none of the vendor's documents describe any acknowledgment for a
keyword the center doesn't recognize. An unmatched keyword is logged and dropped, not answered —
a documented absence, not an oversight (`docs/vendor/HARDWARE_ANALYSIS.md` §9's own command
catalogue lists no such message).

A handler raising an exception never crashes the connection — caught here exactly as the parent
package's dispatcher does, reported via `on_handler_error`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable

from src.logging_setup import get_logger, log_with_fields
from src.vendors.lsz_mdvr.dispatcher.handler import MdvrHandlerContext, MdvrMessageHandler
from src.vendors.lsz_mdvr.dispatcher.registry import MdvrHandlerRegistry
from src.vendors.lsz_mdvr.protocol.encoder import build_frame, format_sent_at
from src.session.device_session_manager import DeviceSessionManager
from src.vendors.lsz_mdvr.protocol.message import MdvrInboundMessage

logger = get_logger("mdvr.dispatcher")

SendFrame = Callable[[str, bytes], Awaitable[None]]
CloseConnection = Callable[[str, str], Awaitable[None]]
OnDispatched = Callable[[MdvrInboundMessage], None]
OnUnknownMessage = Callable[[MdvrInboundMessage], None]
OnHandlerError = Callable[[MdvrInboundMessage, Exception], None]

_SERIAL_NO_WRAP = 0x10000  # matches the parent dispatcher's own WORD-wrap convention


class _OutboundSerialCounter:
    def __init__(self) -> None:
        self._next = 0

    def next(self) -> int:
        value = self._next
        self._next = (self._next + 1) % _SERIAL_NO_WRAP
        return value


def _default_on_dispatched(message: MdvrInboundMessage) -> None:
    log_with_fields(
        logger,
        10,
        "message_dispatched",
        keyword=message.keyword,
        device_serial_number=message.device_serial_number,
    )


def _default_on_unknown_message(message: MdvrInboundMessage) -> None:
    log_with_fields(
        logger,
        30,
        "unknown_message_dispatched",
        keyword=message.keyword,
        device_serial_number=message.device_serial_number,
    )


def _default_on_handler_error(message: MdvrInboundMessage, exc: Exception) -> None:
    log_with_fields(
        logger,
        40,
        "handler_error",
        keyword=message.keyword,
        device_serial_number=message.device_serial_number,
        error=str(exc),
    )


class MdvrMessageDispatcher:
    def __init__(
        self,
        *,
        registry: MdvrHandlerRegistry,
        device_sessions: DeviceSessionManager,
        send: SendFrame,
        close_connection: CloseConnection,
        on_dispatched: OnDispatched | None = None,
        on_unknown_message: OnUnknownMessage | None = None,
        on_handler_error: OnHandlerError | None = None,
    ) -> None:
        self._registry = registry
        self._device_sessions = device_sessions
        self._send = send
        self._close_connection = close_connection
        self._on_dispatched = on_dispatched or _default_on_dispatched
        self._on_unknown_message = on_unknown_message or _default_on_unknown_message
        self._on_handler_error = on_handler_error or _default_on_handler_error
        self._serial_counter = _OutboundSerialCounter()

    async def dispatch(self, connection_id: str, message: MdvrInboundMessage) -> None:
        handler: MdvrMessageHandler | None = self._registry.resolve(message.keyword)
        if handler is None:
            self._on_unknown_message(message)
            return

        context = MdvrHandlerContext(
            connection_id=connection_id, device_sessions=self._device_sessions
        )
        try:
            result = await handler.handle(message, context)
        except Exception as exc:  # noqa: BLE001 - a handler bug must not crash the connection
            self._on_handler_error(message, exc)
            return

        self._on_dispatched(message)

        if result.response_keyword is not None:
            frame = build_frame(
                keyword=result.response_keyword,
                seq=self._serial_counter.next(),
                device_serial_number=message.device_serial_number,
                workstation_serial_number=message.workstation_serial_number,
                sent_at_raw=format_sent_at(datetime.now(timezone.utc)),
                fields=result.response_fields or [],
            )
            await self._send(connection_id, frame)

        if result.close_connection_after:
            await self._close_connection(
                connection_id, result.close_reason or "handler_requested_close"
            )
