"""FastAPI dependency wiring for `organization` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `OrganizationUnitOfWork` and application services — the only place this
module's HTTP layer touches `core.di`; routers never import the container directly beyond
this file, and never construct a repository or touch SQLAlchemy. Mirrors `iam.api.deps`
exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.interfaces.http.deps import get_container
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.services import (
    OrganizationApplicationService,
    RegionApplicationService,
)


def get_organization_uow(
    container: Container = Depends(get_container),
) -> OrganizationUnitOfWork:
    """Resolves a fresh `OrganizationUnitOfWork` per call — **not** entered here, for the
    same reason `iam.api.deps.get_iam_uow` isn't: every `OrganizationApplicationService`/
    `RegionApplicationService` method already manages its own `async with uow:` block
    (`application/services.py`), so wrapping it again here would call `__aenter__`/
    `__aexit__` twice on the same instance."""
    return container.resolve(OrganizationUnitOfWork)


def get_organization_service(
    container: Container = Depends(get_container),
) -> OrganizationApplicationService:
    return container.resolve(OrganizationApplicationService)


def get_region_service(
    container: Container = Depends(get_container),
) -> RegionApplicationService:
    return container.resolve(RegionApplicationService)
