"""PostgreSQL-backed integration test for `notifications`' `SqlAlchemyNotificationsUnitOfWork`/
two repositories (Phase 16). Stdlib `unittest` — no `pytest` (not an approved dependency), using
`unittest.IsolatedAsyncioTestCase` against the real `SqlAlchemyNotificationsUnitOfWork` and the
live migrated schema (Alembic head `56e86806baa2`), not fakes — mirroring
`test_billing_repository.py`'s skip-guard/cleanup pattern exactly.

Covers what no in-memory unit test can prove: the round trip through the real identity-map/
`flush_tracked_changes` mechanics for both aggregates (including the `data_json`/`JSONB` round
trip — the first JSON column in this codebase), `NotificationRepository.list_for_recipient`'s
direct-`select()` correctness, and `DeviceTokenRepository.get_by_token`'s direct-`select()`
correctness. The DB-level uniqueness proof of `ux_device_tokens__token` lives in
`test_postgres_repository_invariants.py`, not duplicated here.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run
marker and deletes them in `tearDown`, leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime

from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.modules.notifications.domain.entities import DeviceToken, Notification
from raad.modules.notifications.domain.value_objects import (
    DeviceTokenId,
    FcmToken,
    NotificationId,
    NotificationType,
    OrganizationId,
    Platform,
    UserId,
)
from raad.modules.notifications.infra.repositories import (
    SqlAlchemyNotificationsUnitOfWork,
)


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class NotificationsRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_notification_ids: list[str] = []
        self._created_device_token_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_notification_ids:
                await conn.execute(
                    text("DELETE FROM notifications WHERE id = ANY(:ids)"),
                    {"ids": self._created_notification_ids},
                )
            if self._created_device_token_ids:
                await conn.execute(
                    text("DELETE FROM device_tokens WHERE id = ANY(:ids)"),
                    {"ids": self._created_device_token_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyNotificationsUnitOfWork:
        return SqlAlchemyNotificationsUnitOfWork(self.session_factory, self.outbox_writer)

    async def test_notification_add_then_get_round_trips(self) -> None:
        org_id = self.id_generator.new_id()
        recipient_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            notification = Notification.create(
                id=NotificationId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                recipient_user_id=UserId(recipient_id),
                type=NotificationType.TRIP_STARTED,
                title=f"Trip started {self.tag}",
                body="Your child's bus has started its morning trip.",
                data={"deep_link": "raad://trip/01J...", "count": 3},
                clock=self.clock,
            )
            uow.notifications.add(notification)
            uow.record_events(notification.pull_domain_events())
            await uow.commit()
            notification_id = notification.id
            self._created_notification_ids.append(str(notification_id))

        async with self._new_uow() as uow:
            fetched = await uow.notifications.get(notification_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(fetched.type, NotificationType.TRIP_STARTED)
        self.assertIsNone(fetched.read_at)
        self.assertEqual(fetched.data, {"deep_link": "raad://trip/01J...", "count": 3})

    async def test_notification_mutation_after_get_persists_without_a_second_add(
        self,
    ) -> None:
        org_id = self.id_generator.new_id()
        recipient_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            notification = Notification.create(
                id=NotificationId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                recipient_user_id=UserId(recipient_id),
                type=NotificationType.SYSTEM,
                title=f"System {self.tag}",
                body="A system notice.",
                clock=self.clock,
            )
            uow.notifications.add(notification)
            uow.record_events(notification.pull_domain_events())
            await uow.commit()
            notification_id = notification.id
            self._created_notification_ids.append(str(notification_id))

        async with self._new_uow() as uow:
            loaded = await uow.notifications.get(notification_id)
            loaded.mark_read(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.notifications.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.notifications.get(notification_id)

        self.assertIsNotNone(refetched.read_at)

    async def test_list_for_recipient_returns_only_that_recipients_notifications(
        self,
    ) -> None:
        org_id = self.id_generator.new_id()
        recipient_id = self.id_generator.new_id()
        other_recipient_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            mine = Notification.create(
                id=NotificationId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                recipient_user_id=UserId(recipient_id),
                type=NotificationType.SYSTEM,
                title=f"Mine {self.tag}",
                body="This one is mine.",
                clock=self.clock,
            )
            not_mine = Notification.create(
                id=NotificationId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                recipient_user_id=UserId(other_recipient_id),
                type=NotificationType.SYSTEM,
                title=f"Not mine {self.tag}",
                body="This one is not mine.",
                clock=self.clock,
            )
            uow.notifications.add(mine)
            uow.notifications.add(not_mine)
            uow.record_events(mine.pull_domain_events())
            uow.record_events(not_mine.pull_domain_events())
            await uow.commit()
            self._created_notification_ids.append(str(mine.id))
            self._created_notification_ids.append(str(not_mine.id))

        async with self._new_uow() as uow:
            results = await uow.notifications.list_for_recipient(UserId(recipient_id))

        self.assertEqual(len(results), 1)
        self.assertEqual(str(results[0].id), str(mine.id))

    async def test_device_token_add_then_get_round_trips(self) -> None:
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            token = DeviceToken.register(
                id=DeviceTokenId(self.id_generator.new_id()),
                user_id=UserId(user_id),
                fcm_token=FcmToken(f"fcm-token-{self.tag}"),
                platform=Platform.ANDROID,
                clock=self.clock,
            )
            uow.device_tokens.add(token)
            uow.record_events(token.pull_domain_events())
            await uow.commit()
            token_id = token.id
            self._created_device_token_ids.append(str(token_id))

        async with self._new_uow() as uow:
            fetched = await uow.device_tokens.get(token_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.user_id), user_id)
        self.assertIsNone(fetched.revoked_at)

    async def test_get_by_token_finds_the_device_token(self) -> None:
        user_id = self.id_generator.new_id()
        fcm_value = f"fcm-lookup-{self.tag}"
        async with self._new_uow() as uow:
            token = DeviceToken.register(
                id=DeviceTokenId(self.id_generator.new_id()),
                user_id=UserId(user_id),
                fcm_token=FcmToken(fcm_value),
                platform=Platform.IOS,
                clock=self.clock,
            )
            uow.device_tokens.add(token)
            uow.record_events(token.pull_domain_events())
            await uow.commit()
            self._created_device_token_ids.append(str(token.id))

        async with self._new_uow() as uow:
            found = await uow.device_tokens.get_by_token(fcm_value)
            not_found = await uow.device_tokens.get_by_token(f"nonexistent-{self.tag}")

        self.assertIsNotNone(found)
        self.assertEqual(str(found.id), str(token.id))
        self.assertIsNone(not_found)

    async def test_device_token_mutation_after_get_persists_without_a_second_add(
        self,
    ) -> None:
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            token = DeviceToken.register(
                id=DeviceTokenId(self.id_generator.new_id()),
                user_id=UserId(user_id),
                fcm_token=FcmToken(f"fcm-mutate-{self.tag}"),
                platform=Platform.ANDROID,
                clock=self.clock,
            )
            uow.device_tokens.add(token)
            uow.record_events(token.pull_domain_events())
            await uow.commit()
            token_id = token.id
            self._created_device_token_ids.append(str(token_id))

        async with self._new_uow() as uow:
            loaded = await uow.device_tokens.get(token_id)
            loaded.revoke(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.device_tokens.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.device_tokens.get(token_id)

        self.assertIsNotNone(refetched.revoked_at)


if __name__ == "__main__":
    unittest.main()
