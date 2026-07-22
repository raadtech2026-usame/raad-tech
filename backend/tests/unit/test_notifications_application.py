"""Application-layer tests for `notifications`' `NotificationApplicationService` (Phase 16;
cursor-pagination coverage added in the Pagination/Filtering/Sorting phase). Stdlib `unittest`
— no `pytest` (not an approved dependency), mirroring `test_billing_application.py`'s exact
structure. Uses in-memory fakes for both repositories bundled onto one fake
`NotificationsUnitOfWork` — no SQLAlchemy, no FastAPI, no real database.

Covers: `create_notification` (application-layer-only path), `mark_notification_read`'s
ownership enforcement (`NotFoundError` on a non-recipient caller, matching the documented
404-over-403 posture), `get_notification_by_id`'s identical ownership scoping,
`list_notifications_for_recipient`'s personal (not tenant) scoping and (as of this phase) its
cursor pagination/filtering semantics, `register_device_token`'s `ux_device_tokens__token`
defense-in-depth (`ConflictError` on a duplicate token), and `revoke_device_token`'s ownership
enforcement.

`InMemoryNotificationRepository.list_for_recipient_page` re-implements cursor semantics
in-memory (sort descending by `(created_at, id)`, decode/encode cursors via `core.pagination`'s
own helpers) purely to exercise `NotificationApplicationService`/`ListNotificationsForRecipientQuery`
at this layer — it is deliberately not a copy of `SqlAlchemyRepositoryBase.list_cursor_page`'s
SQL, since that mechanics-level proof belongs to `test_notifications_repository.py`'s live-DB
suite instead.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from raad.core.errors.exceptions import ConflictError, NotFoundError, ValidationError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import (
    CursorPage,
    CursorPageRequest,
    FilterCondition,
    decode_cursor,
    encode_cursor,
)
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


class SteppingClock(Clock):
    """Advances by `step` on every `now()` call — needed only by the pagination tests below,
    which must prove newest-first `created_at` ordering (`FixedClock`'s single frozen instant
    can't distinguish creation order on its own, since `Notification.create` doesn't accept an
    explicit `created_at`)."""

    def __init__(self, start: datetime, step: timedelta = timedelta(seconds=1)) -> None:
        self._current = start
        self._step = step

    def now(self) -> datetime:
        value = self._current
        self._current = self._current + self._step
        return value


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
    #: Mirrors `SqlAlchemyNotificationRepository.filterable_fields` (`infra/repositories.py`) —
    #: kept as a plain field-name set here since this fake filters domain objects directly,
    #: never an ORM column. `status` is deliberately excluded, matching the real repository —
    #: it is a domain-derived property (`read_at`-based), never a persisted column.
    _FILTERABLE_FIELDS = {"type", "trip_id", "recipient_user_id"}

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

    def _field_value(self, notification: Notification, field_name: str) -> str | None:
        if field_name == "type":
            return notification.type.value
        if field_name == "trip_id":
            return str(notification.trip_id) if notification.trip_id is not None else None
        if field_name == "recipient_user_id":
            return str(notification.recipient_user_id)
        raise AssertionError(f"unexpected field {field_name!r}")  # pragma: no cover

    async def list_for_recipient_page(
        self,
        recipient_user_id: UserId,
        cursor_request: CursorPageRequest,
        *,
        filters: list[FilterCondition],
    ) -> CursorPage[Notification]:
        combined_filters = [
            FilterCondition(field="recipient_user_id", op="eq", value=str(recipient_user_id)),
            *filters,
        ]
        for condition in combined_filters:
            if condition.field not in self._FILTERABLE_FIELDS:
                raise ValidationError(
                    f"Field {condition.field!r} is not filterable on this resource.",
                    details={"field": condition.field},
                )

        candidates = [
            n
            for n in self.by_id.values()
            if all(
                self._field_value(n, c.field) == c.value for c in combined_filters
            )
        ]
        candidates.sort(key=lambda n: (n.created_at, str(n.id)), reverse=True)

        if cursor_request.cursor is not None:
            raw_value, row_id = decode_cursor(cursor_request.cursor)
            cursor_key = (datetime.fromisoformat(raw_value), row_id)
            candidates = [
                n for n in candidates if (n.created_at, str(n.id)) < cursor_key
            ]

        page_rows = candidates[: cursor_request.limit]
        has_more = len(candidates) > cursor_request.limit
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = encode_cursor(last.created_at.isoformat(), str(last.id))

        return CursorPage(
            data=page_rows,
            limit=cursor_request.limit,
            next_cursor=next_cursor,
            has_more=has_more,
        )


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


def make_service(clock: Clock = CLOCK) -> NotificationApplicationService:
    return NotificationApplicationService(clock=clock, id_generator=SequentialIdGenerator())


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
        page = await service.list_notifications_for_recipient(
            ListNotificationsForRecipientQuery(recipient_user_id=RECIPIENT_USER_ID), uow=uow
        )
        self.assertEqual(len(page.data), 1)
        self.assertEqual(page.data[0].title, "Mine")


class NotificationPaginationApplicationTests(unittest.IsolatedAsyncioTestCase):
    """Cursor pagination/filtering coverage for `list_notifications_for_recipient`, added in
    the Pagination/Filtering/Sorting phase. Uses `SteppingClock` (not the module's shared
    `CLOCK`) so seeded notifications get distinct, monotonically increasing `created_at`
    values — proving the ordering is genuinely timestamp-driven, not an artifact of insertion
    order/id sequence alone."""

    async def _seed(
        self,
        service: NotificationApplicationService,
        uow: FakeNotificationsUnitOfWork,
        *,
        recipient_user_id: str,
        title: str,
        type_: str = "system",
    ):
        return await service.create_notification(
            CreateNotificationCommand(
                organization_id=VALID_ORG_ULID,
                recipient_user_id=recipient_user_id,
                type=type_,
                title=title,
                body=f"Body for {title}",
                data=None,
                trip_id=None,
                actor=make_actor(recipient_user_id),
            ),
            uow=uow,
        )

    async def test_first_page_reports_correct_has_more_and_next_cursor(self) -> None:
        clock = SteppingClock(datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc))
        service = make_service(clock)
        uow = make_uow()
        for i in range(5):
            await self._seed(service, uow, recipient_user_id=RECIPIENT_USER_ID, title=f"N{i}")

        page = await service.list_notifications_for_recipient(
            ListNotificationsForRecipientQuery(
                recipient_user_id=RECIPIENT_USER_ID,
                cursor_request=CursorPageRequest(limit=2),
            ),
            uow=uow,
        )
        self.assertEqual(len(page.data), 2)
        self.assertTrue(page.has_more)
        self.assertIsNotNone(page.next_cursor)
        # Newest-first (descending `created_at`): N4 was created last, so it leads.
        self.assertEqual([n.title for n in page.data], ["N4", "N3"])

    async def test_following_next_cursor_returns_next_slice_with_no_overlap(self) -> None:
        clock = SteppingClock(datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc))
        service = make_service(clock)
        uow = make_uow()
        for i in range(5):
            await self._seed(service, uow, recipient_user_id=RECIPIENT_USER_ID, title=f"N{i}")

        first_page = await service.list_notifications_for_recipient(
            ListNotificationsForRecipientQuery(
                recipient_user_id=RECIPIENT_USER_ID,
                cursor_request=CursorPageRequest(limit=2),
            ),
            uow=uow,
        )
        second_page = await service.list_notifications_for_recipient(
            ListNotificationsForRecipientQuery(
                recipient_user_id=RECIPIENT_USER_ID,
                cursor_request=CursorPageRequest(limit=2, cursor=first_page.next_cursor),
            ),
            uow=uow,
        )
        third_page = await service.list_notifications_for_recipient(
            ListNotificationsForRecipientQuery(
                recipient_user_id=RECIPIENT_USER_ID,
                cursor_request=CursorPageRequest(limit=2, cursor=second_page.next_cursor),
            ),
            uow=uow,
        )
        all_titles = (
            [n.title for n in first_page.data]
            + [n.title for n in second_page.data]
            + [n.title for n in third_page.data]
        )
        self.assertEqual(all_titles, ["N4", "N3", "N2", "N1", "N0"])
        self.assertFalse(third_page.has_more)
        self.assertIsNone(third_page.next_cursor)

    async def test_filtering_by_type_narrows_results(self) -> None:
        clock = SteppingClock(datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc))
        service = make_service(clock)
        uow = make_uow()
        await self._seed(
            service, uow, recipient_user_id=RECIPIENT_USER_ID, title="Trip", type_="trip_started"
        )
        await self._seed(
            service, uow, recipient_user_id=RECIPIENT_USER_ID, title="Sys", type_="system"
        )

        page = await service.list_notifications_for_recipient(
            ListNotificationsForRecipientQuery(
                recipient_user_id=RECIPIENT_USER_ID,
                filters=[FilterCondition(field="type", op="eq", value="trip_started")],
            ),
            uow=uow,
        )
        self.assertEqual(len(page.data), 1)
        self.assertEqual(page.data[0].title, "Trip")

    async def test_filtering_by_status_is_rejected_as_unwhitelisted(self) -> None:
        """`status` is a domain-derived property (`read_at`-based), never a persisted
        `NotificationModel` column (Database Design §7.5 has no `status` column) — whitelisting
        it would turn every `filter[status]=...` request into an unhandled `AttributeError`
        against the real repository instead of this clean `ValidationError`. Regression test
        for that exact mistake, mirroring `SqlAlchemyNotificationRepository.filterable_fields`'s
        own docstring."""
        service = make_service()
        uow = make_uow()
        with self.assertRaises(ValidationError):
            await service.list_notifications_for_recipient(
                ListNotificationsForRecipientQuery(
                    recipient_user_id=RECIPIENT_USER_ID,
                    filters=[FilterCondition(field="status", op="eq", value="read")],
                ),
                uow=uow,
            )

    async def test_unwhitelisted_filter_field_raises_validation_error(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(ValidationError):
            await service.list_notifications_for_recipient(
                ListNotificationsForRecipientQuery(
                    recipient_user_id=RECIPIENT_USER_ID,
                    filters=[FilterCondition(field="title", op="eq", value="Mine")],
                ),
                uow=uow,
            )

    async def test_other_recipients_notifications_never_leak_into_page(self) -> None:
        """Ownership isolation under pagination: even with a limit small enough to force
        multiple pages, another recipient's rows must never appear on any page, mirroring
        this module's existing ownership tests (`test_list_notifications_for_recipient_
        scopes_to_own_only`)."""
        clock = SteppingClock(datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc))
        service = make_service(clock)
        uow = make_uow()
        for i in range(3):
            await self._seed(service, uow, recipient_user_id=RECIPIENT_USER_ID, title=f"Mine{i}")
        for i in range(3):
            await self._seed(
                service, uow, recipient_user_id=OTHER_USER_ID, title=f"NotMine{i}"
            )

        seen_titles: list[str] = []
        cursor = None
        for _ in range(10):  # bounded loop, generous upper limit on page count
            page = await service.list_notifications_for_recipient(
                ListNotificationsForRecipientQuery(
                    recipient_user_id=RECIPIENT_USER_ID,
                    cursor_request=CursorPageRequest(limit=1, cursor=cursor),
                ),
                uow=uow,
            )
            seen_titles.extend(n.title for n in page.data)
            if not page.has_more:
                break
            cursor = page.next_cursor

        self.assertEqual(len(seen_titles), 3)
        self.assertTrue(all(title.startswith("Mine") for title in seen_titles))


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
