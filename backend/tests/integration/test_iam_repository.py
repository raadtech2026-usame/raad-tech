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
from sqlalchemy.ext.asyncio import AsyncEngine

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import LockoutSettings, get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.di.bootstrap import build_container
from raad.core.errors.exceptions import (
    AccountLockedError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
)
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.security.password_hashing import Pbkdf2PasswordHasher
from raad.core.security.tokens import JwtTokenService
from raad.core.tenancy.principal import Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import Clock, SystemClock
from raad.modules.iam.application.commands import LoginCommand, RevokeSessionCommand
from raad.modules.iam.application.ports import SessionCapPort
from raad.modules.iam.application.queries import ListSessionsQuery
from raad.modules.iam.application.services import AuthApplicationService
from raad.modules.iam.domain.entities import RefreshToken, User
from raad.modules.iam.domain.value_objects import (
    Email,
    RefreshTokenId,
    UserId,
    UserStatus,
)
from raad.modules.iam.infra.repositories import SqlAlchemyIamUnitOfWork


class _FixedClock(Clock):
    """A settable fake clock — used only by `AccountLockoutRepositoryTests` to simulate the
    lockout window elapsing without a real `time.sleep`."""

    def __init__(self, now):  # type: ignore[no-untyped-def]
        self._now = now

    def now(self):  # type: ignore[no-untyped-def]
        return self._now

    def set(self, now) -> None:  # type: ignore[no-untyped-def]
        self._now = now


