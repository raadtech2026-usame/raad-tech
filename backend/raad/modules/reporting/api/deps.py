"""FastAPI dependency wiring for `reporting` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `ReportingUnitOfWork` and `ReportingApplicationService` — the only place
this module's HTTP layer touches `core.di`. Mirrors `billing.api.deps`/`notifications.api.deps`
exactly. New file — no scaffold existed for this module's `api/deps.py`, matching
`application/validators.py`'s identical "new file this phase" precedent.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.interfaces.http.deps import get_container
from raad.modules.reporting.application.ports import ReportingUnitOfWork
from raad.modules.reporting.application.services import ReportingApplicationService


def get_reporting_uow(
    container: Container = Depends(get_container),
) -> ReportingUnitOfWork:
    """Resolves a fresh `ReportingUnitOfWork` per call — **not** entered here, for the same
    reason `billing.api.deps.get_billing_uow` isn't: every `ReportingApplicationService` method
    already manages its own `async with uow:` block."""
    return container.resolve(ReportingUnitOfWork)


def get_reporting_service(
    container: Container = Depends(get_container),
) -> ReportingApplicationService:
    return container.resolve(ReportingApplicationService)
