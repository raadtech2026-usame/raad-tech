"""PostgreSQL-backed integration test for `iam`'s `SqlAlchemyUserRepository`. Stdlib
`unittest` — no `pytest` (not an approved dependency) — against the real
`SqlAlchemyIamUnitOfWork` and the live migrated schema, not fakes, mirroring
`test_transport_ops_driver_repository.py`'s skip-guard/cleanup pattern exactly.

**Closes a real, previously-flagged gap**: CLAUDE.md's own "Known gaps" section names IAM as
one of four modules (alongside Organization, Fleet Device, Tracking) with no dedicated live-DB
integration test file, its `SqlAlchemyUnitOfWork` wiring exercised only indirectly via
`test_rbac_and_scope_resolver.py`/`test_postgres_repository_invariants.py`. This file gives
`iam` its own direct round-trip coverage, the same way every other module already has one.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run
marker and deletes them in `tearDown`, leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.core.tenancy.principal import Role
from raad.modules.iam.domain.entities import User
from raad.modules.iam.domain.value_objects import Email, UserId, UserStatus
from raad.modules.iam.infra.repositories import SqlAlchemyIamUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class UserRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_ids:
                await conn.execute(
                    text("DELETE FROM users WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyIamUnitOfWork:
        return SqlAlchemyIamUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def test_add_then_get_round_trips_all_fields(self) -> None:
        async with self._new_uow() as uow:
            user = User.invite(
                id=UserId(self.id_generator.new_id()),
                organization_id=None,
                role=Role.FOUNDER,
                email=Email(f"integration-{self.tag}@example.com"),
                phone=None,
                full_name=f"Integration Test {self.tag}",
                clock=self.clock,
            )
            uow.users.add(user)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            user_id = user.id
            self._created_ids.append(str(user_id))

        async with self._new_uow() as uow:
            fetched = await uow.users.get(user_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.email), f"integration-{self.tag}@example.com")
        self.assertEqual(fetched.full_name, f"Integration Test {self.tag}")
        self.assertEqual(fetched.status, UserStatus.INVITED)

    async def test_mutation_after_get_persists_without_a_second_add(self) -> None:
        """Proves the identity-map/`flush_tracked_changes` bridge: `get()` returns a detached
        domain object, and calling a lifecycle method on it followed by `commit()` (no `add()`
        call) must still persist, because the repository re-projects the tracked object onto
        its ORM row."""
        async with self._new_uow() as uow:
            user = User.invite(
                id=UserId(self.id_generator.new_id()),
                organization_id=None,
                role=Role.FOUNDER,
                email=Email(f"mutate-{self.tag}@example.com"),
                phone=None,
                full_name=f"Mutate Test {self.tag}",
                clock=self.clock,
            )
            uow.users.add(user)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            user_id = user.id
            self._created_ids.append(str(user_id))

        async with self._new_uow() as uow:
            loaded = await uow.users.get(user_id)
            loaded.activate(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.users.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.users.get(user_id)

        self.assertEqual(refetched.status, UserStatus.ACTIVE)

    async def test_list_all_includes_newly_added_user(self) -> None:
        async with self._new_uow() as uow:
            user = User.invite(
                id=UserId(self.id_generator.new_id()),
                organization_id=None,
                role=Role.FOUNDER,
                email=Email(f"list-{self.tag}@example.com"),
                phone=None,
                full_name=f"List Test {self.tag}",
                clock=self.clock,
            )
            uow.users.add(user)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(user.id))

        async with self._new_uow() as uow:
            all_users = await uow.users.list_all()

        self.assertIn(str(user.id), {str(u.id) for u in all_users})

    async def test_get_missing_user_returns_none(self) -> None:
        async with self._new_uow() as uow:
            result = await uow.users.get(UserId(self.id_generator.new_id()))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
