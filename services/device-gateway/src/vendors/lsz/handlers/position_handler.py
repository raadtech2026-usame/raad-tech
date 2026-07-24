"""`MdvrPositionHandler` (`V114`) — the vendor-protocol equivalent of `src.handlers.
location_handler.LocationHandler`, publishing the exact same, **unmodified** `src.events.
device_position_reported.DevicePositionReported` event via the exact same, **unmodified**
`src.events.publisher_port.EventPublisher` port — the whole point of ADR-0009's design: only the
protocol adapter differs, the event contract downstream consumers (this deployable's own
`/ws/tracking`-feeding broker publish, and the Business API's `tracking` module) rely on does not.

**GPS normalization happens here, not downstream** — `protocol.location_status.
parse_location_status` converts this vendor's own D°M′S″ integer encoding into the plain decimal-
degree floats `DevicePositionReported.latitude`/`longitude` already expect, so nothing downstream
needs to know a non-JT/T-808 vendor produced this event at all.

**Authenticated session required**, same rule and same reasoning as the parent package's
`LocationHandler`: a `V114` from a `device_serial_number` with no bound `DeviceSession` (or one
missing `device_id`/`vehicle_id`/`organization_id`) cannot be mapped to a valid event — logged at
WARNING (audited) and dropped, connection left open (nothing in the vendor documentation calls for
a forced disconnect on this specific case).

**`speed_kph`/`heading_deg`/`alarm_flags` default to `0` when this vendor's own field encoding is
uncertain** (`protocol.location_status`'s own documented "best-effort, not independently
validated" caveat for these specific fields) — `DevicePositionReported` declares them as plain
`int`, not `int | None` (unlike `tracking.application.commands.RecordVehiclePositionCommand`,
which *does* make them optional), so a concrete value is required here; `0` is a safe, inert
default for telemetry fields this handler cannot yet confirm, never a fabricated non-zero reading.

**No wire response is sent** — the vendor document names no acknowledgment for `V114` in either
of its two worked examples (`docs/vendor/HARDWARE_ANALYSIS.md` §9's Commands table), matching the
parent package's own `LocationHandler`'s identical "no ack for a position report" precedent.

**`trip_id` is always `None`** — same fallback and same reasoning as the parent package's
`LocationHandler`: no active-trip Redis read-model exists in this deployable.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.events.device_position_reported import DevicePositionReported
from src.events.publisher_port import EventPublisher
from src.logging_setup import get_logger, log_with_fields
from src.vendors.lsz.dispatcher.handler import (
    MdvrHandlerContext,
    MdvrHandlerResult,
    MdvrMessageHandler,
)
from src.vendors.lsz.protocol.location_status import parse_location_status
from src.vendors.lsz.protocol.message import MdvrInboundMessage
from src.vendors.lsz.protocol.time_format import parse_sent_at

logger = get_logger("mdvr.handlers.position")


class MdvrPositionHandler(MdvrMessageHandler):
    def __init__(self, event_publisher: EventPublisher) -> None:
        self._event_publisher = event_publisher

    async def handle(
        self, message: MdvrInboundMessage, context: MdvrHandlerContext
    ) -> MdvrHandlerResult:
        session = context.device_sessions.resolve(message.device_serial_number)
        if (
            session is None
            or session.device_id is None
            or session.vehicle_id is None
            or session.organization_id is None
        ):
            log_with_fields(
                logger,
                30,
                "position_report_dropped_unauthenticated",
                connection_id=context.connection_id,
                device_serial_number=message.device_serial_number,
            )
            return MdvrHandlerResult.no_response()

        location, _remainder = parse_location_status(message.fields)

        event = DevicePositionReported(
            organization_id=session.organization_id,
            vehicle_id=session.vehicle_id,
            device_id=session.device_id,
            terminal_id=message.device_serial_number,
            trip_id=None,
            latitude=location.latitude,
            longitude=location.longitude,
            speed_kph=round(location.ground_speed_kph) if location.ground_speed_kph else 0,
            heading_deg=location.heading_deg if location.heading_deg is not None else 0,
            alarm_flags=(
                location.component_status_alarm
                if location.component_status_alarm is not None
                else 0
            ),
            event_time=parse_sent_at(message.sent_at_raw),
            is_backfill=False,
            received_at=datetime.now(timezone.utc),
        )
        await self._event_publisher.publish(event)

        log_with_fields(
            logger,
            10,
            "position_report_published",
            connection_id=context.connection_id,
            device_serial_number=message.device_serial_number,
            fix_valid=location.fix_valid,
        )
        return MdvrHandlerResult.no_response()
