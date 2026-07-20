"""SQLAlchemy repository implementations for `notifications` (Backend LLD §7.1/§7.2; Database
Design §7.5-§7.6). Composes `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM ↔ domain conversion goes through `mappers.py` (§7.1's "aggregate-in/
aggregate-out" rule). Mirrors `billing.infra.repositories`'s identity-map/
`flush_tracked_changes` pattern exactly.

**`NotificationRepository.list_for_recipient`** is a direct `select()` filtered by
`recipient_user_id`, **not** `list_scoped`/`TenantRegionScope` — this is `GET /notifications`'s
documented "own in-app notifications" personal scoping (API Contracts §4.6), a different
dimension than every other module's tenant/org scoping, so `list_scoped`'s org-filter machinery
doesn't apply here at all (mirrors `SqlAlchemySubscriptionRepository.get_active_by_subscriber`'s
identical "direct select, not list_scoped" shape for a non-tenant-dimension finder).
**`list_all`** still exists for interface-shape uniformity but is not what any route calls.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.domain.entities import DeviceToken, Notification
from raad.modules.notifications.domain.repositories import (
    DeviceTokenRepository,
    NotificationRepository,
)
from raad.modules.notifications.domain.value_objects import (
    DeviceTokenId,
    NotificationId,
    UserId,
)
from raad.modules.notifications.infra.mappers import (
    device_token_to_model,
    model_to_device_token,
    model_to_notification,
    notification_to_model,
)
from raad.modules.notifications.infra.models import DeviceTokenModel, NotificationModel


class SqlAlchemyNotificationRepository(
    SqlAlchemyRepositoryBase[NotificationModel], NotificationRepository
):
    model = NotificationModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Notification, NotificationModel]] = {}

    async def get(self, notification_id: NotificationId) -> Notification | None:
        row = await self.get_by_id(str(notification_id))
        return self._track(row)

    def add(self, notification: Notification) -> None:
        model = notification_to_model(notification)
        super().add(model)
        self._tracked[str(notification.id)] = (notification, model)

    async def list_all(self) -> list[Notification]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_notification(row) for row in rows]

    async def list_for_recipient(self, recipient_user_id: UserId) -> list[Notification]:
        statement = select(NotificationModel).where(
            NotificationModel.recipient_user_id == str(recipient_user_id)
        )
        result = await self._session.execute(statement)
        return [self._track(row) for row in result.scalars().all()]

    def flush_tracked_changes(self) -> None:
        for notification, model in self._tracked.values():
            notification_to_model(notification, existing=model)

    def _track(self, row: NotificationModel | None) -> Notification | None:
        if row is None:
            return None
        notification = model_to_notification(row)
        self._tracked[row.id] = (notification, row)
        return notification


class SqlAlchemyDeviceTokenRepository(
    SqlAlchemyRepositoryBase[DeviceTokenModel], DeviceTokenRepository
):
    model = DeviceTokenModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[DeviceToken, DeviceTokenModel]] = {}

    async def get(self, device_token_id: DeviceTokenId) -> DeviceToken | None:
        row = await self.get_by_id(str(device_token_id))
        return self._track(row)

    def add(self, device_token: DeviceToken) -> None:
        model = device_token_to_model(device_token)
        super().add(model)
        self._tracked[str(device_token.id)] = (device_token, model)

    async def list_all(self) -> list[DeviceToken]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_device_token(row) for row in rows]

    async def get_by_token(self, fcm_token: str) -> DeviceToken | None:
        statement = select(DeviceTokenModel).where(DeviceTokenModel.fcm_token == fcm_token)
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def flush_tracked_changes(self) -> None:
        for device_token, model in self._tracked.values():
            device_token_to_model(device_token, existing=model)

    def _track(self, row: DeviceTokenModel | None) -> DeviceToken | None:
        if row is None:
            return None
        device_token = model_to_device_token(row)
        self._tracked[row.id] = (device_token, row)
        return device_token


class SqlAlchemyNotificationsUnitOfWork(SqlAlchemyUnitOfWork, NotificationsUnitOfWork):
    """Concrete `NotificationsUnitOfWork` (Backend LLD §8.2/§6.2). Constructs `notifications`'
    two repositories once the session is open, and re-syncs every tracked aggregate's in-place
    mutations onto its ORM row immediately before delegating to `SqlAlchemyUnitOfWork.commit()`
    — identical shape to `billing.infra.repositories.SqlAlchemyBillingUnitOfWork`.
    """

    notifications: SqlAlchemyNotificationRepository
    device_tokens: SqlAlchemyDeviceTokenRepository

    async def __aenter__(self) -> "SqlAlchemyNotificationsUnitOfWork":
        await super().__aenter__()
        self.notifications = SqlAlchemyNotificationRepository(self.session)
        self.device_tokens = SqlAlchemyDeviceTokenRepository(self.session)
        return self

    async def commit(self) -> None:
        self.notifications.flush_tracked_changes()
        self.device_tokens.flush_tracked_changes()
        await super().commit()
