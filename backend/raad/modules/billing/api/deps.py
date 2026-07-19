"""FastAPI dependency wiring for `billing` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `BillingUnitOfWork` and `BillingApplicationService` — the only place this
module's HTTP layer touches `core.di`. Mirrors `transport_ops.api.deps` exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.interfaces.http.deps import get_container
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService


def get_billing_uow(
    container: Container = Depends(get_container),
) -> BillingUnitOfWork:
    """Resolves a fresh `BillingUnitOfWork` per call — **not** entered here, for the same reason
    `transport_ops.api.deps.get_transport_ops_uow` isn't: every `BillingApplicationService`
    method already manages its own `async with uow:` block(s)."""
    return container.resolve(BillingUnitOfWork)


def get_billing_service(
    container: Container = Depends(get_container),
) -> BillingApplicationService:
    return container.resolve(BillingApplicationService)
