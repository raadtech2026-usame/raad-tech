"""`UnknownMessageHandler` (Phase 9.4; JT808 Technical Design §7, verbatim: "Unknown message
ids are logged + counted and answered per protocol (general response with 'not supported'
where applicable) rather than dropped silently."). The dispatcher (`dispatcher.py`) routes
here whenever `HandlerRegistry.resolve` finds no registered handler for a `message_id` — this
is the one case in this phase where an automatic response is explicitly documented, unlike
known-but-not-yet-implemented message IDs (`placeholder_handler.py`), which send nothing per
the resolved Phase 9.4 scope.
"""

from __future__ import annotations

from src.dispatcher.general_response import (
    GENERAL_RESPONSE_MESSAGE_ID,
    RESULT_NOT_SUPPORTED,
    build_general_response_body,
)
from src.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.logging_setup import get_logger, log_with_fields
from src.protocol.message import InboundMessage

logger = get_logger("jt808.dispatcher.unknown_handler")


class UnknownMessageHandler(MessageHandler):
    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        log_with_fields(
            logger,
            30,
            "unknown_message_id",
            connection_id=context.connection_id,
            message_id=f"0x{message.message_id:04x}",
            terminal_id=message.terminal_id,
        )
        body = build_general_response_body(
            original_serial_no=message.serial_no,
            original_message_id=message.message_id,
            result=RESULT_NOT_SUPPORTED,
        )
        return HandlerResult(
            response_message_id=GENERAL_RESPONSE_MESSAGE_ID, response_body=body
        )
