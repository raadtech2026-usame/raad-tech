"""`CommandAckHandler` (`0x0001`) — replaces the `"CommandAck"` placeholder
(`dispatcher/placeholder_handler.py`) with a real handler now that this deployable actually sends
platform-initiated commands (`commands/command_sender.py`, the JT/T 1078 video-signaling
forwarding phase). Parses the terminal's general-response body
(`handlers/terminal_general_response_body.py`), resolves it against
`commands/pending_commands.PendingCommandTracker` by the exact `(terminal_id, original_message_id,
original_serial_no)` triple the ack itself echoes, and publishes a `DeviceCommandResult` — the
"Result/telemetry direction" half of ADR-0024 §8.

**A `0x0001` with no matching pending command is expected, not an error** — this deployable does
not (and, per `jt808.md` #6's own scope, need not) track every possible platform-initiated
command type a terminal might be independently configured to ack (e.g. a `0x8103` set-parameters
command issued by some other tool entirely outside this codebase); an unmatched ack is logged at
debug level and produces no response, no event, no `close_connection_after` — the connection is
untouched either way, matching every other handler's "never crash the connection" discipline.

**Sends no wire response of its own** — `0x0001` is itself an acknowledgement; acknowledging an
acknowledgement is not part of the JT/T 808 message flow (contrast `HeartbeatHandler`/
`LocationHandler`, which *do* reply, since `0x0002`/`0x0200` are the terminal-initiated messages
that expect one).
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.events.device_command_result import DeviceCommandResult
from src.events.publisher_port import EventPublisher
from src.vendors.jt808.commands.pending_commands import PendingCommandTracker
from src.vendors.jt808.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.vendors.jt808.handlers.terminal_general_response_body import (
    parse_terminal_general_response,
)
from src.logging_setup import get_logger, log_with_fields
from src.vendors.jt808.protocol.message import InboundMessage

logger = get_logger("jt808.handlers.command_ack")


class CommandAckHandler(MessageHandler):
    def __init__(
        self, pending: PendingCommandTracker, event_publisher: EventPublisher
    ) -> None:
        self._pending = pending
        self._event_publisher = event_publisher

    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        ack = parse_terminal_general_response(message.body)

        pending = self._pending.resolve(
            terminal_id=message.terminal_id,
            message_id=ack.original_message_id,
            serial_no=ack.original_serial_no,
        )
        if pending is None:
            log_with_fields(
                logger,
                10,
                "command_ack_unmatched",
                connection_id=context.connection_id,
                terminal_id=message.terminal_id,
                original_message_id=f"0x{ack.original_message_id:04x}",
                original_serial_no=ack.original_serial_no,
            )
            return HandlerResult.no_response()

        now = datetime.now(timezone.utc)
        log_with_fields(
            logger,
            20 if ack.is_success else 30,
            "command_acknowledged",
            connection_id=context.connection_id,
            terminal_id=message.terminal_id,
            original_message_id=f"0x{ack.original_message_id:04x}",
            correlation_id=pending.correlation_id,
            result=ack.result,
        )
        await self._event_publisher.publish(
            DeviceCommandResult(
                terminal_id=pending.terminal_id,
                organization_id=pending.organization_id,
                vehicle_id=pending.vehicle_id,
                device_id=pending.device_id,
                correlation_id=pending.correlation_id,
                message_id=pending.message_id,
                success=ack.is_success,
                reason="acknowledged" if ack.is_success else "terminal_rejected",
                event_time=now,
                received_at=now,
            )
        )
        return HandlerResult.no_response()
