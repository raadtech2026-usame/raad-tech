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
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.tracking.domain.entities import VehiclePosition
from raad.modules.tracking.domain.repositories import (
    GeofenceCrossingRepository,
    VehiclePositionRepository,
)
from raad.modules.tracking.domain.value_objects import VehicleId


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
