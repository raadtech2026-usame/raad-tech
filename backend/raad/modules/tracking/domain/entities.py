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

from raad.core.errors.exceptions import DomainError, RuleViolationError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.tracking.domain import events as tracking_events
from raad.modules.tracking.domain.value_objects import (
    ALARM_TYPES,
    CRITICAL_ALARM_TYPES,
    AlarmFlags,
    DeviceConfirmation,
    DeviceId,
    GeofenceCrossingId,
    GeofenceEventType,
    GeoPoint,
    HeadingDegrees,
    OrganizationId,
    SafetyAlertId,
    SafetyAlertStatus,
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
        is_gps_valid: bool = True,
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
        self.is_gps_valid = is_gps_valid

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
        is_gps_valid: bool = True,
    ) -> "VehiclePosition":
        """`event_time` is the device-reported time, passed through verbatim and never
        overwritten — buffered/backfilled positions (JT808 `0x0704`, late `0x0200`) publish
        with their *original* timestamp plus `is_backfill=True`
        (`.claude/rules/jt808.md` #3). `received_at` is this module's own ingest time
        (Database Design §7.1), taken from `clock` — never `event_time` — so the two stay
        independently meaningful (live-view filtering compares `event_time` to "now"; ingest
        latency is measured from `received_at`).

        `is_gps_valid` (root-cause fix, RAAD Live Tracking wrong-location investigation):
        `True` only when the device-plane ACL (`services/device-gateway`) confirmed both a
        genuine wire-level GPS fix *and* a plausible coordinate (finite, in-range, not
        null-island) at the moment this position was reported — see `gps_validation.
        is_plausible_coordinate` on that side, and `DevicePositionReported`'s own module
        docstring for the full record. Always persisted, never used to reject the position
        outright: `position`/`GeoPoint` may still hold a numerically valid-but-implausible or
        stale coordinate here, preserved verbatim for audit/debugging
        (`docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md`'s own "never invent a
        vehicle location, but never lie by silence either" posture) — callers that need "is
        this the vehicle's real live position" must check this flag, not just that a position
        exists."""
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
            is_gps_valid=is_gps_valid,
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


# ---- ADR-0055: safety alerts --------------------------------------------------------------------

#: An alarm received this long after it happened is recorded but not announced as live.
LATE_ALARM_SECONDS = 600
_OPEN_STATUSES = (SafetyAlertStatus.OPEN, SafetyAlertStatus.ACKNOWLEDGED)


