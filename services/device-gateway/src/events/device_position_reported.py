"""`DevicePositionReported` — the device-plane domain event this service publishes for every
JT/T 808-2013 `0x0200`/`0x0704` position report (Phase 2 Enterprise Architecture §6.1's
"Telemetry events (device plane)" list; JT808 Technical Design §8's Handler table: Location/
BulkLocation both "Emit: `device.position_reported`"). Field shape is the canonical
`PositionReport` §10 defines verbatim: "`PositionReport { organization_id, vehicle_id,
device_id, trip_id?, lat, lng, speed_kph, heading_deg, alarm_flags, event_time, is_backfill }`"
— this dataclass mirrors that shape one-to-one, which is not a coincidence: it is the same field
set `tracking.application.commands.RecordVehiclePositionCommand`/`RecordBackfillPositionCommand`
expect (confirmed by cross-reading both modules), so a future Business API-side consumer can
build one of those commands from this event with no field renaming or unit conversion of its
own — this module has already done the unit/sign/timezone conversion (`position_body.py`).

**Why this module never imports `tracking`'s command/value-object classes itself, even though
the shape matches:** `.claude/rules/architecture.md` #3 ("the device plane communicates with
the business plane exclusively through asynchronous domain events over the broker — never
direct DB writes, never synchronous RPC from device services into the business database"),
`.claude/rules/jt808.md` #1 ("This service never writes Business API tables directly. It only
publishes domain events... to the broker"), and JT808 Technical Design §1 ("JT808 does not
write `vehicle_positions` directly — it emits events; the Business API's tracking consumer
persists") are unanimous and were confirmed with the user before this phase's design (see
`location_handler.py`'s module docstring for the full conflict record). `services/jt808/` and
`backend/raad/` are separate deployables/processes — there is no import boundary to cross even
if this module wanted to call `TrackingApplicationService` directly, only a network/broker one.

**`trip_id` is always `None` this phase.** JT808 Technical Design §10: "the position is tagged
with the vehicle's currently active trip if one exists... [read from] a read-model cache in
Redis kept current by `trip.started`/`trip.ended` events... If unknown, `trip_id` is null and
the Business API's consumer resolves/repairs it." No such Redis-backed active-trip cache exists
anywhere in `services/jt808/src/` yet (out of this phase's explicit scope) — `trip_id` is always
`None`, which is the documented, correct fallback, not a placeholder bug.

**`organization_id`/`vehicle_id`/`device_id` are required (`str`, not `str | None`) on this
event**, even though `DeviceSession` types them as optional pass-through fields — a position
report from a session missing any of the three cannot be mapped to a valid event and is
dropped-with-audit-log by the handler instead of being published with a hole in it (see
`location_handler.py`).

**`is_gps_valid` (root-cause fix, RAAD Live Tracking wrong-location investigation).** Neither
vendor adapter previously propagated the wire-level GPS fix-validity signal past its own ACL
parsing step: JT/T 808's `status` DWORD bit 1 ("positioned", `position_body.py`) and the LSZ
protocol's 'A'/'V' positioning-status flag (`vendors/lsz/protocol/location_status.
LocationStatus.fix_valid`) were both parsed and then silently discarded before a
`DevicePositionReported` was ever constructed — every position report was published and treated
as an equally-trustworthy live fix regardless of whether the device actually had one. A device
without a live fix (cold start, indoor parking, antenna fault) commonly reports its last cached/
factory fix rather than a zeroed one; for this vendor's procured hardware, that cached fix is a
Shenzhen, China coordinate left over from factory testing — which is how a real "China" reading
reached the Live Tracking map despite the vehicle actually being in Mogadishu. `is_gps_valid` is
`True` only when the device itself reported a live fix **and** the resulting coordinate passes
`gps_validation.is_plausible_coordinate` (finite, in-range, not null-island) — see `src/
gps_validation.py`. It is carried all the way to the Business API (`tracking.domain.entities.
VehiclePosition.is_gps_valid`, persisted on `vehicle_positions`) so a flagged position is still
stored for audit/debugging (never silently dropped) but is never treated as the current live
position: `RedisLatestPositionWriter`/`RedisLatestPositionPort` (`vehicle:{id}:last`) only ever
reflect a valid fix, and `/ws/tracking` forwards this flag verbatim so the frontend can show
"GPS: No Fix" instead of silently relocating the marker to a stale/implausible reading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DevicePositionReported:
    organization_id: str
    vehicle_id: str
    device_id: str
    terminal_id: str
    trip_id: str | None
    latitude: float
    longitude: float
    speed_kph: int
    heading_deg: int
    alarm_flags: int
    event_time: datetime
    is_backfill: bool
    received_at: datetime
    is_gps_valid: bool = True
