"""IAM aggregate roots (Backend LLD §5.1/§5.2; Database Design §4.3/§4.5). Framework-free —
no SQLAlchemy/Pydantic/FastAPI, no I/O. Behavior methods mutate state, enforce invariants, and
return/buffer the resulting `DomainEvent`s, matching the LLD §5.2 shape
(`start(actor, clock) -> [TripStarted]`): a `Clock` (`core.time`, a pure port — no framework
dependency) is passed into each method rather than the aggregate calling `datetime.now()`
itself, so behavior stays deterministic and unit-testable with a fake clock.

Password *hashing* is deliberately not this module's concern: `User` only stores an opaque
`password_hash` string produced elsewhere (`core.security.PasswordHasher`, Phase 4.3) — the
domain never sees a plaintext password or a hashing algorithm.
"""

from __future__ import annotations

from datetime import datetime

from raad.core.errors.exceptions import DomainError
from raad.core.events.base import DomainEvent
from raad.core.tenancy.principal import Role
from raad.core.time.clock import Clock
from raad.modules.iam.domain import events as iam_events
from raad.modules.iam.domain.value_objects import (
    Email,
    OrganizationId,
    PhoneNumber,
    RefreshTokenId,
    UserId,
    UserStatus,
    validate_token_hash,
)

_STAFF_ROLES = frozenset(
    {Role.FOUNDER, Role.REGIONAL_MANAGER, Role.SUPPORT_STAFF, Role.FINANCE_STAFF}
)
_ORG_SCOPED_ROLES = frozenset({Role.ORG_ADMIN, Role.DRIVER, Role.PARENT})