class SafetyAlert(_AggregateRoot):
    """A device alarm on a bus (ADR-0055 §3). One alert per bus and type stays open at a time: a
    repeat while it is open adds to `occurrences` instead of creating another, so a flapping bit
    is one alert. `trip_id`/`driver_id` are what was running on that bus when it started,
    resolved once and never re-derived."""

    def __init__(
        self,
        *,
        id: SafetyAlertId,
        organization_id: OrganizationId,
        vehicle_id: VehicleId,
        device_id: str | None,
        terminal_id: str,
        alarm_type: str,
        status: SafetyAlertStatus,
        raised_at: datetime,
        last_raised_at: datetime,
        received_at: datetime,
        occurrences: int,
        latitude: float | None,
        longitude: float | None,
        speed_kph: float | None,
        trip_id: str | None,
        driver_id: str | None,
        incident_id: str | None,
        device_confirmation: DeviceConfirmation | None,
        acknowledged_at: datetime | None,
        closed_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        if alarm_type not in ALARM_TYPES:
            raise DomainError(f"Unknown alarm type {alarm_type!r}")
        self.id = id
        self.organization_id = organization_id
        self.vehicle_id = vehicle_id
        self.device_id = device_id
        self.terminal_id = terminal_id
        self.alarm_type = alarm_type
        self.status = status
        self.raised_at = raised_at
        self.last_raised_at = last_raised_at
        self.received_at = received_at
        self.occurrences = occurrences
        self.latitude = latitude
        self.longitude = longitude
        self.speed_kph = speed_kph
        self.trip_id = trip_id
        self.driver_id = driver_id
        self.incident_id = incident_id
        self.device_confirmation = device_confirmation
        self.acknowledged_at = acknowledged_at
        self.closed_at = closed_at
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SafetyAlert) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def is_critical(self) -> bool:
        return self.alarm_type in CRITICAL_ALARM_TYPES

    @property
    def is_open(self) -> bool:
        return self.status in _OPEN_STATUSES

    @property
    def is_late(self) -> bool:
        return (self.received_at - self.raised_at).total_seconds() > LATE_ALARM_SECONDS

    @classmethod
    def raise_alarm(
        cls,
        *,
        id: SafetyAlertId,
        organization_id: OrganizationId,
        vehicle_id: VehicleId,
        device_id: str | None,
        terminal_id: str,
        alarm_type: str,
        raised_at: datetime,
        received_at: datetime,
        latitude: float | None,
        longitude: float | None,
        speed_kph: float | None,
        trip_id: str | None,
        driver_id: str | None,
        clock: Clock,
    ) -> "SafetyAlert":
        now = clock.now()
        alert = cls(
            id=id,
            organization_id=organization_id,
            vehicle_id=vehicle_id,
            device_id=device_id,
            terminal_id=terminal_id,
            alarm_type=alarm_type,
            status=SafetyAlertStatus.OPEN,
            raised_at=raised_at,
            last_raised_at=raised_at,
            received_at=received_at,
            occurrences=1,
            latitude=latitude,
            longitude=longitude,
            speed_kph=speed_kph,
            trip_id=trip_id,
            driver_id=driver_id,
            incident_id=None,
            device_confirmation=None,
            acknowledged_at=None,
            closed_at=None,
            created_at=now,
            updated_at=now,
        )
        alert._record(
            tracking_events.safety_alert_raised(
                alert_id=str(id),
                organization_id=str(organization_id),
                vehicle_id=str(vehicle_id),
                alarm_type=alarm_type,
                is_critical=alert.is_critical,
                is_late=alert.is_late,
                trip_id=trip_id,
                raised_at=raised_at,
            )
        )
        return alert

    def repeat(self, *, raised_at: datetime, clock: Clock) -> None:
        """The same alarm started again while this alert is still open. No event: a repeat is
        not news, and must not re-notify anyone."""
        self.occurrences += 1
        self.last_raised_at = max(self.last_raised_at, raised_at)
        self.updated_at = clock.now()

    def acknowledge(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status is not SafetyAlertStatus.OPEN:
            raise RuleViolationError(f"Only an open alert can be acknowledged; this one is {self.status.value}.")
        now = clock.now()
        self.status = SafetyAlertStatus.ACKNOWLEDGED
        self.acknowledged_at = self.updated_at = now
        self._status_changed(actor_id)

    def resolve(self, *, clock: Clock, actor_id: str | None = None, incident_id: str | None = None) -> None:
        self._close(SafetyAlertStatus.RESOLVED, clock=clock, actor_id=actor_id, incident_id=incident_id)

    def mark_false_alarm(self, *, clock: Clock, actor_id: str | None = None) -> None:
        self._close(SafetyAlertStatus.FALSE_ALARM, clock=clock, actor_id=actor_id, incident_id=None)

    def record_device_confirmation(self, confirmation: DeviceConfirmation, *, clock: Clock) -> None:
        self.device_confirmation = confirmation
        self.updated_at = clock.now()

    def _close(self, status: SafetyAlertStatus, *, clock: Clock, actor_id: str | None, incident_id: str | None) -> None:
        if not self.is_open:
            raise RuleViolationError(f"This alert is already {self.status.value}.")
        now = clock.now()
        self.status = status
        self.incident_id = incident_id
        self.closed_at = self.updated_at = now
        self._status_changed(actor_id)

    def _status_changed(self, actor_id: str | None) -> None:
        self._record(
            tracking_events.safety_alert_status_changed(
                alert_id=str(self.id),
                organization_id=str(self.organization_id),
                status=self.status.value,
                incident_id=self.incident_id,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )
