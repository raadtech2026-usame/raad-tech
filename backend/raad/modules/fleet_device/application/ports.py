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

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.fleet_device.domain.repositories import (
    DeviceAssignmentRepository,
    DeviceInventoryRepository,
    DeviceRepository,
    VehicleRepository,
)


class FleetDeviceUnitOfWork(UnitOfWork):
    """Bundles the four repositories `fleet_device`'s use-cases need onto one transaction
    boundary (LLD §8.2 contract skeleton style — plain attributes, matching
    `IamUnitOfWork`/`OrganizationUnitOfWork`). The concrete implementation
    (`SqlAlchemyFleetDeviceUnitOfWork`) is infra.

    `device_inventory` (ADR-0018) bundled onto the same UoW as `devices` deliberately —
    `allocate_device_inventory_item` must transition a `DeviceInventoryItem` and create a
    `Device` row in one transaction, and both repositories are owned by this same module."""

    vehicles: VehicleRepository
    devices: DeviceRepository
    device_assignments: DeviceAssignmentRepository
    device_inventory: DeviceInventoryRepository


@dataclass(frozen=True)
class CameraSignalReport:
    """The terminal's own latest per-channel video-signal report (ADR-0046 §1, `0x0200` items
    `0x15`/`0x16`). Bit n-1 of `loss_mask` set = logical channel n has no video signal."""

    loss_mask: int
    occlusion_mask: int | None
    reported_at: datetime


class CameraSignalStatePort(ABC):
    """Where the latest `CameraSignalReport` per device lives. Volatile, device-reported state
    shared by the worker (writes, from `DeviceVideoSignalStatusReported`) and the API (reads) -
    the ADR-0044 §2 Redis pattern, deliberately not a PostgreSQL column: it is a momentary fact
    about the terminal, refreshed on every reconnect and every few minutes while it is online. The
    last report is kept across outages (physical installation rarely changes, and the first report
    after a reconnect corrects it); only a long-silent terminal reads as "unknown"."""

    @abstractmethod
    async def save(self, device_id: str, report: CameraSignalReport) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_many(self, device_ids: Sequence[str]) -> dict[str, CameraSignalReport]:
        raise NotImplementedError
