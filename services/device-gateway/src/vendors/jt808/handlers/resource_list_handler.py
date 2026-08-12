"""`ResourceListHandler` (`0x1205`) — the terminal's reply to a platform-issued
`QUERY_RESOURCE_LIST` (`0x9205`) command (`mdvrdocs/MDVR-808-1078-spec.pdf` §6.3.2, ADR-0024 §7
point 2's "let the operator browse what recordings actually exist on the device before
requesting playback"). Parses the resource list (`commands/video_signaling.
parse_resource_list_report`), correlates it back to the original `0x9205` via
`commands/pending_commands.PendingCommandTracker` (keyed by the report's own echoed
`original_serial_no` — `0x1205` is a dedicated response message, not a `0x0001` general ack, so
this handler resolves the pending entry itself rather than going through
`command_ack_handler.py`), and publishes `DeviceResourceListReported`.

**Authenticated session required** (`jt808.md` #5), mirroring `LocationHandler`'s identical
"drop, warn, don't close" discipline for an unauthenticated sender — but unlike `LocationHandler`,
`device_id`/`vehicle_id`/`organization_id` are *not* required to be non-`None` to publish: a
resource catalog is still meaningful even with incomplete enrichment (the same "optional,
still meaningful" reasoning `DeviceOnline`/`DeviceOffline` already apply, not
`DevicePositionReported`'s stricter all-three-required rule), and dropping real recording-catalog
data an operator explicitly asked for would be a worse outcome than publishing it with a
enrichment gap.

**No pending correlation found is expected, not an error** — mirrors `command_ack_handler.py`'s
identical reasoning; `correlation_id` is published as an empty string in that case (an
`0x1205` arriving with no matching `0x9205` this process ever sent, e.g. after a device-gateway
restart mid-query) rather than omitting the field, since every other event in this deployable's
vocabulary always carries a real (non-optional) `correlation_id` value once `DeviceCommandResult`
established that convention.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.events.device_resource_list_reported import DeviceResourceListReported
from src.events.publisher_port import EventPublisher
from src.vendors.jt808.commands.pending_commands import PendingCommandTracker
from src.vendors.jt808.commands.video_signaling import parse_resource_list_report
from src.vendors.jt808.dispatcher import message_ids
from src.vendors.jt808.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.logging_setup import get_logger, log_with_fields
from src.vendors.jt808.protocol.message import InboundMessage

logger = get_logger("jt808.handlers.resource_list")


class ResourceListHandler(MessageHandler):
    def __init__(
        self, pending: PendingCommandTracker, event_publisher: EventPublisher
    ) -> None:
        self._pending = pending
        self._event_publisher = event_publisher

    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        session = context.device_sessions.resolve(message.terminal_id)
        if session is None:
            log_with_fields(
                logger,
                30,
                "resource_list_dropped_unauthenticated",
                connection_id=context.connection_id,
                terminal_id=message.terminal_id,
            )
            return HandlerResult.no_response()

        report = parse_resource_list_report(message.body)

        pending = self._pending.resolve(
            terminal_id=message.terminal_id,
            message_id=message_ids.QUERY_RESOURCE_LIST,
            serial_no=report.original_serial_no,
        )
        correlation_id = pending.correlation_id if pending is not None else ""

        now = datetime.now(timezone.utc)
        await self._event_publisher.publish(
            DeviceResourceListReported(
                terminal_id=message.terminal_id,
                organization_id=session.organization_id,
                vehicle_id=session.vehicle_id,
                device_id=session.device_id,
                correlation_id=correlation_id,
                total_resource_count=report.total_resource_count,
                items=tuple(
                    {
                        "logical_channel": item.logical_channel,
                        "start_time": item.start_time.isoformat(),
                        "end_time": item.end_time.isoformat(),
                        "alarm_flag": item.alarm_flag,
                        "resource_type": item.resource_type,
                        "stream_type": item.stream_type,
                        "storage_type": item.storage_type,
                        "file_size_bytes": item.file_size_bytes,
                    }
                    for item in report.items
                ),
                event_time=now,
                received_at=now,
            )
        )
        log_with_fields(
            logger,
            10,
            "resource_list_reported",
            connection_id=context.connection_id,
            terminal_id=message.terminal_id,
            correlation_id=correlation_id,
            total_resource_count=report.total_resource_count,
        )
        return HandlerResult.no_response()
