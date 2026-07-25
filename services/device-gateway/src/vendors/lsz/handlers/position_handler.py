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

**Bug found and fixed (ADR-0012 live-verification pass):** "uncertain" above was only being
treated as "parsed to `None`" — a value that parsed to a concrete but out-of-range int (e.g. this
vendor's own "ground course" worked examples, which `protocol.location_status` already documents
as falling far outside 0-360 in both cases) flowed straight through unchecked. The Business API's
`tracking` domain correctly rejects an out-of-range `HeadingDegrees`/`AlarmFlags` with a
`DomainError`, which silently failed *every* position event forever (retried indefinitely, never
persisted, never dead-lettered within any short observation window) — not a rare edge case, since
both of this vendor's own documented worked examples hit it. `_clamp_heading`/`_clamp_alarm_flags`
below now range-check before publishing, so "uncertain" actually means what this docstring already
claimed it meant.

**`alarm_flags` needs its own caveat, distinct from `heading_deg`.** Heading is cosmetic (map
display only); defaulting it to `0` on an out-of-range read has no safety consequence. Alarm flags
are safety-relevant (`jt808.md`: SOS/overspeed/fatigue/low-power/GPS-fault/video-loss taxonomy),
and this vendor sends a raw 16-hex-char (64-bit) opaque bitfield where the Business API's
`AlarmFlags` expects an *already-normalized*, JT/T-808-taxonomy 32-bit value (Database Design
§7.1: `alarm_flags INT`) — no one has written that bit-mapping yet (`protocol.location_status`'s
own docstring already flags this as out of scope for its ACL step). `0` here means **"unmapped/
unknown," not a verified "no alarms" reading** — accepted as the least-bad interim default
(user-confirmed) only because nothing in this codebase yet triggers any safety action off this
field; a real per-bit ACL mapping from Hardware Analysis §5 is still required before `alarm_flags`
can be trusted for anything safety-relevant.

**No wire response is sent** — the vendor document names no acknowledgment for `V114` in either
of its two worked examples (`docs/vendor/HARDWARE_ANALYSIS.md` §9's Commands table), matching the
parent package's own `LocationHandler`'s identical "no ack for a position report" precedent.

**`trip_id` is always `None`** — same fallback and same reasoning as the parent package's
`LocationHandler`: no active-trip Redis read-model exists in this deployable.

**Calls `touch()` on every accepted position, not just on `V109` heartbeats (bug fix,
`docs/architecture/post-f7-production-readiness-roadmap.md` A1).** Previously only
`MdvrHeartbeatHandler` called `touch()` — a device sending only `V114` position reports (a
plausible firmware configuration; nothing in the vendor documentation guarantees both message
types are always sent) was never promoted `AUTHENTICATED -> ONLINE`, and would eventually be swept
`session_expired` by the idle-timeout sweep *while actively transmitting GPS*. `touch()` is safe to
call unconditionally here: it is a no-op on an unknown `terminal_id` (mirrors
`MdvrHeartbeatHandler`'s own already-established "safe no-op" precedent), and this handler already
requires a resolved session before reaching this point, so the call always targets a real one.
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

# Mirrors `raad.modules.tracking.domain.value_objects` exactly (`_HEADING_MAX_EXCLUSIVE`,
# `_INT_MAX`) — duplicated, not imported, since this deployable never depends on `backend/raad`
# (`.claude/rules/architecture.md` #2). Keep in sync if either bound ever changes there.
_HEADING_MAX_EXCLUSIVE = 360
_ALARM_FLAGS_MAX = 2_147_483_647


def _clamp_heading(raw: int | None) -> int:
    """`0` when missing or outside `[0, 360)` — see module docstring's "Bug found and fixed" note."""
    if raw is None or not (0 <= raw < _HEADING_MAX_EXCLUSIVE):
        return 0
    return raw


def _clamp_alarm_flags(raw: int | None) -> int:
    """`0` ("unmapped/unknown", not a verified no-alarms reading) when missing or outside the
    domain's normalized 32-bit range — see module docstring's `alarm_flags` caveat."""
    if raw is None or not (0 <= raw <= _ALARM_FLAGS_MAX):
        return 0
    return raw


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

        await context.device_sessions.touch(message.device_serial_number)

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
            heading_deg=_clamp_heading(location.heading_deg),
            alarm_flags=_clamp_alarm_flags(location.component_status_alarm),
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
