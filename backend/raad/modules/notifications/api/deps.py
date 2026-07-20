"""FastAPI dependency wiring for `notifications` (Backend LLD §9.2/§16.2). Resolves the
DI-container-bound `NotificationsUnitOfWork` and `NotificationApplicationService` — the only
place this module's HTTP layer touches `core.di`. Mirrors `billing.api.deps` exactly.
"""

from __future__ import annotations

from fastapi import Depends

from raad.core.di.container import Container
from raad.interfaces.http.deps import get_container
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.services import NotificationApplicationService


def get_notifications_uow(
    container: Container = Depends(get_container),
) -> NotificationsUnitOfWork:
    """Resolves a fresh `NotificationsUnitOfWork` per call — **not** entered here, for the same
    reason `billing.api.deps.get_billing_uow` isn't: every `NotificationApplicationService`
    method already manages its own `async with uow:` block."""
    return container.resolve(NotificationsUnitOfWork)


def get_notification_service(
    container: Container = Depends(get_container),
) -> NotificationApplicationService:
    return container.resolve(NotificationApplicationService)