class _FixedSessionCapPort(SessionCapPort):
    """ADR-0019. A controlled, per-test cap value — mirrors `LockoutSettings(max_attempts=3)`'s
    own "deliberately tight, not the production default" reasoning for fast, deterministic
    tests. `SessionCapAdapterLiveSettingTests` below separately proves the *real*
    `SystemSettingSessionCapAdapter` reads the actual migration-seeded row correctly."""

    def __init__(self, max_sessions: int = 100) -> None:
        self._max_sessions = max_sessions

    async def get_max_sessions(self, *, role: Role) -> int:
        return self._max_sessions


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

    async def test_list_by_user_returns_only_non_revoked_tokens_for_that_user(self) -> None:
        """ADR-0017 Amendment: the primitive `reset_password_to_temporary` uses to invalidate
        a user's active sessions — must exclude already-revoked tokens and never return another
        user's tokens."""
        async with self._new_uow() as uow:
            user_id = await self._seed_user(uow)
            other_user = User.invite(
                id=UserId(self.id_generator.new_id()),
                organization_id=None,
                role=Role.FOUNDER,
                email=Email(f"refresh-token-other-{self.tag}@example.com"),
                phone=None,
                full_name=f"Refresh Token Other Test {self.tag}",
                clock=self.clock,
            )
            uow.users.add(other_user)
            uow.record_events(other_user.pull_domain_events())
            await uow.commit()
            self._created_user_ids.append(str(other_user.id))
            other_user_id = other_user.id

            live_token = RefreshToken.issue(
                id=RefreshTokenId(self.id_generator.new_id()),
                user_id=user_id,
                token_hash=hashlib.sha256(f"live-{self.tag}".encode()).hexdigest(),
                expires_at=self.clock.now() + timedelta(days=1),
                clock=self.clock,
            )
            revoked_token = RefreshToken.issue(
                id=RefreshTokenId(self.id_generator.new_id()),
                user_id=user_id,
                token_hash=hashlib.sha256(f"revoked-{self.tag}".encode()).hexdigest(),
                expires_at=self.clock.now() + timedelta(days=1),
                clock=self.clock,
            )
            other_users_token = RefreshToken.issue(
                id=RefreshTokenId(self.id_generator.new_id()),
                user_id=other_user_id,
                token_hash=hashlib.sha256(f"other-{self.tag}".encode()).hexdigest(),
                expires_at=self.clock.now() + timedelta(days=1),
                clock=self.clock,
            )
            revoked_token.revoke(clock=self.clock)

            uow.refresh_tokens.add(live_token)
            uow.refresh_tokens.add(revoked_token)
            uow.refresh_tokens.add(other_users_token)
            uow.record_events(
                live_token.pull_domain_events()
                + revoked_token.pull_domain_events()
                + other_users_token.pull_domain_events()
            )
            await uow.commit()

        async with self._new_uow() as uow:
            result = await uow.refresh_tokens.list_by_user(user_id)

        self.assertEqual([str(t.id) for t in result], [str(live_token.id)])


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


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class TenantIsolationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0021: proves `TenantRegionScope` bound at UoW construction is actually enforced by
    `SqlAlchemyUserRepository` against a real, live database — the audit's confirmed
    `regional_manager`/`support_staff` scope bypass (any in-scope-role caller could list/fetch
    any organization's users, not just their assigned regions/orgs). Mirrors
    `test_transport_ops_student_repository.py`'s identical `TenantIsolationRepositoryTests`
    shape. Also proves `get_by_email`/`get_by_phone` stay deliberately unscoped — login must
    resolve a principal before any scope is known."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self.org_a = self.id_generator.new_id()
        self.org_b = self.id_generator.new_id()
        self._created_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_ids:
                await conn.execute(
                    text("DELETE FROM users WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(
        self, *, scope: TenantRegionScope | None = None
    ) -> SqlAlchemyIamUnitOfWork:
        uow = SqlAlchemyIamUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )
        if scope is not None:
            uow.scope = scope
        return uow

    async def _seed_user(
        self, *, organization_id: str | None, role: Role = Role.ORG_ADMIN
    ) -> str:
        async with self._new_uow() as uow:
            user = User.invite(
                id=UserId(self.id_generator.new_id()),
                organization_id=organization_id,
                role=role,
                email=Email(f"tenant-test-{uuid.uuid4().hex[:10]}@example.com"),
                phone=None,
                full_name=f"Tenant Test {self.tag}",
                clock=self.clock,
            )
            uow.users.add(user)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(user.id))
            return str(user.id)

    async def test_org_a_cannot_get_org_bs_user_by_id(self) -> None:
        user_b = await self._seed_user(organization_id=self.org_b)

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            result = await uow.users.get(UserId(user_b))

        self.assertIsNone(result)

    async def test_org_a_can_still_get_its_own_user_by_id(self) -> None:
        user_a = await self._seed_user(organization_id=self.org_a)

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            result = await uow.users.get(UserId(user_a))

        self.assertIsNotNone(result)
        self.assertEqual(str(result.id), user_a)

    async def test_org_a_list_all_excludes_org_bs_users(self) -> None:
        user_a = await self._seed_user(organization_id=self.org_a)
        user_b = await self._seed_user(organization_id=self.org_b)

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            visible = await uow.users.list_all()

        visible_ids = {str(u.id) for u in visible}
        self.assertIn(user_a, visible_ids)
        self.assertNotIn(user_b, visible_ids)

    async def test_org_a_cannot_bypass_scope_via_organization_id_filter(self) -> None:
        """"Organization A cannot search Organization B's data" — a client-supplied
        `filter[organization_id]=<org B>` must not override the bound scope."""
        await self._seed_user(organization_id=self.org_b)

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            page = await uow.users.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[
                    FilterCondition(field="organization_id", op="eq", value=self.org_b)
                ],
                search=None,
            )

        self.assertEqual(page.total, 0)
        self.assertEqual(page.data, [])

    async def test_scoped_listing_also_excludes_platform_staff_accounts(self) -> None:
        """A side effect flagged in `infra/repositories.py`'s own docstring, not a new gap:
        `UserModel.organization_id` is nullable for platform-staff roles, and `NULL` never
        matches `IN (...)`, so a `regional_manager`/`support_staff`'s now-scoped listing also
        can no longer see *other* platform-staff accounts — strictly a narrowing."""
        org_scoped = await self._seed_user(organization_id=self.org_a)
        platform_staff = await self._seed_user(
            organization_id=None, role=Role.SUPPORT_STAFF
        )

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            visible = await uow.users.list_all()

        visible_ids = {str(u.id) for u in visible}
        self.assertIn(org_scoped, visible_ids)
        self.assertNotIn(platform_staff, visible_ids)

    async def test_founder_unrestricted_scope_sees_both_organizations(self) -> None:
        user_a = await self._seed_user(organization_id=self.org_a)
        user_b = await self._seed_user(organization_id=self.org_b)

        unrestricted = TenantRegionScope(organization_ids=None)
        async with self._new_uow(scope=unrestricted) as uow:
            visible = await uow.users.list_all()

        visible_ids = {str(u.id) for u in visible}
        self.assertIn(user_a, visible_ids)
        self.assertIn(user_b, visible_ids)

    async def test_get_by_email_stays_unscoped_for_login(self) -> None:
        """`get_by_email`/`get_by_phone` must never be scope-filtered — login has no
        `Principal`/scope to resolve until *after* this exact lookup succeeds."""
        user_b = await self._seed_user(organization_id=self.org_b)
        async with self._new_uow() as uow:
            seeded = await uow.users.get(UserId(user_b))

        scope_a = TenantRegionScope(organization_ids=frozenset({self.org_a}))
        async with self._new_uow(scope=scope_a) as uow:
            result = await uow.users.get_by_email(seeded.email)

        self.assertIsNotNone(result)
        self.assertEqual(str(result.id), user_b)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class AccountLockoutRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Priority 1 Item 3 (PROJECT_STATUS.md): the full account-lockout round trip against a
    real, migrated Postgres database — `AuthApplicationService.login()` driven by the real
    `SqlAlchemyIamUnitOfWork`, not the in-memory fakes `tests/unit/test_iam_application.py`
    uses. Proves the new `failed_login_attempts`/`locked_until` columns (migration
    `d4fbe03f2b94`) actually persist and round-trip through `infra/mappers.py`, not just that
    the domain/application logic is internally consistent."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.hasher = Pbkdf2PasswordHasher(iterations=1_000)
        self.tag = uuid.uuid4().hex[:8]
        self._created_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_ids:
                # A successful login (the unlock test) issues a refresh_tokens row with no ON
                # DELETE CASCADE to users (migration 8ffa6434d344) - delete the child rows
                # first, mirroring RefreshTokenRepositoryRoundTripTests.asyncTearDown's own
                # established pattern above.
                await conn.execute(
                    text("DELETE FROM refresh_tokens WHERE user_id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
                await conn.execute(
                    text("DELETE FROM users WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyIamUnitOfWork:
        return SqlAlchemyIamUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    def _make_service(
        self, clock: Clock, *, max_attempts: int = 3, lockout_minutes: int = 15
    ) -> AuthApplicationService:
        token_service = JwtTokenService(
            secret_key="integration-test-secret-not-for-production",
            algorithm="HS256",
            access_token_ttl_seconds=900,
            refresh_token_ttl_seconds=1_209_600,
            clock=clock,
        )
        return AuthApplicationService(
            clock=clock,
            id_generator=self.id_generator,
            token_service=token_service,
            password_hasher=self.hasher,
            session_cap_port=_FixedSessionCapPort(),
            lockout_settings=LockoutSettings(
                max_failed_attempts=max_attempts,
                lockout_duration_minutes=lockout_minutes,
            ),
        )

    async def _seed_active_user(self, *, password: str) -> str:
        async with self._new_uow() as uow:
            user = User.invite(
                id=UserId(self.id_generator.new_id()),
                organization_id=None,
                role=Role.FOUNDER,
                email=Email(f"lockout-live-{self.tag}@example.com"),
                phone=None,
                full_name=f"Lockout Live Test {self.tag}",
                clock=SystemClock(),
            )
            user.activate(clock=SystemClock())
            user.change_password_hash(self.hasher.hash(password), clock=SystemClock())
            uow.users.add(user)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(user.id))
            return str(user.id)

    async def test_repeated_failures_persist_the_counter_across_separate_requests(
        self,
    ) -> None:
        # `AuthApplicationService.login()` already manages its own `async with uow:` block
        # internally (`application/services.py`) — each simulated "separate HTTP request"
        # below passes a freshly *constructed but not yet entered* UoW, exactly like every
        # other caller of `login()` (`interfaces/http`, `tests/unit/test_iam_application.py`'s
        # fakes) already does. Wrapping the call in another `async with self._new_uow() as
        # uow:` here would double-enter the session (`SqlAlchemyUnitOfWork.__aenter__`
        # overwrites `self._session`), which is why every call below uses a plain `uow =
        # self._new_uow()` instead.
        clock = _FixedClock(SystemClock().now())
        await self._seed_active_user(password="correct-password")
        service = self._make_service(clock, max_attempts=3)

        for _ in range(2):
            with self.assertRaises(AuthenticationError):
                await service.login(
                    LoginCommand(
                        email=f"lockout-live-{self.tag}@example.com",
                        phone=None,
                        plain_password="wrong-password",
                    ),
                    uow=self._new_uow(),
                )

        async with self._new_uow() as uow:
            reloaded = await uow.users.get_by_email(
                Email(f"lockout-live-{self.tag}@example.com")
            )
        self.assertEqual(reloaded.failed_login_attempts, 2)
        self.assertIsNone(reloaded.locked_until)

    async def test_reaching_the_threshold_locks_the_account_in_the_database(self) -> None:
        clock = _FixedClock(SystemClock().now())
        await self._seed_active_user(password="correct-password")
        service = self._make_service(clock, max_attempts=3, lockout_minutes=15)

        for _ in range(3):
            with self.assertRaises(AuthenticationError):
                await service.login(
                    LoginCommand(
                        email=f"lockout-live-{self.tag}@example.com",
                        phone=None,
                        plain_password="wrong-password",
                    ),
                    uow=self._new_uow(),
                )

        async with self._new_uow() as uow:
            reloaded = await uow.users.get_by_email(
                Email(f"lockout-live-{self.tag}@example.com")
            )
        self.assertEqual(reloaded.failed_login_attempts, 3)
        self.assertIsNotNone(reloaded.locked_until)
        self.assertTrue(reloaded.is_locked(now=clock.now()))

    async def test_locked_account_rejects_the_correct_password_via_real_db(self) -> None:
        clock = _FixedClock(SystemClock().now())
        await self._seed_active_user(password="correct-password")
        service = self._make_service(clock, max_attempts=3, lockout_minutes=15)

        for _ in range(3):
            with self.assertRaises(AuthenticationError):
                await service.login(
                    LoginCommand(
                        email=f"lockout-live-{self.tag}@example.com",
                        phone=None,
                        plain_password="wrong-password",
                    ),
                    uow=self._new_uow(),
                )

        with self.assertRaises(AccountLockedError):
            await service.login(
                LoginCommand(
                    email=f"lockout-live-{self.tag}@example.com",
                    phone=None,
                    plain_password="correct-password",
                ),
                uow=self._new_uow(),
            )

    async def test_account_unlocks_in_the_database_once_the_window_elapses(self) -> None:
        clock = _FixedClock(SystemClock().now())
        await self._seed_active_user(password="correct-password")
        service = self._make_service(clock, max_attempts=3, lockout_minutes=15)

        for _ in range(3):
            with self.assertRaises(AuthenticationError):
                await service.login(
                    LoginCommand(
                        email=f"lockout-live-{self.tag}@example.com",
                        phone=None,
                        plain_password="wrong-password",
                    ),
                    uow=self._new_uow(),
                )

        # Simulate the lockout window passing — no real sleep, the service's own Clock port is
        # advanced instead (the same pure-port pattern the domain layer already uses).
        clock.set(clock.now() + timedelta(minutes=15, seconds=1))

        result = await service.login(
            LoginCommand(
                email=f"lockout-live-{self.tag}@example.com",
                phone=None,
                plain_password="correct-password",
            ),
            uow=self._new_uow(),
        )
        self.assertTrue(result.access_token)

        async with self._new_uow() as uow:
            reloaded = await uow.users.get_by_email(
                Email(f"lockout-live-{self.tag}@example.com")
            )
        self.assertEqual(reloaded.failed_login_attempts, 0)
        self.assertIsNone(reloaded.locked_until)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class SessionCapRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0019: the full concurrent-session-cap round trip against a real, migrated Postgres
    database — `AuthApplicationService.login()`/`.refresh()`/`.list_sessions()`/
    `.revoke_session()` driven by the real `SqlAlchemyIamUnitOfWork`, proving the new
    `refresh_tokens.device_label` column (migration `4ef3fefb5e8d`) round-trips and that
    eviction/self-service actually persist, not just that the in-memory logic is consistent."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.hasher = Pbkdf2PasswordHasher(iterations=1_000)
        self.tag = uuid.uuid4().hex[:8]
        self._created_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_ids:
                await conn.execute(
                    text("DELETE FROM refresh_tokens WHERE user_id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
                await conn.execute(
                    text("DELETE FROM users WHERE id = ANY(:ids)"),
                    {"ids": self._created_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyIamUnitOfWork:
        return SqlAlchemyIamUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    def _make_service(
        self, clock: Clock, *, max_sessions: int = 100
    ) -> AuthApplicationService:
        token_service = JwtTokenService(
            secret_key="integration-test-secret-not-for-production",
            algorithm="HS256",
            access_token_ttl_seconds=900,
            refresh_token_ttl_seconds=1_209_600,
            clock=clock,
        )
        return AuthApplicationService(
            clock=clock,
            id_generator=self.id_generator,
            token_service=token_service,
            password_hasher=self.hasher,
            session_cap_port=_FixedSessionCapPort(max_sessions=max_sessions),
        )

    async def _seed_active_user(self, *, password: str) -> UserId:
        async with self._new_uow() as uow:
            user = User.invite(
                id=UserId(self.id_generator.new_id()),
                organization_id=None,
                role=Role.FOUNDER,
                email=Email(f"session-cap-live-{self.tag}@example.com"),
                phone=None,
                full_name=f"Session Cap Live Test {self.tag}",
                clock=SystemClock(),
            )
            user.activate(clock=SystemClock())
            user.change_password_hash(self.hasher.hash(password), clock=SystemClock())
            uow.users.add(user)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            self._created_ids.append(str(user.id))
            return user.id

    async def _seed_refresh_token(
        self, *, user_id: UserId, issued_at, expires_at
    ) -> RefreshTokenId:
        token = RefreshToken(
            id=RefreshTokenId(self.id_generator.new_id()),
            user_id=user_id,
            token_hash=hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest(),
            issued_at=issued_at,
            expires_at=expires_at,
        )
        async with self._new_uow() as uow:
            uow.refresh_tokens.add(token)
            await uow.commit()
        return token.id

    async def test_login_past_the_cap_revokes_the_oldest_session_in_the_database(
        self,
    ) -> None:
        now = SystemClock().now()
        user_id = await self._seed_active_user(password="correct-password")
        oldest_id = await self._seed_refresh_token(
            user_id=user_id, issued_at=now - timedelta(days=2), expires_at=now + timedelta(days=12)
        )
        newer_id = await self._seed_refresh_token(
            user_id=user_id, issued_at=now - timedelta(days=1), expires_at=now + timedelta(days=13)
        )
        service = self._make_service(_FixedClock(now), max_sessions=2)

        await service.login(
            LoginCommand(
                email=f"session-cap-live-{self.tag}@example.com",
                phone=None,
                plain_password="correct-password",
            ),
            uow=self._new_uow(),
        )

        # Re-fetched via a brand-new `SqlAlchemyIamUnitOfWork`/session (not the one `login()`
        # itself used) — proves the revocation is real, persisted database state, not just an
        # in-memory side effect of the call above.
        async with self._new_uow() as uow:
            oldest = await uow.refresh_tokens.get(oldest_id)
            newer = await uow.refresh_tokens.get(newer_id)
        self.assertTrue(oldest.is_revoked)
        self.assertFalse(newer.is_revoked)

    async def test_list_and_revoke_sessions_round_trip_through_real_postgres(self) -> None:
        now = SystemClock().now()
        user_id = await self._seed_active_user(password="correct-password")
        token_id = await self._seed_refresh_token(
            user_id=user_id, issued_at=now - timedelta(hours=1), expires_at=now + timedelta(days=14)
        )
        service = self._make_service(_FixedClock(now))

        sessions = await service.list_sessions(
            ListSessionsQuery(user_id=str(user_id)), uow=self._new_uow()
        )
        self.assertEqual([s.id for s in sessions], [str(token_id)])

        await service.revoke_session(
            RevokeSessionCommand(user_id=str(user_id), session_id=str(token_id)),
            uow=self._new_uow(),
        )

        sessions_after = await service.list_sessions(
            ListSessionsQuery(user_id=str(user_id)), uow=self._new_uow()
        )
        self.assertEqual(sessions_after, [])

    async def test_revoke_session_for_another_user_raises_not_found_via_real_postgres(
        self,
    ) -> None:
        now = SystemClock().now()
        owner_id = await self._seed_active_user(password="correct-password")
        token_id = await self._seed_refresh_token(
            user_id=owner_id, issued_at=now - timedelta(hours=1), expires_at=now + timedelta(days=14)
        )
        service = self._make_service(_FixedClock(now))

        with self.assertRaises(NotFoundError):
            await service.revoke_session(
                RevokeSessionCommand(user_id="01J8Z3K9G6X8YV5T4N2R7QW3ZZ", session_id=str(token_id)),
                uow=self._new_uow(),
            )

        async with self._new_uow() as uow:
            reloaded = await uow.refresh_tokens.get(token_id)
        self.assertFalse(reloaded.is_revoked)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class SessionCapAdapterLiveSettingTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0019: proves the *real* `SystemSettingSessionCapAdapter` (`core/di/
    session_cap_adapter.py`) reads the actual migration-seeded `session_cap` `system_settings`
    row (migration `4ef3fefb5e8d`) via the real DI-wired `PlatformAuditApplicationService` —
    the one genuinely new cross-module read this ADR introduces, and the one piece
    `SessionCapRepositoryTests` above deliberately doesn't exercise (it uses
    `_FixedSessionCapPort` for precise, controlled cap values instead)."""

    async def test_seeded_defaults_are_readable_per_role(self) -> None:
        settings = get_settings()
        container = build_container(settings)
        try:
            port = container.resolve(SessionCapPort)

            self.assertEqual(await port.get_max_sessions(role=Role.PARENT), 3)
            self.assertEqual(await port.get_max_sessions(role=Role.DRIVER), 3)
            self.assertEqual(await port.get_max_sessions(role=Role.ORG_ADMIN), 10)
            self.assertEqual(await port.get_max_sessions(role=Role.FOUNDER), 20)
        finally:
            # `build_container` binds its own `AsyncEngine` singleton (`core/di/bootstrap.py`) —
            # every other engine this file creates is disposed in `asyncTearDown`; this test
            # builds its own container ad hoc (the only one in this file), so it owns disposing
            # it too, rather than leaking a connection pool.
            await container.resolve(AsyncEngine).dispose()


if __name__ == "__main__":
    unittest.main()
