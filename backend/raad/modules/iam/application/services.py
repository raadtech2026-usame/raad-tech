"""IAM application services (Backend LLD §4.1/§4.3). Thin, orchestration-only handlers —
business rules stay inside the `User`/`RefreshToken` aggregates (`modules/iam/domain`); these
services only: resolve/validate pre-conditions, load aggregates via the repositories bound to
`IamUnitOfWork`, invoke domain behavior, record the resulting `DomainEvent`s, commit, and
return a DTO — the exact skeleton the LLD's §4.3 "transaction & event ordering" steps
describe.

Split into two services by natural API grouping (LLD §16.1: `/auth/*` vs a future user-
management surface), not by aggregate: `AuthApplicationService` spans both `User` and
`RefreshToken` for login/refresh/logout, `UserApplicationService` covers `User` lifecycle
management. Neither depends on FastAPI/SQLAlchemy — dependencies are constructor-injected
ports (`Clock`, `IdGenerator`, `TokenService`, `PasswordHasher`, `PasswordPolicy`), wired by
`core/di` in a later phase.
"""

from __future__ import annotations

import hashlib
import secrets
import string
from datetime import datetime

from raad.core.config.settings import LockoutSettings
from raad.core.errors.exceptions import (
    AccountLockedError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ValidationError,
)
from raad.core.events.base import DomainEvent
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import OffsetPage
from raad.core.policies.session_limit import SessionLimitPolicy
from raad.core.security.claims import TokenType
from raad.core.security.user_agent import parse_device_label
from raad.core.tenancy.principal import Principal, Role
from raad.core.security.password_hashing import PasswordHasher
from raad.core.security.password_policy import PasswordPolicy
from raad.core.security.tokens import TokenService
from raad.core.time.clock import Clock
from raad.modules.iam.application.commands import (
    ActivateUserCommand,
    ChangePasswordCommand,
    CreateUserWithTemporaryPasswordCommand,
    DisableMfaCommand,
    DisableUserCommand,
    EnableMfaCommand,
    GrantRolePermissionCommand,
    InviteUserCommand,
    LoginCommand,
    LogoutCommand,
    RefreshAccessTokenCommand,
    ResetPasswordToTemporaryCommand,
    RevokeRolePermissionCommand,
    RevokeSessionCommand,
)
from raad.modules.iam.application.ports import IamUnitOfWork, SessionCapPort
from raad.modules.iam.application.queries import (
    AuthResultDTO,
    GetUserByIdQuery,
    ListSessionsQuery,
    ListUsersQuery,
    MeDriverProfileDTO,
    MeIdentityDTO,
    MeStudentDTO,
    SessionDTO,
    UserDTO,
    UserStatsDTO,
    refresh_token_to_session_dto,
    user_to_dto,
)
from raad.modules.iam.application.validators import (
    ensure_email_available,
    ensure_phone_available,
)
from raad.modules.iam.domain import events as iam_events
from raad.modules.iam.domain.entities import RefreshToken, User
from raad.modules.iam.domain.value_objects import (
    Email,
    OrganizationId,
    PhoneNumber,
    RefreshTokenId,
    UserId,
    UserStatus,
)

# ADR-0023: MeApplicationService composes transport_ops's own application-layer services only
# (never its domain/infra) — the same legal cross-module composition
# platform_audit.PlatformStatsApplicationService (ADR-0020) already established, confirmed by
# tests/architecture/test_module_boundaries.py Rule 1 (application-layer imports are unflagged;
# only domain/infra reaches are).
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import ListStudentsForParentQuery
from raad.modules.transport_ops.application.services import (
    DriverApplicationService,
    ParentApplicationService,
    StudentParentApplicationService,
)


