"""Cross-cutting application-layer validators for `notifications` (Backend LLD §15.2:
"application layer validates cross-aggregate/business rules"), mirroring
`billing.application.validators`'s exact shape and existence-check pattern (new file, no
scaffold existed, matching `billing`'s own Phase 15 precedent).

`ensure_fcm_token_available` backs the documented `ux_device_tokens__token` global uniqueness
(Database Design §7.6) as a typed application-layer check, defense-in-depth over the DB
constraint — mirroring `fleet_device.application.validators.ensure_terminal_id_available`'s
identical shape. Unlike `billing`'s `idempotency_key` (which has "return the original" reuse
semantics), a duplicate `fcm_token` here has no documented reuse behavior, so this *does* raise
`ConflictError` rather than silently returning the existing row.
"""

from __future__ import annotations

from raad.core.errors.exceptions import ConflictError, NotFoundError
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.domain.entities import DeviceToken, Notification
from raad.modules.notifications.domain.value_objects import DeviceTokenId, NotificationId


async def ensure_notification_exists(
    uow: NotificationsUnitOfWork, notification_id: NotificationId
) -> Notification:
    notification = await uow.notifications.get(notification_id)
    if notification is None:
        raise NotFoundError(f"Notification {notification_id} not found.")
    return notification


async def ensure_device_token_exists(
    uow: NotificationsUnitOfWork, device_token_id: DeviceTokenId
) -> DeviceToken:
    device_token = await uow.device_tokens.get(device_token_id)
    if device_token is None:
        raise NotFoundError(f"DeviceToken {device_token_id} not found.")
    return device_token


async def ensure_fcm_token_available(
    uow: NotificationsUnitOfWork, fcm_token: str
) -> None:
    existing = await uow.device_tokens.get_by_token(fcm_token)
    if existing is not None:
        raise ConflictError("This FCM token is already registered.")
