"""Notifications entities (Backend LLD §5.1/§5.2; Database Design §7.5-§7.6). Framework-free —
no SQLAlchemy/Pydantic/FastAPI, no I/O. Behavior methods mutate state, enforce invariants, and
buffer the resulting `DomainEvent`s, matching every other module's exact shape (`Clock` passed
in, never called internally).

Two aggregates this phase: `Notification` (§7.5, the in-app store — D2) and `DeviceToken`
(§7.6, FCM registration). `notification_preferences` (§7.7) is **not built** — no document
gives it an HTTP route, and the task's own scope names only "Notification aggregate" — see
`value_objects.py`'s module docstring and this module's `__init__.py`-level summary for the
full gap, mirroring `transport_ops`'s identical `trip_students`-deferred precedent.

**Neither aggregate resolves or applies `SubscriptionAccessPolicy` (CR-1) itself** — see
`domain/policies.py`'s docstring for the full reasoning (mirrors `transport_ops.domain.policies`/
`tracking.domain.policies`'s identical, already-established "not our enforcement point yet"
posture). `Notification.create()` is an unconditional persist; the *decision* of whether to
call it for a given (event, recipient) pair belongs to the not-yet-built Notification Worker
(event consumption/broker wiring, explicitly out of this phase's scope).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from raad.core.errors.exceptions import DomainError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.notifications.domain import events as notification_events
from raad.modules.notifications.domain.value_objects import (
    DeviceTokenId,
    FcmToken,
    NotificationId,
    NotificationStatus,
    NotificationType,
    OrganizationId,
    Platform,
    TripId,
    UserId,
)

_TITLE_MAX_LENGTH = 160  # Database Design §7.5: title VARCHAR(160)
_BODY_MAX_LENGTH = 500  # §7.5: body VARCHAR(500)


def _validate_title(title: str) -> None:
    if not title:
        raise DomainError("Notification title must not be empty")
    if len(title) > _TITLE_MAX_LENGTH:
        raise DomainError(
            f"Notification title must be at most {_TITLE_MAX_LENGTH} characters: {len(title)}"
        )


def _validate_body(body: str) -> None:
    if not body:
        raise DomainError("Notification body must not be empty")
    if len(body) > _BODY_MAX_LENGTH:
        raise DomainError(
            f"Notification body must be at most {_BODY_MAX_LENGTH} characters: {len(body)}"
        )


class _AggregateRoot:
    """Shared "raise and buffer domain events" mechanics (LLD §8.1), duplicated per module
    deliberately — `.claude/rules/backend.md` #1 forbids one module reaching into another's
    internals, and no approved doc calls for a shared-kernel package (identical to every other
    module's own `_AggregateRoot` copy)."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


class Notification(_AggregateRoot):
    """`notifications` (Database Design §7.5): the durable in-app store (D2) — "in-app store is
    the durable record" (Backend LLD §11.2's Notification Worker row). No `+audit` line in §7.5
    (its own `created_at`/`read_at` pair already serves the purpose) — mirrors `Payment`'s
    identical `UlidPrimaryKeyMixin`-only ORM treatment (`infra/models.py`'s own docstring).
    """

    def __init__(
        self,
        *,
        id: NotificationId,
        organization_id: OrganizationId,
        recipient_user_id: UserId,
        type: NotificationType,
        title: str,
        body: str,
        data: dict[str, Any] | None,
        trip_id: TripId | None,
        created_at: datetime,
        read_at: datetime | None,
    ) -> None:
        super().__init__()
        _validate_title(title)
        _validate_body(body)
        self.id = id
        self.organization_id = organization_id
        self.recipient_user_id = recipient_user_id
        self.type = type
        self.title = title
        self.body = body
        self.data = data
        self.trip_id = trip_id
        self.created_at = created_at
        self.read_at = read_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Notification) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def status(self) -> NotificationStatus:
        """Derived from `read_at` — see `value_objects.py`'s module docstring: no `status`
        column exists in Database Design §7.5."""
        return NotificationStatus.READ if self.read_at is not None else NotificationStatus.UNREAD

    @classmethod
    def create(
        cls,
        *,
        id: NotificationId,
        organization_id: OrganizationId,
        recipient_user_id: UserId,
        type: NotificationType,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        trip_id: TripId | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Notification":
        """The "write in-app" half of the Notification Worker's documented responsibility
        (Backend LLD §11.2) — reachable at the application layer only this phase, no HTTP
        route documents a generic `POST /notifications` (API Contracts §4.6 lists no such
        row); the FCM-push half and the CR-1 withholding decision both belong to the caller
        (the not-yet-built worker), not to this factory. `NotificationCreated` has no approved
        document naming it — this phase's own flagged choice, matching every prior phase's
        identical treatment of an unnamed creation event."""
        now = clock.now()
        notification = cls(
            id=id,
            organization_id=organization_id,
            recipient_user_id=recipient_user_id,
            type=type,
            title=title,
            body=body,
            data=data,
            trip_id=trip_id,
            created_at=now,
            read_at=None,
        )
        notification._record(
            notification_events.notification_created(
                notification_id=str(id),
                organization_id=str(organization_id),
                recipient_user_id=str(recipient_user_id),
                type=type.value,
                trip_id=str(trip_id) if trip_id is not None else None,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return notification

    def mark_read(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Backs `POST /notifications/{id}/read` (API Contracts §4.6). Idempotent same-state
        no-op, mirroring every other status-transition method in this codebase."""
        if self.read_at is not None:
            return
        self.read_at = clock.now()
        self._record(
            notification_events.notification_read(
                notification_id=str(self.id),
                organization_id=str(self.organization_id),
                recipient_user_id=str(self.recipient_user_id),
                occurred_at=self.read_at,
                actor_id=actor_id,
            )
        )


class DeviceToken(_AggregateRoot):
    """`device_tokens` (Database Design §7.6): an FCM push-registration token, owned by exactly
    one `iam.User` (cross-module, opaque — `value_objects.py`'s module docstring). No `+audit`
    line in §7.6 either — same `UlidPrimaryKeyMixin`-only treatment as `Notification`/`Payment`.
    """

    def __init__(
        self,
        *,
        id: DeviceTokenId,
        user_id: UserId,
        fcm_token: FcmToken,
        platform: Platform,
        created_at: datetime,
        revoked_at: datetime | None,
    ) -> None:
        super().__init__()
        self.id = id
        self.user_id = user_id
        self.fcm_token = fcm_token
        self.platform = platform
        self.created_at = created_at
        self.revoked_at = revoked_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, DeviceToken) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    @classmethod
    def register(
        cls,
        *,
        id: DeviceTokenId,
        user_id: UserId,
        fcm_token: FcmToken,
        platform: Platform,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "DeviceToken":
        """Backs `POST /notifications/tokens` (API Contracts §4.6, "Parent/Driver"). No
        approved document names a creation event — this phase's own flagged choice."""
        now = clock.now()
        token = cls(
            id=id,
            user_id=user_id,
            fcm_token=fcm_token,
            platform=platform,
            created_at=now,
            revoked_at=None,
        )
        token._record(
            notification_events.device_token_registered(
                device_token_id=str(id),
                user_id=str(user_id),
                platform=platform.value,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return token

    def revoke(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Backs `DELETE /notifications/tokens/{id}` (API Contracts §4.6, "owner") — a soft
        revoke (`revoked_at` set), not a row deletion, since Database Design §7.6 gives this
        table a `revoked_at` column specifically for this purpose (preserving the audit trail
        a hard delete would lose). Idempotent same-state no-op."""
        if self.revoked_at is not None:
            return
        self.revoked_at = clock.now()
        self._record(
            notification_events.device_token_revoked(
                device_token_id=str(self.id),
                user_id=str(self.user_id),
                occurred_at=self.revoked_at,
                actor_id=actor_id,
            )
        )
