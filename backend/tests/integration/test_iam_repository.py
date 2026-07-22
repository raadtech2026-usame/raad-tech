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

import hashlib
import unittest
import uuid
from datetime import timedelta

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import ValidationError
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.time.clock import SystemClock
from raad.core.tenancy.principal import Role
from raad.modules.iam.domain.entities import RefreshToken, User
from raad.modules.iam.domain.value_objects import (
    Email,
    RefreshTokenId,
    UserId,
    UserStatus,
)
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


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class RefreshTokenRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    """Regression coverage for the tz-aware/naive datetime bug `RefreshToken.is_expired`
    (`domain/entities.py`) shipped with: `clock.now()` (tz-aware) compared against a
    `RefreshToken` reloaded from the database (naive `expires_at`, before `iam.infra.mappers.
    _aware_utc` fixed it) raised `TypeError` on every real `POST /auth/refresh` call. A
    freshly-`.issue()`d token, never reloaded, never exercised the buggy comparison — only a
    real add-then-get round trip against a live database does, which is exactly what no
    existing unit test (all fake-repository-backed) or this file (added after IAM's own
    `SqlAlchemyUnitOfWork` wiring, before `RefreshToken` had any round-trip coverage of its own)
    previously did."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_user_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_user_ids:
                # refresh_tokens has no ON DELETE CASCADE to users (migration
                # 8ffa6434d344) - delete the child rows first or the FK constraint blocks
                # deleting the parent user row.
                await conn.execute(
                    text("DELETE FROM refresh_tokens WHERE user_id = ANY(:ids)"),
                    {"ids": self._created_user_ids},
                )
                await conn.execute(
                    text("DELETE FROM users WHERE id = ANY(:ids)"),
                    {"ids": self._created_user_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyIamUnitOfWork:
        return SqlAlchemyIamUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed_user(self, uow: SqlAlchemyIamUnitOfWork) -> UserId:
        user = User.invite(
            id=UserId(self.id_generator.new_id()),
            organization_id=None,
            role=Role.FOUNDER,
            email=Email(f"refresh-token-{self.tag}@example.com"),
            phone=None,
            full_name=f"Refresh Token Test {self.tag}",
            clock=self.clock,
        )
        uow.users.add(user)
        uow.record_events(user.pull_domain_events())
        await uow.commit()
        self._created_user_ids.append(str(user.id))
        return user.id

    async def test_add_then_get_round_trips_and_is_expired_does_not_raise(self) -> None:
        async with self._new_uow() as uow:
            user_id = await self._seed_user(uow)
            token_hash = hashlib.sha256(f"token-{self.tag}".encode()).hexdigest()
            token = RefreshToken.issue(
                id=RefreshTokenId(self.id_generator.new_id()),
                user_id=user_id,
                token_hash=token_hash,
                expires_at=self.clock.now() + timedelta(days=1),
                clock=self.clock,
            )
            uow.refresh_tokens.add(token)
            uow.record_events(token.pull_domain_events())
            await uow.commit()
            token_id = token.id

        async with self._new_uow() as uow:
            fetched = await uow.refresh_tokens.get(token_id)

        self.assertIsNotNone(fetched)
        # The regression itself: before the fix, this line raised `TypeError: can't compare
        # offset-naive and offset-aware datetimes` - `fetched.expires_at` came back naive.
        self.assertFalse(fetched.is_expired(clock=self.clock))

    async def test_get_by_token_hash_round_trips_and_reports_not_expired(self) -> None:
        """`get_by_token_hash` is the actual lookup path `AuthApplicationService.refresh` uses
        (`application/services.py`) - covering it directly, not just `.get(token_id)` above."""
        async with self._new_uow() as uow:
            user_id = await self._seed_user(uow)
            token_hash = hashlib.sha256(f"lookup-{self.tag}".encode()).hexdigest()
            token = RefreshToken.issue(
                id=RefreshTokenId(self.id_generator.new_id()),
                user_id=user_id,
                token_hash=token_hash,
                expires_at=self.clock.now() + timedelta(days=1),
                clock=self.clock,
            )
            uow.refresh_tokens.add(token)
            uow.record_events(token.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            fetched = await uow.refresh_tokens.get_by_token_hash(token_hash)

        self.assertIsNotNone(fetched)
        self.assertFalse(fetched.is_expired(clock=self.clock))
        self.assertFalse(fetched.is_revoked)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class UserPaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemyUserRepository.list_page` against real SQL, including the `role`
    filter's case `transform` (`infra/repositories.py`): `UserResponse.role`/`Role.value` is
    upper-case (what a client would naturally filter by), the stored column is lower-case
    (`infra/mappers.py`'s module docstring) — this is the one live-DB proof that round-trips
    through the actual asymmetry rather than a same-casing in-memory fake."""

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

    async def _seed(self, *, full_name: str, role: Role) -> None:
        async with self._new_uow() as uow:
            user = User.invite(
                id=UserId(self.id_generator.new_id()),
                organization_id=None,
                role=role,
                email=Email(f"{full_name.lower().replace(' ', '.')}-{self.tag}@example.com"),
                phone=None,
                full_name=full_name,
                clock=self.clock,
            )
            uow.users.add(user)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(user.id))

    async def test_list_page_filters_by_role_case_insensitively_via_transform(self) -> None:
        await self._seed(full_name=f"Founder User {self.tag}", role=Role.FOUNDER)
        await self._seed(full_name=f"Support User {self.tag}", role=Role.SUPPORT_STAFF)

        async with self._new_uow() as uow:
            page = await uow.users.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[FilterCondition(field="role", op="eq", value="FOUNDER")],
                search=self.tag,
            )
        matching = [u for u in page.data if self.tag in u.full_name]
        self.assertTrue(all(u.role == Role.FOUNDER for u in matching))
        self.assertIn(f"Founder User {self.tag}", [u.full_name for u in matching])

    async def test_list_page_search_matches_full_name_substring(self) -> None:
        await self._seed(full_name=f"Searchable Person {self.tag}", role=Role.FOUNDER)

        async with self._new_uow() as uow:
            page = await uow.users.list_page(
                OffsetPageRequest(), sort=[], filters=[], search=f"searchable person {self.tag}"
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].full_name, f"Searchable Person {self.tag}")

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.users.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[FilterCondition(field="password_hash", op="eq", value="x")],
                    search=None,
                )


if __name__ == "__main__":
    unittest.main()
