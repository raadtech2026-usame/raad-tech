"""FastAPI dependency wiring for `school_erp` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `SchoolErpUnitOfWork` and `SchoolErpApplicationService` — the only place this
module's HTTP layer touches `core.di`. Mirrors `billing.api.deps` exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.core.tenancy.scope import TenantRegionScope
from raad.interfaces.http.deps import get_container, get_scope
from raad.modules.school_erp.application.ports import SchoolErpUnitOfWork
from raad.modules.school_erp.application.services import (
    ParentFinanceApplicationService,
    SchoolErpApplicationService,
)


def get_school_erp_uow(
    container: Container = Depends(get_container),
    scope: TenantRegionScope = Depends(get_scope),
) -> SchoolErpUnitOfWork:
    """Resolves a fresh `SchoolErpUnitOfWork` per call — **not** entered here, for the same
    reason `billing.api.deps.get_billing_uow` isn't: every `SchoolErpApplicationService` method
    already manages its own `async with uow:` block.

    **ADR-0021**: sets the caller's resolved `TenantRegionScope` on the UoW before it is entered,
    so every repository `SqlAlchemySchoolErpUnitOfWork.__aenter__` constructs picks it up
    automatically. Unlike `billing.plans`, every table in this module carries `organization_id`,
    so that scope is genuinely load-bearing on every read here — it is what stops one school's
    student invoices, payments and ledger from ever being visible to another.
    """
    uow = container.resolve(SchoolErpUnitOfWork)
    uow.scope = scope
    return uow


def get_school_erp_service(
    container: Container = Depends(get_container),
) -> SchoolErpApplicationService:
    return container.resolve(SchoolErpApplicationService)


def get_parent_finance_service(
    container: Container = Depends(get_container),
) -> ParentFinanceApplicationService:
    """2026-09-10 explicit user directive. `ParentFinanceApplicationService` also needs a
    `TransportOpsUnitOfWork` — its routes (`api/routers.py`) resolve that one directly via
    `transport_ops.api.deps.get_transport_ops_uow`, mirroring `iam`'s `/me` routes exactly (see
    that service's own docstring)."""
    return container.resolve(ParentFinanceApplicationService)
