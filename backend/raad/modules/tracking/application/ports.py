"""Outbound ports the `tracking` application layer depends on (Backend LLD §4.2).
`TrackingUnitOfWork` is the existing core abstraction (`core.db.unit_of_work`), extended here
with `tracking`'s own repositories — exactly what `FleetDeviceUnitOfWork`/
`OrganizationUnitOfWork`/`IamUnitOfWork` already do. `Clock`/`IdGenerator` are likewise
existing core ports, used as constructor dependencies by `services.py` — never redefined here.

`core.db.unit_of_work` co-locates the abstract `UnitOfWork` with its concrete
`SqlAlchemyUnitOfWork` implementation in the same file, so importing the interface transitively
requires SQLAlchemy to be installed. Accepted deliberately here for the same reason
`fleet_device`/`organization`/`iam`'s ports modules accept it: SQLAlchemy is an already-approved
project dependency (Phase 4.4), this application layer's own code never references it directly,
and the LLD's own `application/ports.py` contract skeleton (§4.2) explicitly expects
`interface UnitOfWork` to be referenced from exactly this file.

**`LatestPositionPort` is a genuinely new port this phase defines** (unlike `fleet_device`'s
declined `DeviceCommandPort`, which had zero use-cases needing it). Database Design §7.1 states
plainly "Latest position is NOT read from here" — the current position lives in Redis
(Phase 2 §10.3; JT808 LLD §14's `vehicle:{id}:last`), not the partitioned `vehicle_positions`
history table `VehiclePositionRepository` backs. `GetCurrentVehiclePositionQuery` is an
explicitly approved use case (API Contracts §4.4: `GET /tracking/vehicles/{id}/latest`) whose
only documented backing store is Redis, so — unlike the fleet_device precedent — declining to
define this port would leave an approved use case with no way to be implemented at all. The abstract interface is
defined here; the concrete Redis-backed implementation
(`infra.adapters.RedisLatestPositionPort`, Backend Stabilization phase) is read-only — see that
module's own docstring for why no write method exists on either the interface or the adapter
(the JT808 device-plane service, not this backend, is the documented writer of
`vehicle:{id}:last`).

**`GeofenceStatePort` (post-F7 roadmap item A5; ADR-0014).** Phase 2 §22.2's evaluation
architecture keeps "active-trip geofence state" in Redis, distinct in purpose from
`LatestPositionPort` (that key holds the vehicle's current *position*; this one holds the
evaluator's own *hysteresis bookkeeping* — which stop is currently being approached, whether the
vehicle was inside each radius on the previous position, and per-event-type cooldown
timestamps). `GeofenceHysteresisState` is this port's own payload contract, the same role
`VehiclePosition` plays for `LatestPositionPort` — a plain, JSON-serializable shape, not a domain
entity (this bookkeeping isn't a business fact `tracking` owns the way a `GeofenceCrossing` is;
it is disposable evaluator state, safe to lose and rebuild from scratch on a cache miss). The
concrete implementation (`infra.adapters.RedisGeofenceStatePort`) is read-write, unlike
`LatestPositionPort` — this evaluator (not a separate device-plane service) is the one and only
writer of this key.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.tracking.domain.entities import VehiclePosition
from raad.modules.tracking.domain.repositories import (
    GeofenceCrossingRepository,
    VehiclePositionRepository,
)
from raad.modules.tracking.domain.value_objects import TripId, VehicleId


class TrackingUnitOfWork(UnitOfWork):
    """Bundles the two repositories `tracking`'s use-cases need onto one transaction boundary
    (LLD §8.2 contract skeleton style — plain attributes, matching
    `FleetDeviceUnitOfWork`/`OrganizationUnitOfWork`/`IamUnitOfWork`). The concrete
    implementation (a future `SqlAlchemyTrackingUnitOfWork`) is infra, not implemented in this
    phase."""

    vehicle_positions: VehiclePositionRepository
    geofence_crossings: GeofenceCrossingRepository


class LatestPositionPort(ABC):
    """Read-only access to the current position of a vehicle. See module docstring for why
    this is not `VehiclePositionRepository` — Redis, not the MySQL history table, is the
    documented source of truth for "latest"."""

    @abstractmethod
    async def get_latest(self, vehicle_id: VehicleId) -> VehiclePosition | None:
        raise NotImplementedError

    @abstractmethod
    async def get_latest_many(
        self, vehicle_ids: list[VehicleId]
    ) -> dict[VehicleId, VehiclePosition]:
        """ADR-0031 (Fleet Overview read model) — the bulk sibling of `get_latest`, for the All
        Vehicles map's one-time initial snapshot (realtime *updates* after that still go
        entirely over the existing `/ws/tracking` per-vehicle subscriptions, never this port —
        see the ADR's own scalability analysis for why). A single round trip regardless of how
        many vehicle ids are asked for (the concrete `RedisLatestPositionPort` uses `MGET`, not
        an `get_latest` loop) — the same "one round trip, not N" reasoning
        `fleet_device.VehicleRepository.list_by_ids` applies on the SQL side. A vehicle with no
        cached key is simply absent from the returned dict, the identical "honest, not an
        error" contract `get_latest` already has for a single vehicle."""
        raise NotImplementedError


@dataclass
class GeofenceHysteresisState:
    """Per-trip geofence evaluator bookkeeping (see module docstring). Mutable — the caller
    loads one, mutates fields in place as it evaluates a position, then saves it back.

    `stop_target_id` — the single stop currently being approached/entered (Phase 2 §22.3:
    "'approaching' fires for the *next* assigned stop in route order, not stops already
    passed"). `stops_exhausted` — `True` once every stop on the route has been passed;
    disambiguates "target not yet resolved" (a brand-new state, `stop_target_id is None` and
    `stops_exhausted is False` — evaluation should target the route's first stop) from "no more
    stops to evaluate this trip" (`stop_target_id is None` and `stops_exhausted is True`).
    `stop_is_inside_arrival`/`stop_is_inside_approach` — this trip's previous-position
    containment reading against the target stop's arrival/approach radii, feeding
    `GeofenceEvaluationService.detect_transition`. `org_is_inside` — the same, independently,
    against the organization's own geofence (not sequence-bound; evaluated every position
    regardless of stop progress). `last_fired_at` — ISO-8601 timestamp of the last time each
    `GeofenceEventType` value fired for this trip, backing the cooldown window
    (`tracking.events.subscribers`'s own module docstring; Phase 2 §22.3)."""

    stop_target_id: str | None = None
    stops_exhausted: bool = False
    stop_is_inside_arrival: bool = False
    stop_is_inside_approach: bool = False
    org_is_inside: bool = False
    last_fired_at: dict[str, str] = field(default_factory=dict)


class GeofenceStatePort(ABC):
    """Read-write per-trip geofence hysteresis state (see module docstring) — unlike
    `LatestPositionPort`, this evaluator is the sole writer, so both directions are defined
    here rather than split across a read-only interface plus an undocumented write path."""

    @abstractmethod
    async def get_state(self, trip_id: TripId) -> GeofenceHysteresisState | None:
        raise NotImplementedError

    @abstractmethod
    async def save_state(self, trip_id: TripId, state: GeofenceHysteresisState) -> None:
        raise NotImplementedError
