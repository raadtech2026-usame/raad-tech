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

**Every report is answered with a platform general response `0x8001` (fix, 2026-09-17).** This
handler originally sent nothing, following JT808 Technical Design §8's Handler table literally.
The confirmed supplier specification (`mdvrdocs/MDVR-808-1078-spec.pdf`, ADR-0025) is explicit
instead: §7.8.1 — "除消息定义明确标注无需应答外，发送方应等待通用应答或特定应答" (unless a message
is explicitly marked as needing no reply, the sender waits for a general or specific response);
§5.2.1 does not mark `0x0200` as no-reply (compare §5.1.3, where `0x0003` is); and §3.5.3 —
after the maximum retransmissions without a valid reply the terminal treats the link as broken.
An unacknowledged terminal therefore retransmits every report and eventually reconnects, which
matched the connection churn seen in production over 4G. The reply echoes this report's own
serial number and message ID (Table 5.21). Result codes:

- `0` success — sent only **after** `publish()` returns. If the snapshot write or the publish
  raises, no acknowledgement is sent, so the terminal retransmits instead of discarding a point
  RAAD never recorded.
- `1` failure — no authenticated session (§7.1.2: the connection must not be treated as online).
  The connection stays open, unchanged.
- `2` message error — the body could not be parsed (`ProtocolError`). Answering stops the
  terminal from retransmitting a report that can never succeed; the fact is still logged.

The alarm-specific acknowledgement (result `4`, §7.3) stays unbuilt: alarm handling is a separate
business flow this handler does not implement.

**Calls `touch()` on every accepted position, not just on `0x0002` heartbeats** (JT808
device-plane integration gap — mirrors `vendors.lsz.handlers.position_handler.
MdvrPositionHandler`'s identical, already-established bug-fix precedent exactly: a terminal
sending only `0x0200` position reports and no heartbeats would otherwise never be promoted
`AUTHENTICATED -> ONLINE`, and would eventually be swept `session_expired` by the idle-timeout
sweep while actively transmitting GPS). `touch()` is safe to call unconditionally here: it is a
no-op on an unknown `terminal_id`, and this handler already requires a resolved session before
reaching this point, so the call always targets a real one.

**`latest_position_writer` (root-cause fix — RAAD Live Tracking wrong-location investigation).**
Previously this constructor took only `event_publisher`, so this adapter — confirmed as the
live, primary GPS adapter for the procured hardware (ADR-0025 §4) — never wrote the
`vehicle:{id}:last` Redis snapshot `RedisLatestPositionPort.get_latest`/
`GET /tracking/vehicles/{id}/latest` read: `gateway.DeviceGateway._build_latest_position_writer`
wired it only into the dormant LSZ adapter, per an assumption from before ADR-0025 reversed
which vendor protocol is actually live. Mirrors `vendors.lsz.handlers.position_handler.
MdvrPositionHandler`'s existing `write()`-before-`publish()` shape exactly, and — per that
writer's own gating — only ever updates the snapshot for a position with `is_gps_valid=True`, so
a fix-invalid report can never overwrite a genuinely live last-known-good position.

**`gps_valid` (root-cause fix): the wire's own "positioned" bit, further narrowed by
`gps_validation.is_plausible_coordinate`.** Neither check alone is sufficient: a device can
report "positioned" against a stale/frozen/garbage coordinate, and a numerically in-range
coordinate carries no guarantee the device actually had a fix when it produced it. Both must
hold for `DevicePositionReported.is_gps_valid=True` — see that event's own module docstring for
the full downstream handling (persisted for audit either way, never silently dropped; never
treated as "live" when `False`).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from src.vendors.jt808.dispatcher.general_response import (
    GENERAL_RESPONSE_MESSAGE_ID,
    RESULT_FAILURE,
    RESULT_MESSAGE_ERROR,
    RESULT_SUCCESS,
    build_general_response_body,
)
from src.vendors.jt808.dispatcher.handler import HandlerContext, HandlerResult, MessageHandler
from src.events.device_position_reported import DevicePositionReported
from src.events.device_video_signal_status_reported import DeviceVideoSignalStatusReported
from src.events.publisher_port import EventPublisher
from src.gps_validation import is_plausible_coordinate
from src.latest_position.writer_port import LatestPositionWriter, LoggingLatestPositionWriter
from src.vendors.jt808.handlers.position_additional_info import (
    VideoSignalStatus,
    parse_additional_items,
    video_signal_status,
)
from src.vendors.jt808.handlers.position_body import parse_position_report_body
from src.logging_setup import get_logger, log_with_fields
from src.vendors.jt808.protocol.exceptions import ProtocolError
from src.vendors.jt808.protocol.message import InboundMessage

logger = get_logger("jt808.handlers.location")


def _general_response(message: InboundMessage, result: int) -> HandlerResult:
    return HandlerResult(
        response_message_id=GENERAL_RESPONSE_MESSAGE_ID,
        response_body=build_general_response_body(
            original_serial_no=message.serial_no,
            original_message_id=message.message_id,
            result=result,
        ),
    )


#: ADR-0046 §1: republish an unchanged video-signal mask at most this often, keeping the backend's
#: copy (`reported_at`) fresh while the terminal is online.
VIDEO_SIGNAL_REFRESH_SECONDS = 300.0


class VideoSignalStatusTracker:
    """Decides when a terminal's `0x15`/`0x16` report is news: the mask changed, it is the first
    report on this connection, or the last publish is older than the refresh interval. A position
    report arrives every ~20 s; publishing each one would be noise."""

    def __init__(
        self,
        *,
        refresh_seconds: float = VIDEO_SIGNAL_REFRESH_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self._refresh_seconds = refresh_seconds
        self._clock = clock
        self._last: dict[str, tuple[str, VideoSignalStatus, float]] = {}

    def should_publish(
        self, terminal_id: str, connection_id: str, status: VideoSignalStatus
    ) -> bool:
        now = self._clock()
        previous = self._last.get(terminal_id)
        if (
            previous is not None
            and previous[0] == connection_id
            and previous[1] == status
            and now - previous[2] < self._refresh_seconds
        ):
            return False
        self._last[terminal_id] = (connection_id, status, now)
        return True


class LocationHandler(MessageHandler):
    def __init__(
        self,
        event_publisher: EventPublisher,
        *,
        latest_position_writer: LatestPositionWriter | None = None,
        video_signal_tracker: VideoSignalStatusTracker | None = None,
    ) -> None:
        self._event_publisher = event_publisher
        self._latest_position_writer = latest_position_writer or LoggingLatestPositionWriter()
        self._video_signal_tracker = video_signal_tracker or VideoSignalStatusTracker()

    async def handle(
        self, message: InboundMessage, context: HandlerContext
    ) -> HandlerResult:
        session = await context.device_sessions.resolve_for_connection(
            message.terminal_id, context.connection_id
        )
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
                serial_no=message.serial_no,
            )
            return _general_response(message, RESULT_FAILURE)

        await context.device_sessions.touch(
            message.terminal_id, connection_id=context.connection_id
        )

        try:
            report = parse_position_report_body(message.body)
        except ProtocolError as exc:
            log_with_fields(
                logger,
                30,
                "position_report_malformed",
                connection_id=context.connection_id,
                terminal_id=message.terminal_id,
                serial_no=message.serial_no,
                body_length=len(message.body),
                error=str(exc),
            )
            return _general_response(message, RESULT_MESSAGE_ERROR)
        is_gps_valid = report.gps_valid and is_plausible_coordinate(
            report.latitude, report.longitude
        )

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
            is_gps_valid=is_gps_valid,
        )
        await self._latest_position_writer.write(event)
        await self._event_publisher.publish(event)
        await self._publish_video_signal_status(message, context, session, event)

        log_with_fields(
            logger,
            10,
            "position_report_published",
            connection_id=context.connection_id,
            terminal_id=message.terminal_id,
            is_backfill=False,
            is_gps_valid=is_gps_valid,
        )
        return _general_response(message, RESULT_SUCCESS)

    async def _publish_video_signal_status(
        self, message: InboundMessage, context: HandlerContext, session, position
    ) -> None:
        """ADR-0046 §1: the terminal's own per-channel camera signal (item `0x15`). A failure here
        is logged and never affects the position report itself."""
        try:
            status = video_signal_status(parse_additional_items(message.body))
            if status is None or not self._video_signal_tracker.should_publish(
                message.terminal_id, context.connection_id, status
            ):
                return
            await self._event_publisher.publish(
                DeviceVideoSignalStatusReported(
                    terminal_id=message.terminal_id,
                    organization_id=session.organization_id,
                    vehicle_id=session.vehicle_id,
                    device_id=session.device_id,
                    video_signal_loss_mask=status.loss_mask,
                    video_signal_occlusion_mask=status.occlusion_mask,
                    event_time=position.event_time,
                    received_at=position.received_at,
                )
            )
        except Exception as exc:  # noqa: BLE001 - never lose a position over an extra item
            log_with_fields(
                logger,
                30,
                "video_signal_status_publish_failed",
                connection_id=context.connection_id,
                terminal_id=message.terminal_id,
                error=str(exc),
            )
