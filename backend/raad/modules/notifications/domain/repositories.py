"""Repository interfaces for the `notifications` module (Backend LLD §5.1/§7.1/§7.2).
Framework-free — no SQLAlchemy/FastAPI/Pydantic. No LLD-given contract skeleton exists for
either aggregate (unlike `TripRepository`) — each mirrors the closest already-completed
precedent in `billing.domain.repositories`.

`NotificationRepository.list_for_recipient` backs `GET /notifications`'s documented "own in-app
notifications" scoping (API Contracts §4.6) — filtering by `recipient_user_id`, not by
`organization_id`/`TenantRegionScope` (a personal list, not a tenant-scoped admin list, unlike
every list endpoint in every other module so far). `DeviceTokenRepository.get_by_token` backs
the documented `ux_device_tokens__token` uniqueness (Database Design §7.6) as an application-
level defense-in-depth check, mirroring `PaymentRepository.get_by_idempotency_key`'s identical
shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

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
        """Backs `GET /notifications` (API Contracts §4.6: "own in-app notifications
        (paginated)"). No pagination parameters — `core/pagination` is empty, the same
        pre-existing, module-wide gap `transport_ops.application.queries.ListStudentsQuery`
        already flags, not a new one."""
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
