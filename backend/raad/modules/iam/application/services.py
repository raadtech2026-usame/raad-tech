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

from raad.core.errors.exceptions import AuthenticationError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import OffsetPage
from raad.core.security.claims import TokenType
from raad.core.tenancy.principal import Role
from raad.core.security.password_hashing import PasswordHasher
from raad.core.security.password_policy import PasswordPolicy
from raad.core.security.tokens import TokenService
from raad.core.time.clock import Clock
from raad.modules.iam.application.commands import (
    ActivateUserCommand,
    ChangePasswordCommand,
    DisableMfaCommand,
    DisableUserCommand,
    EnableMfaCommand,
    GrantRolePermissionCommand,
    InviteUserCommand,
    LoginCommand,
    LogoutCommand,
    RefreshAccessTokenCommand,
    RevokeRolePermissionCommand,
)
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.queries import (
    AuthResultDTO,
    GetUserByIdQuery,
    ListUsersQuery,
    UserDTO,
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


def _hash_refresh_token(raw_token: str) -> str:
    """SHA-256 hex digest (Database Design §4.5: `token_hash CHAR(64)`) — a fast lookup hash,
    not a slow KDF like `PasswordHasher`: refresh tokens are already high-entropy signed JWTs,
    not user-chosen secrets, so PBKDF2-style stretching isn't needed here."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


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
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._token_service = token_service
        self._password_hasher = password_hasher

    async def login(
        self, command: LoginCommand, *, uow: IamUnitOfWork
    ) -> AuthResultDTO:
        async with uow:
            user = await self._find_user_by_identifier(
                uow, command.email, command.phone
            )
            if (
                user is None
                or user.password_hash is None
                or not self._password_hasher.verify(
                    command.plain_password, user.password_hash
                )
            ):
                raise AuthenticationError("Invalid credentials.")
            if user.status is not UserStatus.ACTIVE:
                raise AuthenticationError("Account is not active.")

            user.record_login(clock=self._clock)
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
            )
            uow.refresh_tokens.add(refresh_entity)
            uow.record_events(
                user.pull_domain_events() + refresh_entity.pull_domain_events()
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
            )
            uow.refresh_tokens.add(new_refresh_entity)
            uow.record_events(
                stored.pull_domain_events() + new_refresh_entity.pull_domain_events()
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
