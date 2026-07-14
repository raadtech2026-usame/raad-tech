"""Tracking application commands (Backend LLD §4.2 "intent DTOs"). Immutable request objects
describing what the caller wants done. Identifiers are plain `str` (converted to value objects
inside `services.py`); `GeofenceEventType` is passed as the already-typed domain enum — the
same treatment `fleet_device.application.commands.RegisterCameraCommand.position:
CameraPosition` gives an already-parsed enum.

**No command here carries an `actor: Principal`**, unlike every `fleet_device`/`organization`/
`iam` command. Those commands are all triggered by a human caller through an API route; every
command in this module is triggered by a system process instead — `RecordVehiclePosition`/
`RecordBackfillPosition` by the JT808 device-plane event consumer (Phase 2 §6.1: `device.
position_reported`), `RecordGeofenceCrossing` by the geofence evaluator (Phase 2 §22.2), and
`EvaluateGeofence` by whichever of those calls it. This mirrors `tracking.domain.entities`
already having no `actor_id` anywhere (Phase 8.1) — there is no human actor to carry.

Only four action use-cases are modeled, exactly Phase 2 §22.2's evaluation flow: a live
position is recorded (`RecordVehiclePosition`) or a buffered one is (`RecordBackfillPosition`,
JT808 `0x0704`/late `0x0200` — same shape, distinct command per JT808 LLD §8's distinct
handler, `.claude/rules/jt808.md` #3); a live, non-backfill position is evaluated against a
geofence (`EvaluateGeofence`, pure — see `services.py`); a detected transition is recorded
(`RecordGeofenceCrossing`). No `ChangeVehicleDriver`-style unbuilt-use-case placeholder is
needed here — Phase 2 §22 names no other tracking commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from raad.modules.tracking.domain.value_objects import GeofenceEventType

# --- Position ingestion (Phase 2 §5.1/§22.2; JT808 LLD §8/§10) ----------------------------


@dataclass(frozen=True)
class RecordVehiclePositionCommand:
    """A live GPS fix (JT808 `0x0200`). `event_time` is the device-reported time — never
    replaced with "now" (`.claude/rules/jt808.md` #3)."""

    organization_id: str
    vehicle_id: str
    device_id: str
    latitude: float
    longitude: float
    event_time: datetime
    trip_id: str | None = None
    speed_kph: int | None = None
    heading_deg: int | None = None
    alarm_flags: int | None = None


@dataclass(frozen=True)
class RecordBackfillPositionCommand:
    """A buffered GPS fix ingested on reconnect (JT808 `0x0704`, or a late `0x0200`).
    Identical fields to `RecordVehiclePositionCommand` — the distinction is which JT808
    handler produced it (JT808 LLD §8's `Bulk Location` row) and that the resulting
    `VehiclePosition.is_backfill` is `True`, never live fan-out/geofence-evaluated
    (`.claude/rules/jt808.md` #3; Phase 2 §22.2: "live, non-backfill" positions only feed the
    evaluator)."""

    organization_id: str
    vehicle_id: str
    device_id: str
    latitude: float
    longitude: float
    event_time: datetime
    trip_id: str | None = None
    speed_kph: int | None = None
    heading_deg: int | None = None
    alarm_flags: int | None = None


# --- Geofence evaluation (Phase 2 §22.2/§22.3) ---------------------------------------------


@dataclass(frozen=True)
class EvaluateGeofenceCommand:
    """Tests one position against one geofence circle (a stop's approach radius, a stop's
    arrival radius, or the organization's radius — the caller decides which by which
    center/radius it supplies; this command is deliberately geofence-kind-agnostic, matching
    `GeofenceEvaluationService.is_within_radius`'s single-circle shape, Phase 8.1). Pure
    computation — no organization/trip context is needed since nothing is persisted or looked
    up (see `services.py`'s `evaluate_geofence`, which performs no I/O for this command).
    """

    position_latitude: float
    position_longitude: float
    center_latitude: float
    center_longitude: float
    radius_m: float
    was_inside: bool


@dataclass(frozen=True)
class RecordGeofenceCrossingCommand:
    """Persists a crossing already decided by the caller (typically off an `EvaluateGeofence`
    result showing `ENTERED`/`EXITED`) as the matching `GeofenceEventType`. `stop_id` is
    required for `approaching_stop`/`entered_stop` and optional for `arrived_org`/`exited` —
    enforced by `GeofenceCrossing.__init__` (Phase 8.1's domain invariant), not re-checked
    here (`.claude/rules/backend.md` #6-adjacent principle: never duplicate a domain rule at
    the application layer)."""

    organization_id: str
    trip_id: str
    event_type: GeofenceEventType
    stop_id: str | None = None