class _AggregateRoot:
    """Shared "raise and buffer domain events" mechanics (LLD §8.1: the Unit of Work "buffers
    domain events"). `pull_domain_events()` is called once, by the future application layer/
    UoW, when this aggregate's changes are committed — not implemented in this phase."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


class User(_AggregateRoot):
    """Single identity aggregate for every principal — RAAD staff, org admins, drivers,
    parents — discriminated by `role` (Database Design §4.3). Enforces:

    - at least one of `email`/`phone` present (§4.3 CHECK constraint)
    - `organization_id` required for org-scoped roles (org_admin/driver/parent) and absent for
      RAAD-staff roles (founder/regional_manager/support_staff/finance_staff)
    """

    def __init__(
        self,
        *,
        id: UserId,
        organization_id: OrganizationId | None,
        role: Role,
        email: Email | None,
        phone: PhoneNumber | None,
        full_name: str,
        status: UserStatus,
        created_at: datetime,
        updated_at: datetime,
        password_hash: str | None = None,
        mfa_enabled: bool = False,
        last_login_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._validate_identity_and_scope(
            role=role, organization_id=organization_id, email=email, phone=phone
        )
        self.id = id
        self.organization_id = organization_id
        self.role = role
        self.email = email
        self.phone = phone
        self.full_name = full_name
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
        self.password_hash = password_hash
        self.mfa_enabled = mfa_enabled
        self.last_login_at = last_login_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, User) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @staticmethod
    def _validate_identity_and_scope(
        *,
        role: Role,
        organization_id: OrganizationId | None,
        email: Email | None,
        phone: PhoneNumber | None,
    ) -> None:
        if email is None and phone is None:
            raise DomainError("A user must have at least one of email or phone.")
        if role in _ORG_SCOPED_ROLES and organization_id is None:
            raise DomainError(f"role={role.value} requires an organization_id.")
        if role in _STAFF_ROLES and organization_id is not None:
            raise DomainError(
                f"role={role.value} is a RAAD-staff role and must not have an organization_id."
            )

    def _org_id_value(self) -> str | None:
        return str(self.organization_id) if self.organization_id is not None else None

    @classmethod
    def invite(
        cls,
        *,
        id: UserId,
        organization_id: OrganizationId | None,
        role: Role,
        email: Email | None,
        phone: PhoneNumber | None,
        full_name: str,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "User":
        """Factory for a newly-invited user (`status=invited`, no password yet — Database
        Design §4.3's `password_hash` is nullable; it's set once the invitee completes
        registration, via `change_password_hash`)."""
        now = clock.now()
        user = cls(
            id=id,
            organization_id=organization_id,
            role=role,
            email=email,
            phone=phone,
            full_name=full_name,
            status=UserStatus.INVITED,
            created_at=now,
            updated_at=now,
        )
        user._record(
            iam_events.user_invited(
                user_id=str(id),
                organization_id=user._org_id_value(),
                role=role.value,
                email=str(email) if email else None,
                phone=str(phone) if phone else None,
                full_name=full_name,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return user

    def activate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == UserStatus.ACTIVE:
            return
        self.status = UserStatus.ACTIVE
        self.updated_at = clock.now()
        self._record(
            iam_events.user_activated(
                user_id=str(self.id),
                organization_id=self._org_id_value(),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def disable(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == UserStatus.DISABLED:
            return
        self.status = UserStatus.DISABLED
        self.updated_at = clock.now()
        self._record(
            iam_events.user_disabled(
                user_id=str(self.id),
                organization_id=self._org_id_value(),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def record_login(self, *, clock: Clock) -> None:
        now = clock.now()
        self.last_login_at = now
        self.updated_at = now
        self._record(
            iam_events.user_logged_in(
                user_id=str(self.id),
                organization_id=self._org_id_value(),
                occurred_at=now,
            )
        )

    def change_password_hash(
        self, new_password_hash: str, *, clock: Clock, actor_id: str | None = None
    ) -> None:
        """Stores an already-hashed password. Hashing itself is `core.security`'s concern
        (Phase 4.3) — the domain never imports it, and never handles a plaintext password.
        """
        if not new_password_hash:
            raise DomainError("password hash must not be empty")
        self.password_hash = new_password_hash
        self.updated_at = clock.now()
        self._record(
            iam_events.user_password_changed(
                user_id=str(self.id),
                organization_id=self._org_id_value(),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def enable_mfa(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.mfa_enabled:
            return
        self.mfa_enabled = True
        self.updated_at = clock.now()
        self._record(
            iam_events.user_mfa_enabled(
                user_id=str(self.id),
                organization_id=self._org_id_value(),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def disable_mfa(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if not self.mfa_enabled:
            return
        self.mfa_enabled = False
        self.updated_at = clock.now()
        self._record(
            iam_events.user_mfa_disabled(
                user_id=str(self.id),
                organization_id=self._org_id_value(),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class RefreshToken(_AggregateRoot):
    """One issued refresh token (Database Design §4.5). `token_hash` is the hash of the actual
    token value — the domain never sees or handles the raw secret, mirroring `User`'s
    password-hash convention."""

    def __init__(
        self,
        *,
        id: RefreshTokenId,
        user_id: UserId,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
        revoked_at: datetime | None = None,
    ) -> None:
        super().__init__()
        validate_token_hash(token_hash)
        if expires_at <= issued_at:
            raise DomainError("expires_at must be after issued_at")
        self.id = id
        self.user_id = user_id
        self.token_hash = token_hash
        self.issued_at = issued_at
        self.expires_at = expires_at
        self.revoked_at = revoked_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RefreshToken) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def issue(
        cls,
        *,
        id: RefreshTokenId,
        user_id: UserId,
        token_hash: str,
        expires_at: datetime,
        clock: Clock,
    ) -> "RefreshToken":
        issued_at = clock.now()
        token = cls(
            id=id,
            user_id=user_id,
            token_hash=token_hash,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        token._record(
            iam_events.refresh_token_issued(
                token_id=str(id),
                user_id=str(user_id),
                expires_at=expires_at,
                occurred_at=issued_at,
            )
        )
        return token

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired(self, *, clock: Clock) -> bool:
        return clock.now() >= self.expires_at

    def revoke(self, *, clock: Clock) -> None:
        if self.is_revoked:
            return
        now = clock.now()
        self.revoked_at = now
        self._record(
            iam_events.refresh_token_revoked(
                token_id=str(self.id), user_id=str(self.user_id), occurred_at=now
            )
        )
