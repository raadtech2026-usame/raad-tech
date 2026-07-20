"""ORM ↔ Domain mappers for `notifications` (Backend LLD §7.1 "aggregate-in/aggregate-out";
§17 `db`). Mappers own **every** conversion between SQLAlchemy rows and domain objects —
repositories (`repositories.py`) never construct or read ORM columns directly outside calling
these functions. Mirrors `billing.infra.mappers`'s `existing=` in-place-update pattern exactly,
including reusing the `_to_naive_utc` fix (Phase 12's live-verification finding: `SystemClock`
returns tz-aware `datetime`s, but every `DateTime(timezone=False)` column needs naive ones) for
every timestamp field here that comes from `Clock.now()`.
"""

from __future__ import annotations

from datetime import datetime

from raad.modules.notifications.domain.entities import DeviceToken, Notification
from raad.modules.notifications.domain.value_objects import (
    DeviceTokenId,
    FcmToken,
    NotificationId,
    NotificationType,
    OrganizationId,
    Platform,
    TripId,
    UserId,
)
from raad.modules.notifications.infra.models import DeviceTokenModel, NotificationModel


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """See `transport_ops.infra.mappers._to_naive_utc`'s own docstring for the live-DB finding
    that motivated this — identical fix, duplicated per module for the same reason every other
    per-module convention in this codebase is duplicated rather than shared
    (`.claude/rules/backend.md` #1)."""
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def notification_to_model(
    notification: Notification, *, existing: NotificationModel | None = None
) -> NotificationModel:
    model = existing if existing is not None else NotificationModel(id=str(notification.id))
    model.organization_id = str(notification.organization_id)
    model.recipient_user_id = str(notification.recipient_user_id)
    model.type = notification.type.value
    model.title = notification.title
    model.body = notification.body
    model.data_json = notification.data
    model.trip_id = str(notification.trip_id) if notification.trip_id is not None else None
    model.created_at = _to_naive_utc(notification.created_at)
    model.read_at = _to_naive_utc(notification.read_at)
    return model


def model_to_notification(model: NotificationModel) -> Notification:
    return Notification(
        id=NotificationId(model.id),
        organization_id=OrganizationId(model.organization_id),
        recipient_user_id=UserId(model.recipient_user_id),
        type=NotificationType(model.type),
        title=model.title,
        body=model.body,
        data=model.data_json,
        trip_id=TripId(model.trip_id) if model.trip_id is not None else None,
        created_at=model.created_at,
        read_at=model.read_at,
    )


def device_token_to_model(
    device_token: DeviceToken, *, existing: DeviceTokenModel | None = None
) -> DeviceTokenModel:
    model = existing if existing is not None else DeviceTokenModel(id=str(device_token.id))
    model.user_id = str(device_token.user_id)
    model.fcm_token = str(device_token.fcm_token)
    model.platform = device_token.platform.value
    model.created_at = _to_naive_utc(device_token.created_at)
    model.revoked_at = _to_naive_utc(device_token.revoked_at)
    return model


def model_to_device_token(model: DeviceTokenModel) -> DeviceToken:
    return DeviceToken(
        id=DeviceTokenId(model.id),
        user_id=UserId(model.user_id),
        fcm_token=FcmToken(model.fcm_token),
        platform=Platform(model.platform),
        created_at=model.created_at,
        revoked_at=model.revoked_at,
    )
