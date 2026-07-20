"""Application-layer tests for `notifications`' `NotificationApplicationService` (Phase 16).
Stdlib `unittest` — no `pytest` (not an approved dependency), mirroring
`test_billing_application.py`'s exact structure. Uses in-memory fakes for both repositories
bundled onto one fake `NotificationsUnitOfWork` — no SQLAlchemy, no FastAPI, no real database.

Covers: `create_notification` (application-layer-only path), `mark_notification_read`'s
ownership enforcement (`NotFoundError` on a non-recipient caller, matching the documented
404-over-403 posture), `get_notification_by_id`'s identical ownership scoping,
`list_notifications_for_recipient`'s personal (not tenant) scoping, `register_device_token`'s
`ux_device_tokens__token` defense-in-depth (`ConflictError` on a duplicate token), and
`revoke_device_token`'s ownership enforcement.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import ConflictError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.notifications.application.commands import (
    CreateNotificationCommand,
    MarkNotificationReadCommand,
    RegisterDeviceTokenCommand,
    RevokeDeviceTokenCommand,
)
from raad.modules.notifications.application.ports import NotificationsUnitOfWork
from raad.modules.notifications.application.queries import (
    GetNotificationByIdQuery,
    ListNotificationsForRecipientQuery,
)
from raad.modules.notifications.application.services import NotificationApplicationService
from raad.modules.notifications.domain.entities import DeviceToken, Notification
from raad.modules.notifications.domain.repositories import (
    DeviceTokenRepository,
    NotificationRepository,
)
from raad.modules.notifications.domain.value_objects import DeviceTokenId, NotificationId, UserId

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
RECIPIENT_USER_ID = "recipient-ref-001"
OTHER_USER_ID = "other-user-ref-002"
NON_EXISTENT_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc))


class SequentialIdGenerator(IdGenerator):
    """26-char, valid-Crockford-Base32 ULID-shaped ids, unique per call — mirrors
    `test_billing_application.py`'s identical helper exactly."""

    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"  # 20 chars

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


def make_actor(user_id: str = RECIPIENT_USER_ID) -> Principal:
    return Principal(user_id=user_id, role=Role.PARENT, org_id=VALID_ORG_ULID)


class InMemoryNotificationRepository(NotificationRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Notification] = {}

    async def get(self, notification_id: NotificationId) -> Notification | None:
        return self.by_id.get(str(notification_id))

    def add(self, notification: Notification) -> None:
        self.by_id[str(notification.id)] = notification

    async def list_all(self) -> list[Notification]:
        return list(self.by_id.values())

    async def list_for_recipient(self, recipient_user_id: UserId) -> list[Notification]:
        return [
            n
            for n in self.by_id.values()
            if str(n.recipient_user_id) == str(recipient_user_id)
        ]


class InMemoryDeviceTokenRepository(DeviceTokenRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, DeviceToken] = {}

    async def get(self, device_token_id: DeviceTokenId) -> DeviceToken | None:
        return self.by_id.get(str(device_token_id))

    def add(self, device_token: DeviceToken) -> None:
        self.by_id[str(device_token.id)] = device_token

    async def list_all(self) -> list[DeviceToken]:
        return list(self.by_id.values())

    async def get_by_token(self, fcm_token: str) -> DeviceToken | None:
        return next(
            (t for t in self.by_id.values() if str(t.fcm_token) == fcm_token), None
        )


class FakeNotificationsUnitOfWork(NotificationsUnitOfWork):
    def __init__(
        self,
        notifications: InMemoryNotificationRepository,
        device_tokens: InMemoryDeviceTokenRepository,
    ) -> None:
        self.notifications = notifications
        self.device_tokens = device_tokens
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def make_uow() -> FakeNotificationsUnitOfWork:
    return FakeNotificationsUnitOfWork(
        InMemoryNotificationRepository(), InMemoryDeviceTokenRepository()
    )


def make_service() -> NotificationApplicationService:
    return NotificationApplicationService(clock=CLOCK, id_generator=SequentialIdGenerator())


class NotificationApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_notification_persists_and_returns_dto(self) -> None:
        service = make_service()
        uow = make_uow()
        notification = await service.create_notification(
            CreateNotificationCommand(
                organization_id=VALID_ORG_ULID,
                recipient_user_id=RECIPIENT_USER_ID,
                type="trip_started",
                title="Morning trip started",
                body="Your child's bus has started its morning trip.",
                data=None,
                trip_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(notification.status, "unread")
        self.assertEqual(uow.commit_count, 1)
        self.assertEqual(len(uow.notifications.by_id), 1)

    async def test_mark_notification_read_by_recipient_succeeds(self) -> None:
        service = make_service()
        uow = make_uow()
        notification = await service.create_notification(
            CreateNotificationCommand(
                organization_id=VALID_ORG_ULID,
                recipient_user_id=RECIPIENT_USER_ID,
                type="system",
                title="System notice",
                body="Something happened.",
                data=None,
                trip_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        read = await service.mark_notification_read(
            MarkNotificationReadCommand(
                notification_id=notification.id, actor=make_actor(RECIPIENT_USER_ID)
            ),
            uow=uow,
        )
        self.assertEqual(read.status, "read")
        self.assertIsNotNone(read.read_at)

    async def test_mark_notification_read_by_non_recipient_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        notification = await service.create_notification(
            CreateNotificationCommand(
                organization_id=VALID_ORG_ULID,
                recipient_user_id=RECIPIENT_USER_ID,
                type="system",
                title="System notice",
                body="Something happened.",
                data=None,
                trip_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(NotFoundError):
            await service.mark_notification_read(
                MarkNotificationReadCommand(
                    notification_id=notification.id, actor=make_actor(OTHER_USER_ID)
                ),
                uow=uow,
            )

    async def test_mark_notification_read_missing_notification_raises_not_found(
        self,
    ) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.mark_notification_read(
                MarkNotificationReadCommand(
                    notification_id=NON_EXISTENT_ID, actor=make_actor()
                ),
                uow=uow,
            )

    async def test_get_notification_by_id_for_recipient_succeeds(self) -> None:
        service = make_service()
        uow = make_uow()
        notification = await service.create_notification(
            CreateNotificationCommand(
                organization_id=VALID_ORG_ULID,
                recipient_user_id=RECIPIENT_USER_ID,
                type="system",
                title="System notice",
                body="Something happened.",
                data=None,
                trip_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        fetched = await service.get_notification_by_id(
            GetNotificationByIdQuery(
                notification_id=notification.id, recipient_user_id=RECIPIENT_USER_ID
            ),
            uow=uow,
        )
        self.assertEqual(fetched.id, notification.id)

    async def test_get_notification_by_id_for_non_recipient_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        notification = await service.create_notification(
            CreateNotificationCommand(
                organization_id=VALID_ORG_ULID,
                recipient_user_id=RECIPIENT_USER_ID,
                type="system",
                title="System notice",
                body="Something happened.",
                data=None,
                trip_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(NotFoundError):
            await service.get_notification_by_id(
                GetNotificationByIdQuery(
                    notification_id=notification.id, recipient_user_id=OTHER_USER_ID
                ),
                uow=uow,
            )

    async def test_list_notifications_for_recipient_scopes_to_own_only(self) -> None:
        service = make_service()
        uow = make_uow()
        await service.create_notification(
            CreateNotificationCommand(
                organization_id=VALID_ORG_ULID,
                recipient_user_id=RECIPIENT_USER_ID,
                type="system",
                title="Mine",
                body="This one is mine.",
                data=None,
                trip_id=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.create_notification(
            CreateNotificationCommand(
                organization_id=VALID_ORG_ULID,
                recipient_user_id=OTHER_USER_ID,
                type="system",
                title="Not mine",
                body="This one is not mine.",
                data=None,
                trip_id=None,
                actor=make_actor(OTHER_USER_ID),
            ),
            uow=uow,
        )
        results = await service.list_notifications_for_recipient(
            ListNotificationsForRecipientQuery(recipient_user_id=RECIPIENT_USER_ID), uow=uow
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Mine")


class DeviceTokenApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_device_token_persists_and_returns_dto(self) -> None:
        service = make_service()
        uow = make_uow()
        token = await service.register_device_token(
            RegisterDeviceTokenCommand(
                fcm_token="fcm-token-abc", platform="android", actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(token.fcm_token, "fcm-token-abc")
        self.assertIsNone(token.revoked_at)
        self.assertEqual(len(uow.device_tokens.by_id), 1)

    async def test_register_duplicate_fcm_token_raises_conflict(self) -> None:
        service = make_service()
        uow = make_uow()
        await service.register_device_token(
            RegisterDeviceTokenCommand(
                fcm_token="fcm-token-dup", platform="android", actor=make_actor()
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await service.register_device_token(
                RegisterDeviceTokenCommand(
                    fcm_token="fcm-token-dup",
                    platform="ios",
                    actor=make_actor(OTHER_USER_ID),
                ),
                uow=uow,
            )

    async def test_revoke_device_token_by_owner_succeeds(self) -> None:
        service = make_service()
        uow = make_uow()
        token = await service.register_device_token(
            RegisterDeviceTokenCommand(
                fcm_token="fcm-token-owned", platform="ios", actor=make_actor()
            ),
            uow=uow,
        )
        revoked = await service.revoke_device_token(
            RevokeDeviceTokenCommand(
                device_token_id=token.id, actor=make_actor(RECIPIENT_USER_ID)
            ),
            uow=uow,
        )
        self.assertIsNotNone(revoked.revoked_at)

    async def test_revoke_device_token_by_non_owner_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        token = await service.register_device_token(
            RegisterDeviceTokenCommand(
                fcm_token="fcm-token-owned-2", platform="ios", actor=make_actor()
            ),
            uow=uow,
        )
        with self.assertRaises(NotFoundError):
            await service.revoke_device_token(
                RevokeDeviceTokenCommand(
                    device_token_id=token.id, actor=make_actor(OTHER_USER_ID)
                ),
                uow=uow,
            )

    async def test_revoke_missing_device_token_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.revoke_device_token(
                RevokeDeviceTokenCommand(
                    device_token_id=NON_EXISTENT_ID, actor=make_actor()
                ),
                uow=uow,
            )


if __name__ == "__main__":
    unittest.main()
