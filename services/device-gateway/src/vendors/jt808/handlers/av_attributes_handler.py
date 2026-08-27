"""`AvAttributesHandler` (`0x1003`) — the terminal's reply to a platform-issued
`QUERY_AV_ATTRIBUTES` (`0x9003`) command (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.1.2, ADR-0030).
Parses the report (`commands/av_attributes.parse_av_attributes_report`), correlates it back to
the original `0x9003` via `commands/pending_commands.PendingCommandTracker.
resolve_by_terminal_and_message` (not the standard `resolve()` triple — see that method's own
docstring and `commands/av_attributes.py`'s module docstring for why `0x1003` has no serial
number to match on), and publishes `DeviceAvAttributesReported`. Mirrors
`resource_list_handler.ResourceListHandler`'s exact shape otherwise.

**Authenticated session required** (`jt808.md` #5), identical "drop, warn, don't close"
discipline as `ResourceListHandler`/`LocationHandler`.

**No pending correlation found is expected, not an error** — same reasoning as
`ResourceListHandler`: an `0x1003` arriving with no matching `0x9003` this process ever sent
(e.g. after a device-gateway restart mid-query, or a device that proactively uploads its
attributes unsolicited) still publishes, with `correlation_id=""`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.events.device_av_attributes_reported import DeviceAvAttributesReported
from src.events.publisher_port import EventPublisher
from src.vendors.jt808.commands.av_attributes import parse_av_attributes_report
from src.vendors.jt808.commands.pending_commands import PendingCommandTracker
from src.vendors.jt808.dispatcher import message_ids
from src.vendors.jt808.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.logging_setup import get_logger, log_with_fields
from src.vendors.jt808.protocol.message import InboundMessage

logger = get_logger("jt808.handlers.av_attributes")


class AvAttributesHandler(MessageHandler):
    def __init__(
        self, pending: PendingCommandTracker, event_publisher: EventPublisher
    ) -> None:
        self._pending = pending
        self._event_publisher = event_publisher

    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        session = await context.device_sessions.resolve(message.terminal_id)
        if session is None:
            log_with_fields(
                logger,
                30,
                "av_attributes_dropped_unauthenticated",
                connection_id=context.connection_id,
                terminal_id=message.terminal_id,
            )
            return HandlerResult.no_response()

        report = parse_av_attributes_report(message.body)

        pending = self._pending.resolve_by_terminal_and_message(
            terminal_id=message.terminal_id,
            message_id=message_ids.QUERY_AV_ATTRIBUTES,
        )
        correlation_id = pending.correlation_id if pending is not None else ""

        now = datetime.now(timezone.utc)
        await self._event_publisher.publish(
            DeviceAvAttributesReported(
                terminal_id=message.terminal_id,
                organization_id=session.organization_id,
                vehicle_id=session.vehicle_id,
                device_id=session.device_id,
                correlation_id=correlation_id,
                max_video_channels=report.max_video_channels,
                max_audio_channels=report.max_audio_channels,
                event_time=now,
                received_at=now,
            )
        )
        log_with_fields(
            logger,
            10,
            "av_attributes_reported",
            connection_id=context.connection_id,
            terminal_id=message.terminal_id,
            correlation_id=correlation_id,
            max_video_channels=report.max_video_channels,
        )
        return HandlerResult.no_response()
