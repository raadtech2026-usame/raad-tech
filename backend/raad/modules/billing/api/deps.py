"""FastAPI dependency wiring for `billing` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `BillingUnitOfWork` and `BillingApplicationService` — the only place this
module's HTTP layer touches `core.di`. Mirrors `transport_ops.api.deps` exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.core.tenancy.scope import TenantRegionScope
from raad.interfaces.http.deps import get_container, get_scope
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService


def get_billing_uow(
    container: Container = Depends(get_container),
    scope: TenantRegionScope = Depends(get_scope),
) -> BillingUnitOfWork:
    """Resolves a fresh `BillingUnitOfWork` per call — **not** entered here, for the same reason
    `transport_ops.api.deps.get_transport_ops_uow` isn't: every `BillingApplicationService`
    method already manages its own `async with uow:` block(s).

    **ADR-0021**: sets the caller's resolved `TenantRegionScope` on the UoW before it's
    entered — every repository `SqlAlchemyBillingUnitOfWork.__aenter__` constructs picks it up
    automatically, mirroring `transport_ops.api.deps.get_transport_ops_uow` exactly. This is the
    fix for the audit's highest-severity finding: `GET /billing/subscriptions`/
    `GET /billing/invoices` previously returned every organization's financial data to any
    caller holding the underlying (list-only) permission."""
    uow = container.resolve(BillingUnitOfWork)
    uow.scope = scope
    return uow


def get_billing_service(
    container: Container = Depends(get_container),
) -> BillingApplicationService:
    return container.resolve(BillingApplicationService)
