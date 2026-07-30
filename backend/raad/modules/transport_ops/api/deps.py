"""FastAPI dependency wiring for `transport_ops` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `TransportOpsUnitOfWork` and `StudentApplicationService` — the only place
this module's HTTP layer touches `core.di`; routers never import the container directly beyond
this file, and never construct a repository or touch SQLAlchemy. Mirrors
`organization.api.deps`/`fleet_device.api.deps`/`tracking.api.deps` exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.core.tenancy.scope import TenantRegionScope
from raad.interfaces.http.deps import get_container, get_scope
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.services import (
    DriverApplicationService,
    ParentApplicationService,
    RouteApplicationService,
    StudentApplicationService,
    StudentAssignmentApplicationService,
    StudentParentApplicationService,
    TripApplicationService,
)


def get_transport_ops_uow(
    container: Container = Depends(get_container),
    scope: TenantRegionScope = Depends(get_scope),
) -> TransportOpsUnitOfWork:
    """Resolves a fresh `TransportOpsUnitOfWork` per call — **not** entered here, for the same
    reason `organization.api.deps.get_organization_uow` isn't: every
    `StudentApplicationService`/`ParentApplicationService` method already manages its own
    `async with uow:` block (`application/services.py`), so wrapping it again here would call
    `__aenter__`/`__aexit__` twice on the same instance.

    **ADR-0021**: sets the caller's resolved `TenantRegionScope` on the UoW before it's
    entered — every repository `SqlAlchemyTransportOpsUnitOfWork.__aenter__` constructs picks
    it up automatically, mirroring `fleet_device.api.deps.get_fleet_device_uow`/
    `organization.api.deps.get_organization_uow` exactly."""
    uow = container.resolve(TransportOpsUnitOfWork)
    uow.scope = scope
    return uow


def get_student_service(
    container: Container = Depends(get_container),
) -> StudentApplicationService:
    return container.resolve(StudentApplicationService)


def get_parent_service(
    container: Container = Depends(get_container),
) -> ParentApplicationService:
    return container.resolve(ParentApplicationService)


def get_student_parent_service(
    container: Container = Depends(get_container),
) -> StudentParentApplicationService:
    return container.resolve(StudentParentApplicationService)


def get_driver_service(
    container: Container = Depends(get_container),
) -> DriverApplicationService:
    return container.resolve(DriverApplicationService)


def get_route_service(
    container: Container = Depends(get_container),
) -> RouteApplicationService:
    return container.resolve(RouteApplicationService)


def get_trip_service(
    container: Container = Depends(get_container),
) -> TripApplicationService:
    return container.resolve(TripApplicationService)


def get_student_assignment_service(
    container: Container = Depends(get_container),
) -> StudentAssignmentApplicationService:
    return container.resolve(StudentAssignmentApplicationService)
