"""Notifications application service (Backend LLD §4.1/§4.3). One `NotificationApplicationService`
class covering both aggregates (`Notification`, `DeviceToken`) — mirrors `billing`'s single-
service-per-phase convention (`BillingApplicationService`) rather than `transport_ops`'s
per-aggregate split, the more directly comparable precedent given both modules landed all their
aggregates in one phase.

**Ownership enforcement (not RBAC) is implemented directly here**, unlike the still-pending RBAC
permission matrix: `mark_notification_read`/`get_notification_by_id`/`revoke_device_token` all
compare the resource's own `recipient_user_id`/`user_id` field against the caller's
`actor.user_id` — a plain equality check against a field already on the aggregate, requiring no
RBAC matrix, no cross-module lookup, no `ScopeResolver`. A mismatch raises `NotFoundError` (see
`queries.py`'s `GetNotificationByIdQuery` docstring for the 404-over-403 reasoning).

**`create_notification` does not call `SubscriptionAccessPolicy`** — see `domain/policies.py`'s
module docstring for the full reasoning (mirrors `transport_ops`/`tracking`'s identical,
already-established deferral of that same policy's actual wiring).
"""

from __future__ import annotations

from raad.core.errors.exceptions import NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import CursorPage
from raad.core.time.clock import Clock
from raad.modules.notifications.application.commands import (
    CreateNotificationCommand,
    MarkNotificationReadCommand,
    RegisterDeviceTokenCommand,
    RevokeDeviceTokenCommand,
)
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.queries import (
    DeviceTokenDTO,
    GetNotificationByIdQuery,
    ListNotificationsForRecipientQuery,
    NotificationDTO,
    device_token_to_dto,
    notification_to_dto,
)
from raad.modules.notifications.application.validators import (
    ensure_device_token_exists,
    ensure_fcm_token_available,
    ensure_notification_exists,
)
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


class NotificationApplicationService:
    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    # --- Notification ------------------------------------------------------------------

    async def create_notification(
        self, command: CreateNotificationCommand, *, uow: NotificationsUnitOfWork
    ) -> NotificationDTO:
        """No approved HTTP route (`commands.py`'s own docstring) — the future Notification
        Worker's "write in-app" entry point."""
        async with uow:
            notification = Notification.create(
                id=NotificationId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                recipient_user_id=UserId(command.recipient_user_id),
                type=NotificationType(command.type),
                title=command.title,
                body=command.body,
                data=command.data,
                trip_id=TripId(command.trip_id) if command.trip_id is not None else None,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.notifications.add(notification)
            uow.record_events(notification.pull_domain_events())
            await uow.commit()
            return notification_to_dto(notification)

    async def mark_notification_read(
        self, command: MarkNotificationReadCommand, *, uow: NotificationsUnitOfWork
    ) -> NotificationDTO:
        async with uow:
            notification = await ensure_notification_exists(
                uow, NotificationId(command.notification_id)
            )
            if str(notification.recipient_user_id) != command.actor.user_id:
                raise NotFoundError(
                    f"Notification {command.notification_id} not found."
                )
            notification.mark_read(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(notification.pull_domain_events())
            await uow.commit()
            return notification_to_dto(notification)

    async def get_notification_by_id(
        self, query: GetNotificationByIdQuery, *, uow: NotificationsUnitOfWork
    ) -> NotificationDTO:
        async with uow:
            notification = await ensure_notification_exists(
                uow, NotificationId(query.notification_id)
            )
            if str(notification.recipient_user_id) != query.recipient_user_id:
                raise NotFoundError(f"Notification {query.notification_id} not found.")
            return notification_to_dto(notification)

    async def list_notifications_for_recipient(
        self, query: ListNotificationsForRecipientQuery, *, uow: NotificationsUnitOfWork
    ) -> CursorPage[NotificationDTO]:
        async with uow:
            page = await uow.notifications.list_for_recipient_page(
                UserId(query.recipient_user_id),
                query.cursor_request,
                filters=query.filters,
            )
            return CursorPage(
                data=[notification_to_dto(n) for n in page.data],
                limit=page.limit,
                next_cursor=page.next_cursor,
                has_more=page.has_more,
            )

    # --- DeviceToken ---------------------------------------------------------------------

    async def register_device_token(
        self, command: RegisterDeviceTokenCommand, *, uow: NotificationsUnitOfWork
    ) -> DeviceTokenDTO:
        async with uow:
            await ensure_fcm_token_available(uow, command.fcm_token)
            device_token = DeviceToken.register(
                id=DeviceTokenId(self._id_generator.new_id()),
                user_id=UserId(command.actor.user_id),
                fcm_token=FcmToken(command.fcm_token),
                platform=Platform(command.platform),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.device_tokens.add(device_token)
            uow.record_events(device_token.pull_domain_events())
            await uow.commit()
            return device_token_to_dto(device_token)

    async def revoke_device_token(
        self, command: RevokeDeviceTokenCommand, *, uow: NotificationsUnitOfWork
    ) -> DeviceTokenDTO:
        async with uow:
            device_token = await ensure_device_token_exists(
                uow, DeviceTokenId(command.device_token_id)
            )
            if str(device_token.user_id) != command.actor.user_id:
                raise NotFoundError(f"DeviceToken {command.device_token_id} not found.")
            device_token.revoke(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(device_token.pull_domain_events())
            await uow.commit()
            return device_token_to_dto(device_token)
