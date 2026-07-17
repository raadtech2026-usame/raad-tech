"""Application-layer tests for `iam`'s `UserApplicationService`/`AuthApplicationService`.
Stdlib `unittest` — no `pytest`, matching `test_transport_ops_student_application.py`'s
precedent. In-memory fake `IamUnitOfWork`/repositories — no SQLAlchemy, no FastAPI, no real
database. `AuthApplicationService` tests use the real `JwtTokenService`/`Pbkdf2PasswordHasher`
(both stdlib-only, already-shipped concrete implementations) rather than fakes, since the
login/refresh flow's correctness depends on real signing/hashing behavior, not just call
counts.

Covers: command validation, DTO mapping, service orchestration, validator behavior (duplicate
email/phone rejection), and the authentication error paths (wrong password, inactive account,
revoked/expired/reused refresh token).
"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timedelta, timezone

from raad.core.errors.exceptions import (
    AuthenticationError,
    ConflictError,
    DomainError,
    NotFoundError,
)
from raad.core.ids.generator import IdGenerator
from raad.core.security.password_hashing import Pbkdf2PasswordHasher
from raad.core.security.password_policy import PasswordPolicy
from raad.core.security.tokens import JwtTokenService
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.iam.application.commands import (
    ActivateUserCommand,
    ChangePasswordCommand,
    DisableMfaCommand,
    DisableUserCommand,
    EnableMfaCommand,
    InviteUserCommand,
    LoginCommand,
    LogoutCommand,
    RefreshAccessTokenCommand,
)
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.queries import GetUserByIdQuery, UserDTO
from raad.modules.iam.application.services import (
    AuthApplicationService,
    UserApplicationService,
)
from raad.modules.iam.domain.entities import RefreshToken, User
from raad.modules.iam.domain.repositories import RefreshTokenRepository, UserRepository
from raad.modules.iam.domain.value_objects import (
    Email,
    PhoneNumber,
    RefreshTokenId,
    UserId,
    UserStatus,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
NON_EXISTENT_USER_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class SequentialIdGenerator(IdGenerator):
    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"  # 20 chars

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


class InMemoryUserRepository(UserRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, User] = {}

    async def get(self, user_id: UserId) -> User | None:
        return self.by_id.get(str(user_id))

    async def get_by_email(self, email: Email) -> User | None:
        for user in self.by_id.values():
            if user.email is not None and str(user.email) == str(email):
                return user
        return None

    async def get_by_phone(self, phone: PhoneNumber) -> User | None:
        for user in self.by_id.values():
            if user.phone is not None and str(user.phone) == str(phone):
                return user
        return None

    def add(self, user: User) -> None:
        self.by_id[str(user.id)] = user


class InMemoryRefreshTokenRepository(RefreshTokenRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, RefreshToken] = {}

    async def get(self, token_id: RefreshTokenId) -> RefreshToken | None:
        return self.by_id.get(str(token_id))

    async def get_by_token_hash(self, token_hash: str) -> RefreshToken | None:
        for token in self.by_id.values():
            if token.token_hash == token_hash:
                return token
        return None

    def add(self, refresh_token: RefreshToken) -> None:
        self.by_id[str(refresh_token.id)] = refresh_token


class FakeIamUnitOfWork(IamUnitOfWork):
    def __init__(
        self,
        users: InMemoryUserRepository,
        refresh_tokens: InMemoryRefreshTokenRepository,
    ) -> None:
        self.users = users
        self.refresh_tokens = refresh_tokens
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def make_actor() -> Principal:
    return Principal(user_id="admin-1", role=Role.FOUNDER, org_id=None)


def make_user_service() -> tuple[UserApplicationService, FakeIamUnitOfWork]:
    policy = PasswordPolicy(
        _PasswordPolicySettingsStub(
            min_length=8,
            require_uppercase=True,
            require_lowercase=True,
            require_digit=True,
            require_special=False,
        )
    )
    service = UserApplicationService(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_generator=SequentialIdGenerator(),
        password_hasher=Pbkdf2PasswordHasher(iterations=1_000),  # cheap for test speed
        password_policy=policy,
    )
    uow = FakeIamUnitOfWork(InMemoryUserRepository(), InMemoryRefreshTokenRepository())
    return service, uow


class _PasswordPolicySettingsStub:
    """Mirrors `core.config.settings.PasswordPolicySettings`'s field shape without importing
    the full `Settings` tree (constructor-friendly, avoids env-var parsing entirely)."""

    def __init__(
        self,
        *,
        min_length: int,
        require_uppercase: bool,
        require_lowercase: bool,
        require_digit: bool,
        require_special: bool,
    ) -> None:
        self.min_length = min_length
        self.require_uppercase = require_uppercase
        self.require_lowercase = require_lowercase
        self.require_digit = require_digit
        self.require_special = require_special


def make_auth_service(
    clock: Clock,
) -> tuple[AuthApplicationService, FakeIamUnitOfWork, Pbkdf2PasswordHasher]:
    hasher = Pbkdf2PasswordHasher(iterations=1_000)
    token_service = JwtTokenService(
        secret_key="test-secret-key-not-for-production",
        algorithm="HS256",
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=1_209_600,
        clock=clock,
    )
    service = AuthApplicationService(
        clock=clock,
        id_generator=SequentialIdGenerator(),
        token_service=token_service,
        password_hasher=hasher,
    )
    uow = FakeIamUnitOfWork(InMemoryUserRepository(), InMemoryRefreshTokenRepository())
    return service, uow, hasher


# --- Commands --------------------------------------------------------------------------


class CommandImmutabilityTests(unittest.TestCase):
    def test_invite_command_is_frozen(self) -> None:
        command = InviteUserCommand(
            organization_id=None,
            role=Role.FOUNDER,
            email="a@b.com",
            phone=None,
            full_name="Someone",
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.full_name = "Other"  # type: ignore[misc]

    def test_login_command_is_frozen(self) -> None:
        command = LoginCommand(email="a@b.com", phone=None, plain_password="x")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.email = "other@b.com"  # type: ignore[misc]


# --- UserApplicationService: invite / duplicate rejection ---------------------------------


class InviteUserTests(unittest.IsolatedAsyncioTestCase):
    async def test_invite_user_adds_to_repository_and_commits(self) -> None:
        service, uow = make_user_service()
        dto = await service.invite_user(
            InviteUserCommand(
                organization_id=None,
                role=Role.FOUNDER,
                email="founder@example.com",
                phone=None,
                full_name="Founder One",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(dto.status, "invited")
        self.assertEqual(uow.commit_count, 1)
        self.assertIn(dto.id, uow.users.by_id)

    async def test_invite_user_records_user_invited_event(self) -> None:
        service, uow = make_user_service()
        await service.invite_user(
            InviteUserCommand(
                organization_id=None,
                role=Role.FOUNDER,
                email="founder@example.com",
                phone=None,
                full_name="Founder One",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(uow.recorded_events[0].event_type, "UserInvited")

    async def test_duplicate_email_is_rejected(self) -> None:
        """Safety-critical: Database Design §4.3's global email-uniqueness constraint, enforced
        at the application layer via `ensure_email_available` before the domain is even
        touched."""
        service, uow = make_user_service()
        command = InviteUserCommand(
            organization_id=None,
            role=Role.FOUNDER,
            email="dup@example.com",
            phone=None,
            full_name="First",
            actor=make_actor(),
        )
        await service.invite_user(command, uow=uow)

        with self.assertRaises(ConflictError):
            await service.invite_user(
                InviteUserCommand(
                    organization_id=None,
                    role=Role.FOUNDER,
                    email="dup@example.com",
                    phone=None,
                    full_name="Second",
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.users.by_id), 1)  # second invite never persisted

    async def test_duplicate_email_rejected_case_insensitively(self) -> None:
        # Email value object normalizes case (domain test already covers this) - confirm the
        # application-layer duplicate check inherits that normalization end-to-end.
        service, uow = make_user_service()
        await service.invite_user(
            InviteUserCommand(
                organization_id=None,
                role=Role.FOUNDER,
                email="Dup@Example.com",
                phone=None,
                full_name="First",
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await service.invite_user(
                InviteUserCommand(
                    organization_id=None,
                    role=Role.FOUNDER,
                    email="dup@example.com",
                    phone=None,
                    full_name="Second",
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_duplicate_phone_is_rejected(self) -> None:
        service, uow = make_user_service()
        await service.invite_user(
            InviteUserCommand(
                organization_id=None,
                role=Role.FOUNDER,
                email=None,
                phone="+252700000000",
                full_name="First",
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await service.invite_user(
                InviteUserCommand(
                    organization_id=None,
                    role=Role.FOUNDER,
                    email=None,
                    phone="+252700000000",
                    full_name="Second",
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_different_email_and_phone_both_succeed(self) -> None:
        service, uow = make_user_service()
        await service.invite_user(
            InviteUserCommand(
                organization_id=None,
                role=Role.FOUNDER,
                email="a@example.com",
                phone=None,
                full_name="First",
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.invite_user(
            InviteUserCommand(
                organization_id=None,
                role=Role.FOUNDER,
                email="b@example.com",
                phone=None,
                full_name="Second",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(len(uow.users.by_id), 2)

    async def test_invite_org_scoped_role_without_organization_id_raises_domain_error(
        self,
    ) -> None:
        """Role validation: org-scoped roles (org_admin/driver/parent) require an
        organization_id - the domain's own invariant, reached (not bypassed) by the
        application layer."""
        service, uow = make_user_service()
        with self.assertRaises(DomainError):
            await service.invite_user(
                InviteUserCommand(
                    organization_id=None,
                    role=Role.ORG_ADMIN,
                    email="admin@example.com",
                    phone=None,
                    full_name="Org Admin",
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 0)

    async def test_invite_staff_role_with_organization_id_raises_domain_error(
        self,
    ) -> None:
        service, uow = make_user_service()
        with self.assertRaises(DomainError):
            await service.invite_user(
                InviteUserCommand(
                    organization_id=VALID_ORG_ULID,
                    role=Role.FOUNDER,
                    email="founder@example.com",
                    phone=None,
                    full_name="Founder",
                    actor=make_actor(),
                ),
                uow=uow,
            )


class UserStatusTransitionApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def _invited_user_id(self, service: UserApplicationService, uow) -> str:
        dto = await service.invite_user(
            InviteUserCommand(
                organization_id=None,
                role=Role.FOUNDER,
                email="founder@example.com",
                phone=None,
                full_name="Founder",
                actor=make_actor(),
            ),
            uow=uow,
        )
        uow.recorded_events.clear()
        return dto.id

    async def test_activate_user_changes_status(self) -> None:
        service, uow = make_user_service()
        user_id = await self._invited_user_id(service, uow)
        dto = await service.activate_user(
            ActivateUserCommand(user_id=user_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "active")

    async def test_disable_user_changes_status(self) -> None:
        service, uow = make_user_service()
        user_id = await self._invited_user_id(service, uow)
        await service.activate_user(
            ActivateUserCommand(user_id=user_id, actor=make_actor()), uow=uow
        )
        dto = await service.disable_user(
            DisableUserCommand(user_id=user_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "disabled")

    async def test_transition_on_missing_user_raises_not_found(self) -> None:
        service, uow = make_user_service()
        with self.assertRaises(NotFoundError):
            await service.activate_user(
                ActivateUserCommand(user_id=NON_EXISTENT_USER_ID, actor=make_actor()),
                uow=uow,
            )

    async def test_change_password_enforces_policy(self) -> None:
        service, uow = make_user_service()
        user_id = await self._invited_user_id(service, uow)
        from raad.core.errors.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            await service.change_password(
                ChangePasswordCommand(
                    user_id=user_id, new_plain_password="weak", actor=make_actor()
                ),
                uow=uow,
            )

    async def test_change_password_stores_verifiable_hash(self) -> None:
        service, uow = make_user_service()
        user_id = await self._invited_user_id(service, uow)
        await service.change_password(
            ChangePasswordCommand(
                user_id=user_id, new_plain_password="StrongPass1", actor=make_actor()
            ),
            uow=uow,
        )
        stored = uow.users.by_id[user_id]
        hasher = Pbkdf2PasswordHasher(iterations=1_000)
        self.assertTrue(hasher.verify("StrongPass1", stored.password_hash))

    async def test_enable_then_disable_mfa_round_trip(self) -> None:
        service, uow = make_user_service()
        user_id = await self._invited_user_id(service, uow)
        dto = await service.enable_mfa(
            EnableMfaCommand(user_id=user_id, actor=make_actor()), uow=uow
        )
        self.assertTrue(dto.mfa_enabled)
        dto = await service.disable_mfa(
            DisableMfaCommand(user_id=user_id, actor=make_actor()), uow=uow
        )
        self.assertFalse(dto.mfa_enabled)


class GetUserByIdApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_dto_for_existing_user(self) -> None:
        service, uow = make_user_service()
        dto = await service.invite_user(
            InviteUserCommand(
                organization_id=None,
                role=Role.FOUNDER,
                email="founder@example.com",
                phone=None,
                full_name="Founder",
                actor=make_actor(),
            ),
            uow=uow,
        )
        fetched = await service.get_user_by_id(
            GetUserByIdQuery(user_id=dto.id), uow=uow
        )
        self.assertIsInstance(fetched, UserDTO)
        self.assertEqual(fetched.id, dto.id)

    async def test_raises_not_found_for_missing_user(self) -> None:
        service, uow = make_user_service()
        with self.assertRaises(NotFoundError):
            await service.get_user_by_id(
                GetUserByIdQuery(user_id=NON_EXISTENT_USER_ID), uow=uow
            )


# --- AuthApplicationService: login / refresh / logout --------------------------------------


class LoginTests(unittest.IsolatedAsyncioTestCase):
    async def _active_user_with_password(
        self, uow: FakeIamUnitOfWork, hasher: Pbkdf2PasswordHasher, password: str
    ) -> User:
        user = User(
            id=UserId("01J8Z3K9G6X8YV5T4N2R7QW3M1"),
            organization_id=None,
            role=Role.FOUNDER,
            email=Email("login@example.com"),
            phone=None,
            full_name="Login User",
            status=UserStatus.ACTIVE,
            password_hash=hasher.hash(password),
        )
        uow.users.add(user)
        return user

    async def test_login_with_correct_credentials_succeeds(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        service, uow, hasher = make_auth_service(clock)
        await self._active_user_with_password(uow, hasher, "correct-password")

        result = await service.login(
            LoginCommand(
                email="login@example.com", phone=None, plain_password="correct-password"
            ),
            uow=uow,
        )
        self.assertTrue(result.access_token)
        self.assertTrue(result.refresh_token)
        self.assertEqual(result.user.email, "login@example.com")
        self.assertEqual(len(uow.refresh_tokens.by_id), 1)

    async def test_login_with_wrong_password_raises_authentication_error(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        service, uow, hasher = make_auth_service(clock)
        await self._active_user_with_password(uow, hasher, "correct-password")

        with self.assertRaises(AuthenticationError):
            await service.login(
                LoginCommand(
                    email="login@example.com",
                    phone=None,
                    plain_password="wrong-password",
                ),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 0)

    async def test_login_with_unknown_email_raises_authentication_error(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        service, uow, _hasher = make_auth_service(clock)

        with self.assertRaises(AuthenticationError):
            await service.login(
                LoginCommand(
                    email="nobody@example.com", phone=None, plain_password="x"
                ),
                uow=uow,
            )

    async def test_login_with_disabled_account_raises_authentication_error(
        self,
    ) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        service, uow, hasher = make_auth_service(clock)
        user = await self._active_user_with_password(uow, hasher, "correct-password")
        user.status = UserStatus.DISABLED

        with self.assertRaises(AuthenticationError):
            await service.login(
                LoginCommand(
                    email="login@example.com",
                    phone=None,
                    plain_password="correct-password",
                ),
                uow=uow,
            )


class RefreshTokenFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_rotates_token_and_revokes_the_old_one(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        service, uow, hasher = make_auth_service(clock)
        user = User(
            id=UserId("01J8Z3K9G6X8YV5T4N2R7QW3M2"),
            organization_id=None,
            role=Role.FOUNDER,
            email=Email("refresh@example.com"),
            phone=None,
            full_name="Refresh User",
            status=UserStatus.ACTIVE,
            password_hash=hasher.hash("pw"),
        )
        uow.users.add(user)
        login_result = await service.login(
            LoginCommand(email="refresh@example.com", phone=None, plain_password="pw"),
            uow=uow,
        )
        old_refresh_token = login_result.refresh_token

        new_result = await service.refresh(
            RefreshAccessTokenCommand(refresh_token=old_refresh_token), uow=uow
        )
        self.assertNotEqual(new_result.refresh_token, old_refresh_token)
        self.assertEqual(len(uow.refresh_tokens.by_id), 2)  # old + new both stored

        # The old token must now be revoked - reusing it must fail.
        with self.assertRaises(AuthenticationError):
            await service.refresh(
                RefreshAccessTokenCommand(refresh_token=old_refresh_token), uow=uow
            )

    async def test_refresh_with_garbage_token_raises_authentication_error(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        service, uow, _hasher = make_auth_service(clock)
        with self.assertRaises(AuthenticationError):
            await service.refresh(
                RefreshAccessTokenCommand(refresh_token="not-a-real-token"), uow=uow
            )

    async def test_refresh_with_expired_token_raises_authentication_error(self) -> None:
        issue_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        clock = FixedClock(issue_time)
        service, uow, hasher = make_auth_service(clock)
        user = User(
            id=UserId("01J8Z3K9G6X8YV5T4N2R7QW3M3"),
            organization_id=None,
            role=Role.FOUNDER,
            email=Email("expiry@example.com"),
            phone=None,
            full_name="Expiry User",
            status=UserStatus.ACTIVE,
            password_hash=hasher.hash("pw"),
        )
        uow.users.add(user)
        login_result = await service.login(
            LoginCommand(email="expiry@example.com", phone=None, plain_password="pw"),
            uow=uow,
        )

        # Advance the clock past the refresh token's TTL (14 days) before attempting refresh.
        clock._now = issue_time + timedelta(days=15)
        with self.assertRaises(AuthenticationError):
            await service.refresh(
                RefreshAccessTokenCommand(refresh_token=login_result.refresh_token),
                uow=uow,
            )


class LogoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_logout_revokes_the_presented_token(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        service, uow, hasher = make_auth_service(clock)
        user = User(
            id=UserId("01J8Z3K9G6X8YV5T4N2R7QW3M4"),
            organization_id=None,
            role=Role.FOUNDER,
            email=Email("logout@example.com"),
            phone=None,
            full_name="Logout User",
            status=UserStatus.ACTIVE,
            password_hash=hasher.hash("pw"),
        )
        uow.users.add(user)
        login_result = await service.login(
            LoginCommand(email="logout@example.com", phone=None, plain_password="pw"),
            uow=uow,
        )

        await service.logout(
            LogoutCommand(refresh_token=login_result.refresh_token), uow=uow
        )

        with self.assertRaises(AuthenticationError):
            await service.refresh(
                RefreshAccessTokenCommand(refresh_token=login_result.refresh_token),
                uow=uow,
            )

    async def test_logout_with_unknown_token_is_a_no_op_not_an_error(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        service, uow, _hasher = make_auth_service(clock)
        await service.logout(
            LogoutCommand(refresh_token="unknown-token"), uow=uow
        )  # no raise


if __name__ == "__main__":
    unittest.main()
