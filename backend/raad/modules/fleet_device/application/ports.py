"""Outbound ports the `fleet_device` application layer depends on (Backend LLD §4.2).
`UnitOfWork` is the existing core abstraction (`core.db.unit_of_work`), extended here with
`fleet_device`'s own repositories — exactly what `IamUnitOfWork`/`OrganizationUnitOfWork`
already do. `Clock`/`IdGenerator` are likewise existing core ports, used as constructor
dependencies by the application services (`services.py`) — never redefined here.

`DeviceCommandPort` (LLD §4.2's D6 seam toward the JT808 service) is deliberately **not**
defined this phase: no use-case below sends anything to a device — assignment/lifecycle
changes are pure business-plane state (the device plane learns them via events/read-model,
Phase 3.4 §15), and command-downlink use-cases belong to the device-plane phases. Defining an
unused port now would be a stub the composition root refuses to bind anyway ("fail loudly,
don't fake it", `core/di/bootstrap.py`).

`core.db.unit_of_work` co-locates the abstract `UnitOfWork` with its concrete
`SqlAlchemyUnitOfWork` implementation in the same file, so importing the interface transitively
requires SQLAlchemy to be installed. Accepted deliberately here for the same reason
`iam`/`organization`'s ports modules accept it: SQLAlchemy is an already-approved project
dependency (Phase 4.4), this application layer's own code never references it directly, and
the LLD's own `application/ports.py` contract skeleton (§4.2) explicitly expects
`interface UnitOfWork` to be referenced from exactly this file.
"""

from __future__ import annotations

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.fleet_device.domain.repositories import (
    DeviceAssignmentRepository,
    DeviceRepository,
    VehicleRepository,
)


class FleetDeviceUnitOfWork(UnitOfWork):
    """Bundles the three repositories `fleet_device`'s use-cases need onto one transaction
    boundary (LLD §8.2 contract skeleton style — plain attributes, matching
    `IamUnitOfWork`/`OrganizationUnitOfWork`). The concrete implementation (a future
    `SqlAlchemyFleetDeviceUnitOfWork`) is infra, not implemented in this phase."""

    vehicles: VehicleRepository
    devices: DeviceRepository
    device_assignments: DeviceAssignmentRepository
