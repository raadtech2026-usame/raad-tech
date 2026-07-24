"""`PlaceholderMessageHandler` (Phase 9.4). One reusable, named no-op handler class — not eight
near-identical subclasses — registered once per known `message_id` (`server.py`'s composition
root) with a label matching JT808 Technical Design §8's handler names (Register, Auth,
Heartbeat, Location, BulkLocation, Alarm, CommandAck, Logout). Logs receipt only; the real
business behavior for each (§8's Action/Emits columns — resolve device, verify token, touch
session, normalize position, classify alarm, etc.) belongs to a later phase.

**Sends no response** — confirmed with the user before implementing (Phase 9.4): extending the
documented "unknown message -> not supported ack" behavior to *known*-but-unimplemented
message IDs was considered and deliberately not done, since no approved document addresses
that case and a future real handler should decide its own response without an already-sent
placeholder ack to account for.
"""

from __future__ import annotations

from src.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.logging_setup import get_logger, log_with_fields
from src.protocol.message import InboundMessage

logger = get_logger("jt808.dispatcher.placeholder_handler")


class PlaceholderMessageHandler(MessageHandler):
    def __init__(self, name: str) -> None:
        self._name = name

    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        log_with_fields(
            logger,
            10,
            "placeholder_handler_invoked",
            handler=self._name,
            connection_id=context.connection_id,
            message_id=f"0x{message.message_id:04x}",
            terminal_id=message.terminal_id,
            body_length=len(message.body),
        )
        return HandlerResult.no_response()
