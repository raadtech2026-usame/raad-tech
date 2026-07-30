"""FastAPI dependency wiring for `organization` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `OrganizationUnitOfWork` and application services — the only place this
module's HTTP layer touches `core.di`; routers never import the container directly beyond
this file, and never construct a repository or touch SQLAlchemy. Mirrors `iam.api.deps`
exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.core.tenancy.scope import TenantRegionScope
from raad.interfaces.http.deps import get_container, get_scope
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.services import (
    OrganizationApplicationService,
    RegionApplicationService,
)


def get_organization_uow(
    container: Container = Depends(get_container),
    scope: TenantRegionScope = Depends(get_scope),
) -> OrganizationUnitOfWork:
    """Resolves a fresh `OrganizationUnitOfWork` per call — **not** entered here, for the
    same reason `iam.api.deps.get_iam_uow` isn't: every `OrganizationApplicationService`/
    `RegionApplicationService` method already manages its own `async with uow:` block
    (`application/services.py`), so wrapping it again here would call `__aenter__`/
    `__aexit__` twice on the same instance.

    **ADR-0021**: sets the caller's resolved `TenantRegionScope` on the UoW before it's
    entered — every repository `SqlAlchemyOrganizationUnitOfWork.__aenter__` constructs picks
    it up automatically. Does not affect `OrganizationScopeResolver`'s own internal UoW
    construction (a separate `uow_factory`, bound in `core/di/bootstrap.py`, outside FastAPI's
    dependency graph) — that one stays unrestricted by design, since computing scope requires
    seeing every organization/assignment row, not a caller's own already-resolved scope."""
    uow = container.resolve(OrganizationUnitOfWork)
    uow.scope = scope
    return uow


def get_organization_service(
    container: Container = Depends(get_container),
) -> OrganizationApplicationService:
    return container.resolve(OrganizationApplicationService)


def get_region_service(
    container: Container = Depends(get_container),
) -> RegionApplicationService:
    return container.resolve(RegionApplicationService)
