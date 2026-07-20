"""FastAPI dependency wiring for `platform_audit` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `PlatformAuditUnitOfWork` and `PlatformAuditApplicationService`. Mirrors
`billing.api.deps` exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.interfaces.http.deps import get_container
from raad.modules.platform_audit.application.ports import PlatformAuditUnitOfWork
from raad.modules.platform_audit.application.services import PlatformAuditApplicationService


def get_platform_audit_uow(
    container: Container = Depends(get_container),
) -> PlatformAuditUnitOfWork:
    return container.resolve(PlatformAuditUnitOfWork)


def get_platform_audit_service(
    container: Container = Depends(get_container),
) -> PlatformAuditApplicationService:
    return container.resolve(PlatformAuditApplicationService)
