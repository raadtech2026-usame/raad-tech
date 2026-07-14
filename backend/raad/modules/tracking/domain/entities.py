"""Tracking entities (Backend LLD §5.2; Database Design §7.1/§7.2; Phase 2 §22). Framework-
free — no SQLAlchemy/Pydantic/FastAPI, no I/O.

Two entities, exactly the two tables this module owns (Database Design §7.1/§7.2; JT808 LLD
§15: "the Business API persists `vehicle_positions`, `geofence_events`..."):

- `VehiclePosition` (§7.1) — a single GPS fix, already normalized by the JT808 device-plane
  ACL (Phase 2 §5.1) before it ever reaches this module. **Not** an aggregate root: it is
  created once (`record()`) and never mutated again — `vehicle_positions` has no update path,
  is hard-pruned by partition drop rather than soft-deleted (Database Design §9/§11.1,
  `.claude/rules/database.md` #5/#6) — and it emits no domain event, since the fact it
  represents (`DevicePositionReported`) was already announced by the JT808 plane
  (`.claude/rules/jt808.md` #1); persisting it here is storage of an already-announced fact,
  not a new one, the same reasoning `fleet_device.domain.entities.Device.mark_assigned` gives
  for emitting no event.
- `GeofenceCrossing` (§7.2) — a detected stop/organization-geofence crossing. This *is* the
  module's first-class domain fact (API Contracts §13.2 names `tracking` as the producer of
  `geofence.approaching_stop`/`geofence.arrived_org`; Phase 2 §22.2 names the other two), so
  it extends `_AggregateRoot` and its four factory methods each emit the corresponding event.
  Append-only like `fleet_device.domain.entities.DeviceAssignment`'s audit-shaped rows —
  `geofence_events` carries no `updated_at`/`deleted_at` (Database Design §7.2: "+created_at"
  only) — so there is no mutation method, only creation.

**Device connectivity (`Online`/`Offline`) and `device_status_log` are deliberately absent
from this module.** They are runtime state of the device plane's session manager (Phase 2
§21.1/§21.2), the same reasoning `fleet_device.domain.entities`'s module docstring gives for
excluding connectivity from `Device` — and Database Design §7's own heading groups
`device_status_log` under "Tracking (C5), Video (C6), Notifications (C7)" without assigning it
to a specific module, an ownership ambiguity this phase does not resolve (flagged, not
guessed, per `.claude/rules/workflow.md` #8).

**Geofence *configuration* (radius, approach threshold) is not modeled here either** — it
lives on `stops.geofence_radius_m` (`transport_ops`-owned) and `org_settings.settings_json`
(`organization`-owned, Database Design §4.7); this module consumes those by id/value only, per
the cross-module-DB-read prohibition (`.claude/rules/backend.md` #3). See `services.py` for
the stateless evaluation primitives that take a radius as a plain input rather than owning it.
"""

from __future__ import annotations

from datetime import datetime

from raad.core.errors.exceptions import DomainError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.tracking.domain import events as tracking_events
from raad.modules.tracking.domain.value_objects import (
    AlarmFlags,
    DeviceId,
    GeofenceCrossingId,
    GeofenceEventType,
    GeoPoint,
    HeadingDegrees,
    OrganizationId,
    SpeedKph,
    StopId,
    TripId,
    VehicleId,
    VehiclePositionId,
)


