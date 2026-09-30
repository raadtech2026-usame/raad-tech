"""Cross-module adapter for ADR-0050's bus crew assignments.

`transport_ops` must check that a bus belongs to the same organization as the staff member it
is putting on it, but buses belong to `fleet_device`, and `.claude/rules/backend.md` #3 forbids
reading another module's tables. This adapter asks `fleet_device`'s own application service
instead. It lives in the composition root for the same reason `erp_adapters.py` does: neither
module imports the other.
"""

from __future__ import annotations

from raad.core.di.container import Container
from raad.core.errors.exceptions import DomainError, NotFoundError
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.queries import GetVehicleByIdQuery
from raad.modules.fleet_device.application.services import VehicleApplicationService
from raad.modules.transport_ops.application.ports import VehicleDirectoryPort


class FleetVehicleDirectoryAdapter(VehicleDirectoryPort):
    """Answers "which organization owns this bus" on an unscoped `fleet_device` Unit of Work.

    Unscoped on purpose: the caller compares the answer with the staff member's organization
    and answers 404 on a mismatch, so a bus in another tenant is indistinguishable from one that
    does not exist. A malformed id is treated the same way.
    """

    def __init__(self, container: Container) -> None:
        self._container = container

    async def organization_of_vehicle(self, vehicle_id: str) -> str | None:
        service: VehicleApplicationService = self._container.resolve(VehicleApplicationService)
        uow: FleetDeviceUnitOfWork = self._container.resolve(FleetDeviceUnitOfWork)
        try:
            vehicle = await service.get_vehicle_by_id(
                GetVehicleByIdQuery(vehicle_id=vehicle_id), uow=uow
            )
        except (NotFoundError, DomainError):
            return None
        return vehicle.organization_id
