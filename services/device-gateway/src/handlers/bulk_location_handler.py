"""`BulkLocationHandler` (`0x0704`, Phase 9.6; JT808 Technical Design §8/§10, JT/T 808-2013
§8.49). Parses the batch body (`bulk_position_body.py`) and publishes one `DevicePositionReported`
event per item, `is_backfill=True` for all of them — see `bulk_position_body.py`'s module
docstring for why the whole message is treated uniformly rather than varying per-item on the
primary spec's `position_data_type` byte.

**Shares every architectural decision `location_handler.py` documents**: no `TrackingApplicationService`
call, no geofence-evaluation trigger, authenticated-session-required-or-drop-with-audit-log, no
wire response. Not repeated here in full — see that module's docstring for the resolved
direct-call-vs-event-driven conflict record.

**Event ordering is preserved by publishing sequentially, in wire order.** JT/T 808-2013 does
not document that a device pre-sorts a batch's items by `event_time` before upload; `asyncio.
gather`-style concurrent publishing would let the publisher (a future real broker client)
observe items out of the order the device actually sent them in. Each item is `await`ed in turn
instead — the single-coroutine-per-connection ordering guarantee `dispatcher.py`'s own module
docstring already relies on (per-connection frames are processed one at a time) is extended
here to *items within one frame* as well, by the same "no extra sequencing machinery needed,
just don't introduce concurrency" reasoning.

**Duplicate timestamps are passed through, not deduplicated.** No approved document (JT808
Technical Design, Backend LLD, Database Design, `.claude/rules/jt808.md`) defines any
duplicate-timestamp handling for positions — Tracking's own `VehiclePosition`/`VehiclePositionRepository`
enforce no uniqueness constraint on `(vehicle_id, event_time)` either (confirmed by reading
`tracking/domain/entities.py`/`infra/repositories.py` before this phase's design). Per the
task's own "(if documented)" qualifier, this handler invents no dedup logic — two items sharing
an `event_time` (a real possibility: some terminals resend an un-acked buffered fix) both
publish as separate events, exactly as received.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.events.device_position_reported import DevicePositionReported
from src.events.publisher_port import EventPublisher
from src.handlers.bulk_position_body import parse_bulk_position_report
from src.logging_setup import get_logger, log_with_fields
from src.protocol.message import InboundMessage

logger = get_logger("jt808.handlers.bulk_location")


class BulkLocationHandler(MessageHandler):
    def __init__(self, event_publisher: EventPublisher) -> None:
        self._event_publisher = event_publisher

    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        session = context.device_sessions.resolve(message.terminal_id)
        if (
            session is None
            or session.device_id is None
            or session.vehicle_id is None
            or session.organization_id is None
        ):
            log_with_fields(
                logger,
                30,
                "bulk_position_report_dropped_unauthenticated",
                connection_id=context.connection_id,
                terminal_id=message.terminal_id,
            )
            return HandlerResult.no_response()

        batch = parse_bulk_position_report(message.body)

        for report in batch.items:
            event = DevicePositionReported(
                organization_id=session.organization_id,
                vehicle_id=session.vehicle_id,
                device_id=session.device_id,
                terminal_id=message.terminal_id,
                trip_id=None,  # JT808 Technical Design §10: no active-trip read-model built yet
                latitude=report.latitude,
                longitude=report.longitude,
                speed_kph=report.speed_kph,
                heading_deg=report.heading_deg,
                alarm_flags=report.alarm_flags,
                event_time=report.event_time,
                is_backfill=True,
                received_at=datetime.now(timezone.utc),
            )
            await self._event_publisher.publish(
                event
            )  # sequential: preserves wire order

        log_with_fields(
            logger,
            10,
            "bulk_position_report_published",
            connection_id=context.connection_id,
            terminal_id=message.terminal_id,
            item_count=len(batch.items),
            position_data_type=batch.position_data_type,
        )
        return HandlerResult.no_response()
