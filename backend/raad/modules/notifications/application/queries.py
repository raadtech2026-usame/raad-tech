"""Notifications application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite read-models).
DTOs are plain dataclasses — id fields become `str(vo)`, enum/status fields become `.value`,
timestamps stay native `datetime`, mirroring `billing.application.queries`'s exact convention.

**One DTO per aggregate, no Summary/Full split** — mirrors `billing.application.queries`'s
identical simplification: every field here is already a primitive/small value, no embedded
child collections.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from raad.modules.notifications.domain.entities import DeviceToken, Notification


@dataclass(frozen=True)
class GetNotificationByIdQuery:
    """`recipient_user_id` is the requesting caller's own id (router-populated from
    `principal.user_id`) — not a documented API Contracts field, but required to enforce the
    same "own" ownership scoping `GET /notifications` (list) already carries, for the uniform-
    CRUD `GET /notifications/{id}` addition this phase builds (see `routers.py`'s module
    docstring). A mismatch raises `NotFoundError`, not `AuthorizationError` — mirroring Backend
    LLD §14.3's "404-over-403... avoids confirming existence of out-of-scope data" reasoning,
    generalized here from its literal cross-tenant wording to this analogous cross-recipient
    case, flagged as this phase's own interpretive extension."""

    notification_id: str
    recipient_user_id: str


@dataclass(frozen=True)
class ListNotificationsForRecipientQuery:
    """No filter/pagination parameters — `core/pagination` is empty, the same pre-existing,
    module-wide gap `transport_ops.application.queries.ListStudentsQuery` already flags."""

    recipient_user_id: str


@dataclass(frozen=True)
class NotificationDTO:
    id: str
    organization_id: str
    recipient_user_id: str
    type: str
    title: str
    body: str
    data: dict[str, Any] | None
    trip_id: str | None
    status: str
    created_at: datetime
    read_at: datetime | None


def notification_to_dto(notification: Notification) -> NotificationDTO:
    return NotificationDTO(
        id=str(notification.id),
        organization_id=str(notification.organization_id),
        recipient_user_id=str(notification.recipient_user_id),
        type=notification.type.value,
        title=notification.title,
        body=notification.body,
        data=notification.data,
        trip_id=str(notification.trip_id) if notification.trip_id is not None else None,
        status=notification.status.value,
        created_at=notification.created_at,
        read_at=notification.read_at,
    )


@dataclass(frozen=True)
class DeviceTokenDTO:
    id: str
    user_id: str
    fcm_token: str
    platform: str
    created_at: datetime
    revoked_at: datetime | None


def device_token_to_dto(device_token: DeviceToken) -> DeviceTokenDTO:
    return DeviceTokenDTO(
        id=str(device_token.id),
        user_id=str(device_token.user_id),
        fcm_token=str(device_token.fcm_token),
        platform=device_token.platform.value,
        created_at=device_token.created_at,
        revoked_at=device_token.revoked_at,
    )
