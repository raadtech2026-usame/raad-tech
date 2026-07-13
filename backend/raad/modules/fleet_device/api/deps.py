"""FastAPI dependency wiring for `fleet_device` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `FleetDeviceUnitOfWork` and application services — the only place this
module's HTTP layer touches `core.di`; routers never import the container directly beyond
this file, and never construct a repository or touch SQLAlchemy. Mirrors
`iam`/`organization.api.deps` exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.interfaces.http.deps import get_container
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.services import (
    DeviceApplicationService,
    VehicleApplicationService,
)


def get_fleet_device_uow(
    container: Container = Depends(get_container),
) -> FleetDeviceUnitOfWork:
    """Resolves a fresh `FleetDeviceUnitOfWork` per call — **not** entered here, for the same
    reason `iam.api.deps.get_iam_uow` isn't: every application-service method already manages
    its own `async with uow:` block (`application/services.py`), so wrapping it again here
    would call `__aenter__`/`__aexit__` twice on the same instance."""
    return container.resolve(FleetDeviceUnitOfWork)


def get_vehicle_service(
    container: Container = Depends(get_container),
) -> VehicleApplicationService:
    return container.resolve(VehicleApplicationService)


def get_device_service(
    container: Container = Depends(get_container),
) -> DeviceApplicationService:
    return container.resolve(DeviceApplicationService)