def _hash_refresh_token(raw_token: str) -> str:
    """SHA-256 hex digest (Database Design §4.5: `token_hash CHAR(64)`) — a fast lookup hash,
    not a slow KDF like `PasswordHasher`: refresh tokens are already high-entropy signed JWTs,
    not user-chosen secrets, so PBKDF2-style stretching isn't needed here."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


_ORG_ADMIN_CREATABLE_ROLES = frozenset({Role.ORG_ADMIN, Role.DRIVER, Role.PARENT})
_TEMPORARY_PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_"
_TEMPORARY_PASSWORD_LENGTH = 16
_TEMPORARY_PASSWORD_MAX_ATTEMPTS = 20


def _enforce_creation_scope(
    *, actor: "object", role: Role, organization_id: str | None
) -> None:
    """ADR-0017/ADR-0003 Extension: the only new authorization restriction this realignment
    introduces on user creation. Applies **only** to an `org_admin` actor — every other actor
    role (`founder`/`regional_manager`/`support_staff`/`finance_staff`) keeps its existing,
    unrestricted invite latitude exactly as before (no approved document restricts it, and this
    codebase does not invent restrictions no document asks for). An `org_admin` may create only
    `org_admin`/`driver`/`parent` — never a platform-staff role — and only within their own
    `organization_id`, mirroring `.claude/rules/security.md` #2's defense-in-depth: this check
    is independent of, and in addition to, the `iam.users.create` RBAC grant itself."""
    from raad.core.tenancy.principal import Principal  # local import avoids a cycle risk

    assert isinstance(actor, Principal)
    if actor.role is not Role.ORG_ADMIN:
        return
    if role not in _ORG_ADMIN_CREATABLE_ROLES:
        raise AuthorizationError(
            f"org_admin may not create a user with role={role.value}."
        )
    if organization_id != actor.org_id:
        raise AuthorizationError(
            "org_admin may only create users within their own organization."
        )


def _generate_temporary_password(policy: PasswordPolicy) -> str:
    """Reuses `PasswordPolicy.validate` itself as the single source of truth for what counts as
    valid, rather than duplicating its rules here — a random high-entropy candidate is generated
    and checked against the caller's actual configured policy, retried a bounded number of times
    (astronomically unlikely to ever need more than one or two attempts at this length/alphabet
    against any policy this codebase's `PasswordPolicySettings` can express)."""
    for _ in range(_TEMPORARY_PASSWORD_MAX_ATTEMPTS):
        candidate = "".join(
            secrets.choice(_TEMPORARY_PASSWORD_ALPHABET)
            for _ in range(_TEMPORARY_PASSWORD_LENGTH)
        )
        try:
            policy.validate(candidate)
        except ValidationError:
            continue
        return candidate
    raise RuntimeError(
        "Unable to generate a policy-compliant temporary password after "
        f"{_TEMPORARY_PASSWORD_MAX_ATTEMPTS} attempts."
    )


class UserApplicationService:
    """User lifecycle use-cases: invite, activate, disable, change password, enable/disable
    MFA, and the `GetUserByIdQuery` read path."""

    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        password_hasher: PasswordHasher,
        password_policy: PasswordPolicy,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._password_hasher = password_hasher
        self._password_policy = password_policy

    async def invite_user(
        self, command: InviteUserCommand, *, uow: IamUnitOfWork
    ) -> UserDTO:
        _enforce_creation_scope(
            actor=command.actor,
            role=command.role,
            organization_id=command.organization_id,
        )
        async with uow:
            email = Email(command.email) if command.email else None
            phone = PhoneNumber(command.phone) if command.phone else None
            if email is not None:
                await ensure_email_available(uow, email)
            if phone is not None:
                await ensure_phone_available(uow, phone)

            user = User.invite(
                id=UserId(self._id_generator.new_id()),
                organization_id=(
                    OrganizationId(command.organization_id)
                    if command.organization_id
                    else None
                ),
                role=command.role,
                email=email,
                phone=phone,
                full_name=command.full_name,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.users.add(user)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            return user_to_dto(user)

    async def create_user_with_temporary_password(
        self,
        command: CreateUserWithTemporaryPasswordCommand,
        *,
        uow: IamUnitOfWork,
    ) -> tuple[UserDTO, str]:
        """ADR-0017/ADR-0003 Extension: creates a `User` that's immediately usable — `invite`
        (status=`invited`, no password) then, in the same transaction, sets a generated
        temporary password and activates it. Returns the plaintext temporary password
        alongside the DTO — the **only** place it is ever available; it is never persisted or
        retrievable again after this call returns."""
        _enforce_creation_scope(
            actor=command.actor,
            role=command.role,
            organization_id=command.organization_id,
        )
        async with uow:
            email = Email(command.email) if command.email else None
            phone = PhoneNumber(command.phone) if command.phone else None
            if email is not None:
                await ensure_email_available(uow, email)
            if phone is not None:
                await ensure_phone_available(uow, phone)

            user = User.invite(
                id=UserId(self._id_generator.new_id()),
                organization_id=(
                    OrganizationId(command.organization_id)
                    if command.organization_id
                    else None
                ),
                role=command.role,
                email=email,
                phone=phone,
                full_name=command.full_name,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            temporary_password = _generate_temporary_password(self._password_policy)
            user.set_temporary_password_hash(
                self._password_hasher.hash(temporary_password),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            user.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.users.add(user)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            return user_to_dto(user), temporary_password

    async def activate_user(
        self, command: ActivateUserCommand, *, uow: IamUnitOfWork
    ) -> UserDTO:
        async with uow:
            user = await self._get_user_or_raise(uow, command.user_id)
            user.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            return user_to_dto(user)

    async def disable_user(
        self, command: DisableUserCommand, *, uow: IamUnitOfWork
    ) -> UserDTO:
        async with uow:
            user = await self._get_user_or_raise(uow, command.user_id)
            user.disable(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            return user_to_dto(user)

    async def change_password(
        self, command: ChangePasswordCommand, *, uow: IamUnitOfWork
    ) -> UserDTO:
        async with uow:
            user = await self._get_user_or_raise(uow, command.user_id)
            self._password_policy.validate(command.new_plain_password)
            new_hash = self._password_hasher.hash(command.new_plain_password)
            user.change_password_hash(
                new_hash, clock=self._clock, actor_id=command.actor.user_id
            )
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            return user_to_dto(user)

    async def reset_password_to_temporary(
        self, command: ResetPasswordToTemporaryCommand, *, uow: IamUnitOfWork
    ) -> tuple[UserDTO, str]:
        """ADR-0017 Amendment: same guarantee as `create_user_with_temporary_password` (the new
        plaintext password is returned exactly once, never persisted/retrievable again) applied
        to an *existing* user instead of a new invite. Also revokes every non-revoked refresh
        token already issued to this user — a reset should not leave a prior session usable."""
        async with uow:
            user = await self._get_user_or_raise(uow, command.user_id)
            temporary_password = _generate_temporary_password(self._password_policy)
            user.set_temporary_password_hash(
                self._password_hasher.hash(temporary_password),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            active_tokens = await uow.refresh_tokens.list_by_user(user.id)
            for token in active_tokens:
                token.revoke(clock=self._clock)

            events = user.pull_domain_events()
            for token in active_tokens:
                events += token.pull_domain_events()
            uow.record_events(events)
            await uow.commit()
            return user_to_dto(user), temporary_password

    async def enable_mfa(
        self, command: EnableMfaCommand, *, uow: IamUnitOfWork
    ) -> UserDTO:
        async with uow:
            user = await self._get_user_or_raise(uow, command.user_id)
            user.enable_mfa(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            return user_to_dto(user)

    async def disable_mfa(
        self, command: DisableMfaCommand, *, uow: IamUnitOfWork
    ) -> UserDTO:
        async with uow:
            user = await self._get_user_or_raise(uow, command.user_id)
            user.disable_mfa(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(user.pull_domain_events())
            await uow.commit()
            return user_to_dto(user)

    async def get_user_by_id(
        self, query: GetUserByIdQuery, *, uow: IamUnitOfWork
    ) -> UserDTO:
        async with uow:
            user = await self._get_user_or_raise(uow, query.user_id)
            return user_to_dto(user)

    async def list_users(
        self, query: ListUsersQuery, *, uow: IamUnitOfWork
    ) -> OffsetPage[UserDTO]:
        """Backs `GET /users` (API Contracts §4.1/§7/§8)."""
        async with uow:
            page = await uow.users.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[user_to_dto(u) for u in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    async def get_user_stats(
        self, *, since_today: datetime, mau_since: datetime, uow: IamUnitOfWork
    ) -> UserStatsDTO:
        """ADR-0020: active-user breakdown + MAU + "New Users Today" KPIs, backing
        `platform_audit.PlatformStatsApplicationService`. Both date boundaries are resolved by
        the caller once, for the whole composed response (`OrganizationApplicationService.
        get_organization_stats`'s own docstring gives the full "policy resolved by caller"
        reasoning)."""
        async with uow:
            by_status = await uow.users.count_by_status()
            monthly_active = await uow.users.count_last_login_after(mau_since)
            created_today = await uow.users.count_created_since(since_today)
            return UserStatsDTO(
                total=sum(by_status.values()),
                by_status=by_status,
                monthly_active=monthly_active,
                created_today=created_today,
            )

    @staticmethod
    async def _get_user_or_raise(uow: IamUnitOfWork, user_id: str) -> User:
        user = await uow.users.get(UserId(user_id))
        if user is None:
            raise NotFoundError(f"User {user_id} not found.")
        return user


class AuthApplicationService:
    """Login/refresh/logout use-cases — the only ones spanning both `User` and
    `RefreshToken`. Refresh-token rotation (LLD-standard practice): each successful `refresh`
    revokes the presented token and issues a brand new one, rather than reusing it."""

    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        token_service: TokenService,
        password_hasher: PasswordHasher,
        session_cap_port: SessionCapPort,
        lockout_settings: LockoutSettings | None = None,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._token_service = token_service
        self._password_hasher = password_hasher
        self._session_cap_port = session_cap_port
        # Defaulted, not required — every existing/future caller that constructs this service
        # without an explicit LockoutSettings (e.g. a test fixture predating Priority 1 Item 3)
        # still gets the documented default policy rather than a constructor break.
        self._lockout_settings = lockout_settings or LockoutSettings()

    async def login(
        self, command: LoginCommand, *, uow: IamUnitOfWork
    ) -> AuthResultDTO:
        async with uow:
            user = await self._find_user_by_identifier(
                uow, command.email, command.phone
            )

            # Checked before spending a bcrypt verify on it, and before the credential check
            # below — a locked account is rejected regardless of whether the password given is
            # actually correct (Priority 1 Item 3).
            if user is not None and user.is_locked(now=self._clock.now()):
                raise AccountLockedError(locked_until=user.locked_until)

            password_ok = (
                user is not None
                and user.password_hash is not None
                and self._password_hasher.verify(
                    command.plain_password, user.password_hash
                )
            )
            if not password_ok:
                if user is not None:
                    # Persisted even though this request ultimately fails — the whole point of
                    # tracking failed attempts is that the count survives across requests.
                    # Safe to commit here and still raise below: SqlAlchemyUnitOfWork.__aexit__
                    # only rolls back when an exception is propagating, and a rollback() called
                    # after an already-completed commit() has nothing left to undo.
                    user.record_failed_login(
                        max_attempts=self._lockout_settings.max_failed_attempts,
                        lockout_duration_minutes=self._lockout_settings.lockout_duration_minutes,
                        clock=self._clock,
                    )
                    uow.record_events(user.pull_domain_events())
                    await uow.commit()
                raise AuthenticationError("Invalid credentials.")
            if user.status is not UserStatus.ACTIVE:
                raise AuthenticationError("Account is not active.")

            # ADR-0019: resolved before `record_login`/token issuance, using data already
            # available at this point — no extra query beyond what the cap check itself needs.
            device_label = parse_device_label(command.user_agent)
            existing_sessions = [
                t
                for t in await uow.refresh_tokens.list_by_user(user.id)
                if not t.is_expired(clock=self._clock)
            ]
            # Flagged interpretive choice: "not seen in the user's last N sessions" (ADR-0019
            # Decision #6) is only meaningful once there *is* session history to compare
            # against — a brand-new user's very first login has none, so treating it as
            # "suspicious" would flag the single most common, entirely legitimate case. Reusing
            # the same `existing_sessions` list already fetched for the cap check below (no
            # extra query, no separate "last N" history concept the ADR itself never defines).
            is_new_device = bool(existing_sessions) and not any(
                t.device_label == device_label and t.ip_address == command.ip_address
                for t in existing_sessions
            )

            revoked_events: list[DomainEvent] = []
            max_sessions = await self._session_cap_port.get_max_sessions(role=user.role)
            decision = SessionLimitPolicy().evaluate(
                active_session_count=len(existing_sessions) + 1,
                max_sessions=max_sessions,
            )
            if not decision.allowed:
                excess = len(existing_sessions) + 1 - max_sessions
                for stale in sorted(existing_sessions, key=lambda t: t.issued_at)[:excess]:
                    stale.revoke(clock=self._clock)
                    revoked_events += stale.pull_domain_events()

            user.record_login(
                clock=self._clock,
                is_new_device=is_new_device,
                device_label=device_label,
                ip_address=command.ip_address,
            )
            token_pair = self._token_service.issue_token_pair(
                subject=str(user.id),
                role=user.role,
                org_id=str(user.organization_id) if user.organization_id else None,
            )
            # Re-derive the refresh token's own expiry from the just-issued JWT itself
            # (`TokenService.decode`), rather than re-deriving TTL config separately here —
            # single source of truth for how long a refresh token actually lives.
            refresh_claims = self._token_service.decode(
                token_pair.refresh_token, expected_type=TokenType.REFRESH
            )
            refresh_entity = RefreshToken.issue(
                id=RefreshTokenId(self._id_generator.new_id()),
                user_id=user.id,
                token_hash=_hash_refresh_token(token_pair.refresh_token),
                expires_at=refresh_claims.expires_at,
                clock=self._clock,
                user_agent=command.user_agent,
                ip_address=command.ip_address,
                device_label=device_label,
            )
            uow.refresh_tokens.add(refresh_entity)
            uow.record_events(
                user.pull_domain_events()
                + revoked_events
                + refresh_entity.pull_domain_events()
            )
            await uow.commit()
            return AuthResultDTO(
                access_token=token_pair.access_token,
                refresh_token=token_pair.refresh_token,
                token_type=token_pair.token_type,
                expires_in=token_pair.expires_in,
                user=user_to_dto(user),
            )

    async def refresh(
        self, command: RefreshAccessTokenCommand, *, uow: IamUnitOfWork
    ) -> AuthResultDTO:
        async with uow:
            # Verifies signature/expiry/token_type first — a structurally invalid token never
            # reaches the repository lookup below.
            self._token_service.decode(
                command.refresh_token, expected_type=TokenType.REFRESH
            )

            token_hash = _hash_refresh_token(command.refresh_token)
            stored = await uow.refresh_tokens.get_by_token_hash(token_hash)
            if (
                stored is None
                or stored.is_revoked
                or stored.is_expired(clock=self._clock)
            ):
                raise AuthenticationError(
                    "Refresh token is invalid or has been revoked."
                )

            user = await uow.users.get(stored.user_id)
            if user is None or user.status is not UserStatus.ACTIVE:
                raise AuthenticationError("Account is not active.")

            stored.revoke(clock=self._clock)

            # ADR-0019: cap enforcement applies to refresh too ("At POST /auth/login and POST
            # /auth/refresh... after issuing a new RefreshToken"), but rotation is a 1:1
            # replacement, not a net-new session — `stored` (already revoked above, in-memory)
            # is excluded from the count, otherwise every ordinary refresh would spuriously look
            # like "+1 session" and could evict a legitimate, unrelated session. Deliberately no
            # `is_new_device`/suspicious-login check here: Decision #6 names "a login," and a
            # background token refresh (typically silent/automatic) isn't a user-facing sign-in
            # event the way `login()` is — a flagged interpretive scoping choice.
            device_label = parse_device_label(command.user_agent)
            existing_sessions = [
                t
                for t in await uow.refresh_tokens.list_by_user(user.id)
                if t.id != stored.id and not t.is_expired(clock=self._clock)
            ]
            revoked_events: list[DomainEvent] = []
            max_sessions = await self._session_cap_port.get_max_sessions(role=user.role)
            decision = SessionLimitPolicy().evaluate(
                active_session_count=len(existing_sessions) + 1,
                max_sessions=max_sessions,
            )
            if not decision.allowed:
                excess = len(existing_sessions) + 1 - max_sessions
                for stale in sorted(existing_sessions, key=lambda t: t.issued_at)[:excess]:
                    stale.revoke(clock=self._clock)
                    revoked_events += stale.pull_domain_events()

            new_pair = self._token_service.issue_token_pair(
                subject=str(user.id),
                role=user.role,
                org_id=str(user.organization_id) if user.organization_id else None,
            )
            new_claims = self._token_service.decode(
                new_pair.refresh_token, expected_type=TokenType.REFRESH
            )
            new_refresh_entity = RefreshToken.issue(
                id=RefreshTokenId(self._id_generator.new_id()),
                user_id=user.id,
                token_hash=_hash_refresh_token(new_pair.refresh_token),
                expires_at=new_claims.expires_at,
                clock=self._clock,
                user_agent=command.user_agent,
                ip_address=command.ip_address,
                device_label=device_label,
            )
            uow.refresh_tokens.add(new_refresh_entity)
            uow.record_events(
                stored.pull_domain_events()
                + revoked_events
                + new_refresh_entity.pull_domain_events()
            )
            await uow.commit()
            return AuthResultDTO(
                access_token=new_pair.access_token,
                refresh_token=new_pair.refresh_token,
                token_type=new_pair.token_type,
                expires_in=new_pair.expires_in,
                user=user_to_dto(user),
            )

    async def logout(self, command: LogoutCommand, *, uow: IamUnitOfWork) -> None:
        async with uow:
            token_hash = _hash_refresh_token(command.refresh_token)
            stored = await uow.refresh_tokens.get_by_token_hash(token_hash)
            if stored is None:
                # Logging out an already-invalid/unknown token is a no-op, not an error —
                # logout is idempotent from the caller's point of view.
                return
            stored.revoke(clock=self._clock)
            uow.record_events(stored.pull_domain_events())
            await uow.commit()

    async def list_sessions(
        self, query: ListSessionsQuery, *, uow: IamUnitOfWork
    ) -> list[SessionDTO]:
        """ADR-0019: `GET /auth/sessions`. Newest-first — no document specifies ordering (the
        same flagged, no-document-specifies-it choice `GET /notifications` already established
        for its own default ordering)."""
        async with uow:
            tokens = await uow.refresh_tokens.list_by_user(UserId(query.user_id))
            active = [t for t in tokens if not t.is_expired(clock=self._clock)]
            active.sort(key=lambda t: t.issued_at, reverse=True)
            return [refresh_token_to_session_dto(t) for t in active]

    async def revoke_session(
        self, command: RevokeSessionCommand, *, uow: IamUnitOfWork
    ) -> None:
        """ADR-0019: `DELETE /auth/sessions/{id}` — the "secure device replacement flow." Never
        a 403 on ownership mismatch (`NotFoundError` instead) — this codebase's established
        404-over-403 posture for "don't confirm existence of another principal's data."""
        async with uow:
            token = await uow.refresh_tokens.get(RefreshTokenId(command.session_id))
            if token is None or str(token.user_id) != command.user_id:
                raise NotFoundError(f"Session {command.session_id} not found.")
            token.revoke(clock=self._clock)
            uow.record_events(token.pull_domain_events())
            await uow.commit()

    @staticmethod
    async def _find_user_by_identifier(
        uow: IamUnitOfWork, email: str | None, phone: str | None
    ) -> User | None:
        if email:
            user = await uow.users.get_by_email(Email(email))
            if user is not None:
                return user
        if phone:
            return await uow.users.get_by_phone(PhoneNumber(phone))
        return None


class PermissionApplicationService:
    """RBAC permission-matrix management (Database Design §4.4). No approved HTTP route exists
    yet (`application/commands.py`'s own docstring) — reachable at the application layer only,
    and by the migration-time seed (`migrations/versions/...`) that installs this codebase's
    own derived starting matrix. `Clock` is the only dependency — no `id_generator` (composite
    PK, no surrogate id to mint, the same reasoning `StudentParentApplicationService` already
    gives for its own link-table aggregate)."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    async def grant_role_permission(
        self, command: GrantRolePermissionCommand, *, uow: IamUnitOfWork
    ) -> None:
        async with uow:
            await uow.role_permissions.grant(command.role, command.permission)
            uow.record_events(
                [
                    iam_events.role_permission_granted(
                        role=command.role.value,
                        permission=command.permission,
                        occurred_at=self._clock.now(),
                        actor_id=command.actor.user_id,
                    )
                ]
            )
            await uow.commit()

    async def revoke_role_permission(
        self, command: RevokeRolePermissionCommand, *, uow: IamUnitOfWork
    ) -> None:
        async with uow:
            await uow.role_permissions.revoke(command.role, command.permission)
            uow.record_events(
                [
                    iam_events.role_permission_revoked(
                        role=command.role.value,
                        permission=command.permission,
                        occurred_at=self._clock.now(),
                        actor_id=command.actor.user_id,
                    )
                ]
            )
            await uow.commit()

    async def list_permissions_for_role(
        self, role: Role, *, uow: IamUnitOfWork
    ) -> frozenset[str]:
        async with uow:
            return await uow.role_permissions.list_permissions_for_role(role)


class MeApplicationService:
    """ADR-0023: `GET /me`, `GET /me/students`, `GET /me/driver-profile` — the canonical
    self-service identity-resolution capability behind Known Issue #17's fix. Composes
    `transport_ops`'s own application services only (never its `domain`/`infra`), the same
    legal cross-module shape `platform_audit.PlatformStatsApplicationService` (ADR-0020) already
    established. Every method takes a `Principal` (or its bare `user_id`) as its *only* identity
    input — there is no `parent_id`/`driver_id` parameter anywhere in this class for a caller to
    supply, by construction, not by a runtime check bolted on afterward."""

    def __init__(
        self,
        *,
        parent_service: ParentApplicationService,
        driver_service: DriverApplicationService,
        student_parent_service: StudentParentApplicationService,
    ) -> None:
        self._parent_service = parent_service
        self._driver_service = driver_service
        self._student_parent_service = student_parent_service

    async def get_my_identity(
        self, principal: Principal, *, uow: TransportOpsUnitOfWork
    ) -> MeIdentityDTO:
        """Always resolves — `user_id`/`role`/`organization_id` come straight from the
        already-verified `Principal`, no DB read needed for them. `parent_id`/`driver_id` are
        resolved only for the role that could possibly have one, avoiding two pointless queries
        for every other role (Founder/Regional Manager/Support Staff/Finance Staff/Org Admin)."""
        parent_id: str | None = None
        driver_id: str | None = None
        if principal.role == Role.PARENT:
            parent = await self._parent_service.get_parent_by_user_id(
                principal.user_id, uow=uow
            )
            parent_id = parent.id if parent is not None else None
        elif principal.role == Role.DRIVER:
            driver = await self._driver_service.get_driver_by_user_id(
                principal.user_id, uow=uow
            )
            driver_id = driver.id if driver is not None else None
        return MeIdentityDTO(
            user_id=principal.user_id,
            role=principal.role.value,
            organization_id=principal.org_id,
            parent_id=parent_id,
            driver_id=driver_id,
        )

    async def get_my_students(
        self, principal: Principal, *, uow: TransportOpsUnitOfWork
    ) -> list[MeStudentDTO]:
        """`GET /me/students`. Resolves the caller's own `Parent` row from `principal.user_id`
        first — never a client-supplied `parent_id` — then reuses the existing, already-tested
        `StudentParentApplicationService.list_students_for_parent` unchanged with that
        server-resolved id. Raises `NotFoundError` (404, not 403) when no `Parent` row links to
        this user — covers both "this role has no such profile" and "a data inconsistency",
        with one honest code path rather than branching on `principal.role` first."""
        parent = await self._parent_service.get_parent_by_user_id(
            principal.user_id, uow=uow
        )
        if parent is None:
            raise NotFoundError("No Parent profile is linked to this account.")
        results = await self._student_parent_service.list_students_for_parent(
            ListStudentsForParentQuery(parent_id=parent.id), uow=uow
        )
        return [
            MeStudentDTO(
                student_id=dto.student_id,
                full_name=dto.full_name,
                status=dto.status,
                relationship=dto.relationship,
                is_primary=dto.is_primary,
            )
            for dto in results
        ]

    async def get_my_driver_profile(
        self, principal: Principal, *, uow: TransportOpsUnitOfWork
    ) -> MeDriverProfileDTO:
        """`GET /me/driver-profile`. Resolves the caller's own `Driver` row from
        `principal.user_id` — never a client-supplied `driver_id` — closing the mobile Driver
        client's own "learn my own `driver_id` to filter `GET /trips?filter[driver_id]=...`"
        gap (Known Issue #17). Raises `NotFoundError` (404) when no `Driver` row links to this
        user, the same posture as `get_my_students` above."""
        driver = await self._driver_service.get_driver_by_user_id(
            principal.user_id, uow=uow
        )
        if driver is None:
            raise NotFoundError("No Driver profile is linked to this account.")
        return MeDriverProfileDTO(
            driver_id=driver.id,
            organization_id=driver.organization_id,
            license_no=driver.license_no,
            status=driver.status,
        )
