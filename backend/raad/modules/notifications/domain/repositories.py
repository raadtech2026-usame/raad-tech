"""Repository interfaces for the `notifications` module (Backend LLD §5.1/§7.1/§7.2).
Framework-free — no SQLAlchemy/FastAPI/Pydantic. No LLD-given contract skeleton exists for
either aggregate (unlike `TripRepository`) — each mirrors the closest already-completed
precedent in `billing.domain.repositories`.

`NotificationRepository.list_for_recipient` backs the personal "own in-app notifications"
scoping (API Contracts §4.6) — filtering by `recipient_user_id`, not by `organization_id`/
`TenantRegionScope` (a personal list, not a tenant-scoped admin list, unlike every list endpoint
in every other module so far). It is unpaginated and kept only as the pre-existing, still-valid
finder for any non-HTTP caller that wants the full set; `GET /notifications` itself now calls
`list_for_recipient_page` (below), added in the Pagination/Filtering/Sorting phase once
`core/pagination`/`SqlAlchemyRepositoryBase.list_cursor_page` landed. `DeviceTokenRepository.
get_by_token` backs the documented `ux_device_tokens__token` uniqueness (Database Design §7.6)
as an application-level defense-in-depth check, mirroring `PaymentRepository.
get_by_idempotency_key`'s identical shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.pagination import CursorPage, CursorPageRequest, FilterCondition
from raad.modules.notifications.domain.entities import DeviceToken, Notification
from raad.modules.notifications.domain.value_objects import (
    DeviceTokenId,
    NotificationId,
    UserId,
)


class NotificationRepository(ABC):
    @abstractmethod
    async def get(self, notification_id: NotificationId) -> Notification | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, notification: Notification) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Notification]:
        """Uniform-shape method every repository in this codebase provides — not the method
        `GET /notifications` actually calls (see `list_for_recipient` below)."""
        raise NotImplementedError

    @abstractmethod
    async def list_for_recipient(self, recipient_user_id: UserId) -> list[Notification]:
        """Unpaginated finder over the caller's own notifications — kept for any non-HTTP
        caller that wants the full set. `GET /notifications` itself calls
        `list_for_recipient_page` instead (below)."""
        raise NotImplementedError

    @abstractmethod
    async def list_for_recipient_page(
        self,
        recipient_user_id: UserId,
        cursor_request: CursorPageRequest,
        *,
        filters: list[FilterCondition],
    ) -> CursorPage[Notification]:
        """Backs `GET /notifications` (API Contracts §4.6: "own in-app notifications
        (paginated)") — cursor pagination (§7: "stable under inserts, efficient on time-ordered
        data like positions/notifications") over `created_at`, most-recent-first. No document
        specifies ordering explicitly; newest-first is this method's own deliberate,
        interpretive choice, matching the standard notification-inbox convention. The caller's
        own `recipient_user_id` scoping is enforced unconditionally by the implementation, not
        left to `filters` — a client-supplied `filters` list can only narrow the result set
        further, never widen or escape it (API Contracts §8)."""
        raise NotImplementedError


class DeviceTokenRepository(ABC):
    @abstractmethod
    async def get(self, device_token_id: DeviceTokenId) -> DeviceToken | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, device_token: DeviceToken) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[DeviceToken]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_token(self, fcm_token: str) -> DeviceToken | None:
        """Backs the documented `ux_device_tokens__token` global uniqueness (Database Design
        §7.6) — a direct `select()`, mirroring `PaymentRepository.get_by_idempotency_key`'s
        identical shape for an analogous non-`get_by_id` finder."""
        raise NotImplementedError