class _AggregateRoot:
    """Shared "raise and buffer domain events" mechanics (LLD §8.1), identical to
    `fleet_device.domain.entities._AggregateRoot`. Duplicated per module deliberately —
    `.claude/rules/backend.md` #1 forbids one module reaching into another's internals, and no
    approved doc calls for a shared-kernel package."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


class VehiclePosition:
    """A single GPS fix (Database Design §7.1). Plain entity, not an aggregate root — see
    module docstring for why no domain event is recorded. Immutable after construction: every
    field is set once by `record()` and never reassigned, matching the table's insert-only
    shape."""

    def __init__(
        self,
        *,
        id: VehiclePositionId,
        organization_id: OrganizationId,
        vehicle_id: VehicleId,
        device_id: DeviceId,
        trip_id: TripId | None,
        position: GeoPoint,
        speed_kph: SpeedKph | None,
        heading_deg: HeadingDegrees | None,
        alarm_flags: AlarmFlags | None,
        event_time: datetime,
        received_at: datetime,
        is_backfill: bool,
    ) -> None:
        self.id = id
        self.organization_id = organization_id
        self.vehicle_id = vehicle_id
        self.device_id = device_id
        self.trip_id = trip_id
        self.position = position
        self.speed_kph = speed_kph
        self.heading_deg = heading_deg
        self.alarm_flags = alarm_flags
        self.event_time = event_time
        self.received_at = received_at
        self.is_backfill = is_backfill

    def __eq__(self, other: object) -> bool:
        return isinstance(other, VehiclePosition) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def record(
        cls,
        *,
        id: VehiclePositionId,
        organization_id: OrganizationId,
        vehicle_id: VehicleId,
        device_id: DeviceId,
        position: GeoPoint,
        event_time: datetime,
        clock: Clock,
        trip_id: TripId | None = None,
        speed_kph: SpeedKph | None = None,
        heading_deg: HeadingDegrees | None = None,
        alarm_flags: AlarmFlags | None = None,
        is_backfill: bool = False,
    ) -> "VehiclePosition":
        """`event_time` is the device-reported time, passed through verbatim and never
        overwritten — buffered/backfilled positions (JT808 `0x0704`, late `0x0200`) publish
        with their *original* timestamp plus `is_backfill=True`
        (`.claude/rules/jt808.md` #3). `received_at` is this module's own ingest time
        (Database Design §7.1), taken from `clock` — never `event_time` — so the two stay
        independently meaningful (live-view filtering compares `event_time` to "now"; ingest
        latency is measured from `received_at`)."""
        return cls(
            id=id,
            organization_id=organization_id,
            vehicle_id=vehicle_id,
            device_id=device_id,
            trip_id=trip_id,
            position=position,
            speed_kph=speed_kph,
            heading_deg=heading_deg,
            alarm_flags=alarm_flags,
            event_time=event_time,
            received_at=clock.now(),
            is_backfill=is_backfill,
        )


class GeofenceCrossing(_AggregateRoot):
    """A detected stop/organization-geofence crossing (Database Design §7.2). Append-only —
    see module docstring — so the only operations are the four typed factories below, one per
    `GeofenceEventType` value, each emitting the matching `domain/events.py` fact. Evaluation
    itself (deciding *whether* a crossing occurred) is `services.GeofenceEvaluationService`'s
    job; this class only records the outcome once the caller has already decided."""

    def __init__(
        self,
        *,
        id: GeofenceCrossingId,
        organization_id: OrganizationId,
        trip_id: TripId,
        stop_id: StopId | None,
        event_type: GeofenceEventType,
        occurred_at: datetime,
    ) -> None:
        super().__init__()
        if (
            event_type
            in (
                GeofenceEventType.APPROACHING_STOP,
                GeofenceEventType.ENTERED_STOP,
            )
            and stop_id is None
        ):
            raise DomainError(f"{event_type.value} crossings require a stop_id")
        self.id = id
        self.organization_id = organization_id
        self.trip_id = trip_id
        self.stop_id = stop_id
        self.event_type = event_type
        self.occurred_at = occurred_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GeofenceCrossing) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def approaching_stop(
        cls,
        *,
        id: GeofenceCrossingId,
        organization_id: OrganizationId,
        trip_id: TripId,
        stop_id: StopId,
        clock: Clock,
    ) -> "GeofenceCrossing":
        crossing = cls(
            id=id,
            organization_id=organization_id,
            trip_id=trip_id,
            stop_id=stop_id,
            event_type=GeofenceEventType.APPROACHING_STOP,
            occurred_at=clock.now(),
        )
        crossing._record(
            tracking_events.vehicle_approaching_stop(
                crossing_id=str(id),
                organization_id=str(organization_id),
                trip_id=str(trip_id),
                stop_id=str(stop_id),
                occurred_at=crossing.occurred_at,
            )
        )
        return crossing

    @classmethod
    def entered_stop(
        cls,
        *,
        id: GeofenceCrossingId,
        organization_id: OrganizationId,
        trip_id: TripId,
        stop_id: StopId,
        clock: Clock,
    ) -> "GeofenceCrossing":
        crossing = cls(
            id=id,
            organization_id=organization_id,
            trip_id=trip_id,
            stop_id=stop_id,
            event_type=GeofenceEventType.ENTERED_STOP,
            occurred_at=clock.now(),
        )
        crossing._record(
            tracking_events.vehicle_entered_stop_geofence(
                crossing_id=str(id),
                organization_id=str(organization_id),
                trip_id=str(trip_id),
                stop_id=str(stop_id),
                occurred_at=crossing.occurred_at,
            )
        )
        return crossing

    @classmethod
    def arrived_at_organization(
        cls,
        *,
        id: GeofenceCrossingId,
        organization_id: OrganizationId,
        trip_id: TripId,
        clock: Clock,
    ) -> "GeofenceCrossing":
        crossing = cls(
            id=id,
            organization_id=organization_id,
            trip_id=trip_id,
            stop_id=None,
            event_type=GeofenceEventType.ARRIVED_ORG,
            occurred_at=clock.now(),
        )
        crossing._record(
            tracking_events.vehicle_arrived_at_organization(
                crossing_id=str(id),
                organization_id=str(organization_id),
                trip_id=str(trip_id),
                occurred_at=crossing.occurred_at,
            )
        )
        return crossing

    @classmethod
    def exited(
        cls,
        *,
        id: GeofenceCrossingId,
        organization_id: OrganizationId,
        trip_id: TripId,
        stop_id: StopId | None,
        clock: Clock,
    ) -> "GeofenceCrossing":
        """`stop_id=None` means exiting the organization geofence; a `StopId` means exiting
        that stop's geofence (Database Design §7.2's nullable `stop_id`)."""
        crossing = cls(
            id=id,
            organization_id=organization_id,
            trip_id=trip_id,
            stop_id=stop_id,
            event_type=GeofenceEventType.EXITED,
            occurred_at=clock.now(),
        )
        crossing._record(
            tracking_events.vehicle_exited_geofence(
                crossing_id=str(id),
                organization_id=str(organization_id),
                trip_id=str(trip_id),
                stop_id=str(stop_id) if stop_id is not None else None,
                occurred_at=crossing.occurred_at,
            )
        )
        return crossing
