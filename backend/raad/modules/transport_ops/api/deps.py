"""FastAPI dependency wiring for `transport_ops` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `TransportOpsUnitOfWork` and `StudentApplicationService` — the only place
this module's HTTP layer touches `core.di`; routers never import the container directly beyond
this file, and never construct a repository or touch SQLAlchemy. Mirrors
`organization.api.deps`/`fleet_device.api.deps`/`tracking.api.deps` exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.interfaces.http.deps import get_container
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.services import StudentApplicationService


def get_transport_ops_uow(
    container: Container = Depends(get_container),
) -> TransportOpsUnitOfWork:
    """Resolves a fresh `TransportOpsUnitOfWork` per call — **not** entered here, for the same
    reason `organization.api.deps.get_organization_uow` isn't: every
    `StudentApplicationService` method already manages its own `async with uow:` block
    (`application/services.py`), so wrapping it again here would call `__aenter__`/`__aexit__`
    twice on the same instance."""
    return container.resolve(TransportOpsUnitOfWork)


def get_student_service(
    container: Container = Depends(get_container),
) -> StudentApplicationService:
    return container.resolve(StudentApplicationService)
