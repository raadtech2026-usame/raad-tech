"""`LocationHandler` (`0x0200`, Phase 9.6; JT808 Technical Design §8/§10, JT/T 808-2013 §8.18).
The first of this phase's two handlers — parses the position body (`position_body.py`),
resolves the reporting terminal's device/vehicle/org identity from its already-bound
`DeviceSession` (Phase 9.2/9.5 — never re-derives it), and publishes a `DevicePositionReported`
event via the injected `EventPublisher` port (`events/publisher_port.py`).

**This handler never calls `TrackingApplicationService`, never imports `tracking`, and never
writes any table.** That would require importing `backend.raad.modules.tracking` into a
different deployable (`services/jt808/`) entirely — flagged as a direct conflict with this
task's own literal wording ("Position handlers must communicate only through
`TrackingApplicationService`") before any code was written, and resolved with the user in favor
of the approved architecture: `.claude/rules/architecture.md` #3, `.claude/rules/jt808.md` #1,
JT808 Technical Design (top of doc + §1), Backend LLD §10.3, and `docs/architecture/adr/
0001-business-entity-module-mapping.md` are unanimous that the device plane reaches the
business plane *only* via published domain events over a broker, never a synchronous in-process
call, never a direct DB write. See `events/device_position_reported.py`'s module docstring for
the same conflict record from the event-shape side.

**Geofence evaluation is explicitly not triggered here, for the same reason.** `tracking.
application.services.TrackingApplicationService.evaluate_geofence` is not even auto-invoked by
`record_vehicle_position` inside Tracking itself — JT808 Technical Design §21.2's own sequence
diagram places "persist `vehicle_positions`; geofence eval" as a single self-call step inside
"Business API (tracking consumer)", a not-yet-built consumer of this handler's published event,
not inside JT808. Building that consumer is out of this phase's scope.

**Authenticated session required.** `jt808.md` #5: "Unknown/unauthenticated devices are
rejected and audited, never silently dropped without a trace." A `0x0200` from a `terminal_id`
with no bound `DeviceSession` (or one missing `device_id`/`vehicle_id`/`organization_id` —
`DeviceSession`'s fields are optional pass-through data, Phase 9.2) cannot be mapped to a valid
`DevicePositionReported` (all three are required there) — it is logged at WARNING (audited) and
dropped, without closing the connection (nothing in any approved document calls for a forced
disconnect on this specific case, unlike registration/auth failure, JT808 Technical Design §4).

**No wire response is sent.** JT808 Technical Design §8's Handler table lists this handler's
`Emits:` column as `device.position_reported` (+ `device.alarm_raised` if flagged) only — no
platform general response (`0x8001`) is documented for `0x0200`. The primary spec's only
mention of a general-response reply for this message (§7.3.3, alarm handling: "平台可通过回复平
台通用应答消息进行报警处理" — "the platform *may* reply with a platform general response to
process an alarm") is optional ("可"/"may") and per-alarm-bit ("收到应答后清零" applies to some
alarm bits, not others, per Table 24) — building that fine-grained ack-timing logic is
notification/business-response territory this phase's own scope list excludes ("Do NOT
implement: ... Notification delivery"), so this handler follows the documented Handler table
literally and sends nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.events.device_position_reported import DevicePositionReported
from src.events.publisher_port import EventPublisher
from src.handlers.position_body import parse_position_report_body
from src.logging_setup import get_logger, log_with_fields
from src.protocol.message import InboundMessage

logger = get_logger("jt808.handlers.location")


class LocationHandler(MessageHandler):
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
                "position_report_dropped_unauthenticated",
                connection_id=context.connection_id,
                terminal_id=message.terminal_id,
            )
            return HandlerResult.no_response()

        report = parse_position_report_body(message.body)

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
            is_backfill=False,
            received_at=datetime.now(timezone.utc),
        )
        await self._event_publisher.publish(event)

        log_with_fields(
            logger,
            10,
            "position_report_published",
            connection_id=context.connection_id,
            terminal_id=message.terminal_id,
            is_backfill=False,
        )
        return HandlerResult.no_response()
