"""SQLAlchemy repository implementations for `notifications` (Backend LLD §7.1/§7.2; Database
Design §7.5-§7.6). Composes `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM ↔ domain conversion goes through `mappers.py` (§7.1's "aggregate-in/
aggregate-out" rule). Mirrors `billing.infra.repositories`'s identity-map/
`flush_tracked_changes` pattern exactly.

**`NotificationRepository.list_for_recipient`** is a direct `select()` filtered by
`recipient_user_id`, **not** `list_scoped`/`TenantRegionScope` — this is the personal "own
in-app notifications" scoping (API Contracts §4.6), a different dimension than every other
module's tenant/org scoping, so `list_scoped`'s org-filter machinery doesn't apply here at all
(mirrors `SqlAlchemySubscriptionRepository.get_active_by_subscriber`'s identical "direct select,
not list_scoped" shape for a non-tenant-dimension finder). It is kept unpaginated, alongside the
new `list_for_recipient_page` below, which is what `GET /notifications` actually calls as of the
Pagination/Filtering/Sorting phase. **`list_all`** still exists for interface-shape uniformity
but is not what any route calls.

**`list_for_recipient_page`** composes `SqlAlchemyRepositoryBase.list_cursor_page` with an
unconditional `TenantRegionScope(organization_ids=None)` (this is personal, not tenant,
scoping — see above) and cursor over `created_at`, `descending=True` (most-recent-first, this
method's own flagged interpretive choice — no document specifies ordering). The caller's own
`recipient_user_id` is injected as a mandatory `FilterCondition`, ANDed ahead of any
client-supplied `filters` — since `_apply_filters` requires every condition's `field` to be
whitelisted, `recipient_user_id` is deliberately included in `filterable_fields` too, but a
client-supplied `filters` list can only narrow the result set further (e.g. by `type`/
`trip_id`), never widen or escape the caller's own scope (API Contracts §8's "filters can never
widen scope, only narrow") — the same safe pattern `tracking`'s own cursor-paginated
`trip_id`-scoped listing uses.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import FilterField, SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.pagination import CursorPage, CursorPageRequest, FilterCondition
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

    #: `recipient_user_id` IS whitelisted here even though it is never client-supplied through
    #: `GET /notifications` — the router always populates it from `principal.user_id` — so that
    #: `list_for_recipient_page`'s own mandatory `FilterCondition` (see module docstring) passes
    #: `_apply_filters`'s whitelist check like every other condition.
    #:
    #: **`status` is deliberately NOT whitelisted** — `Notification.status` is a domain-derived
    #: `@property` computed from `read_at` (`domain/entities.py`), never a persisted
    #: `NotificationModel` column (Database Design §7.5 has no `status` column at all). Whitelisting
    #: a name `getattr(self.model, ...)` can't resolve would turn every `filter[status]=...`
    #: request into an unhandled `AttributeError` (500) instead of the clean `ValidationError`
    #: every other unwhitelisted field gets — so it is excluded here rather than shipped broken.
    #: A future phase could reintroduce it by adding a computed/hybrid `status` expression to
    #: `NotificationModel`, which this phase does not attempt.
    filterable_fields = {
        "type": FilterField(column="type"),
        "trip_id": FilterField(column="trip_id"),
        "recipient_user_id": FilterField(column="recipient_user_id"),
    }

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

    async def list_for_recipient_page(
        self,
        recipient_user_id: UserId,
        cursor_request: CursorPageRequest,
        *,
        filters: list[FilterCondition],
    ) -> CursorPage[Notification]:
        """Cursor pagination over `created_at`, `descending=True` (most-recent-first) — see
        module docstring: no document specifies ordering explicitly, so newest-first is this
        method's own deliberate, interpretive choice (the standard notification-inbox
        convention). The caller's own `recipient_user_id` is injected as a mandatory
        `FilterCondition`, ANDed ahead of anything the caller passed — narrowing-only, never
        widening (API Contracts §8)."""
        combined_filters = [
            FilterCondition(field="recipient_user_id", op="eq", value=str(recipient_user_id)),
            *filters,
        ]
        raw_page = await super().list_cursor_page(
            TenantRegionScope(organization_ids=None),
            cursor_request,
            cursor_column="created_at",
            descending=True,
            filters=combined_filters,
        )
        return CursorPage(
            data=[self._track(row) for row in raw_page.data],
            limit=raw_page.limit,
            next_cursor=raw_page.next_cursor,
            has_more=raw_page.has_more,
        )

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
