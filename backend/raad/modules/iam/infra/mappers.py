"""ORM ↔ Domain mappers for `iam` (Backend LLD §7.1 "aggregate-in/aggregate-out"; §17 `db`).
Mappers own **every** conversion between SQLAlchemy rows and domain objects — repositories
(`repositories.py`) never construct or read ORM columns directly outside calling these
functions, and never return an ORM model to a caller.

Role casing: see `models.py`'s module docstring — `Role.value` is upper-case
(`core.tenancy.principal`, Phase 4.3), the approved DB column is lower-case (Database Design
§4.3). `.lower()`/`.upper()` here is the single translation point; every `Role` member's
value is already its snake_case DB form upper-cased (`REGIONAL_MANAGER` ↔ `regional_manager`),
so a plain case-fold round-trips exactly.
"""

from __future__ import annotations

from datetime import datetime, timezone

from raad.core.tenancy.principal import Role
from raad.modules.iam.domain.entities import RefreshToken, User
from raad.modules.iam.domain.value_objects import (
    Email,
    OrganizationId,
    PhoneNumber,
    RefreshTokenId,
    UserId,
    UserStatus,
)
from raad.modules.iam.infra.models import RefreshTokenModel, UserModel


def _naive(value: datetime | None) -> datetime | None:
    """Strips tzinfo before a domain-computed timestamp crosses into a `DateTime(timezone=
    False)` column (ADR-0002) — the same pattern `core.events.outbox.OutboxWriter.write()`
    already applies to `DomainEvent.occurred_at`. `Clock.now()` (`SystemClock`) and JWT-decoded
    claims are tz-aware in memory; the DB column is naive-UTC-by-convention
    (`core.db.mixins.utcnow`'s own discipline) — without this, inserting e.g.
    `RefreshToken.expires_at` raises `asyncpg.exceptions.DataError` ("can't subtract
    offset-naive and offset-aware datetimes"), caught by this phase's PostgreSQL integration
    tests."""
    return value.replace(tzinfo=None) if value is not None and value.tzinfo else value


def _aware_utc(value: datetime | None) -> datetime | None:
    """The inverse of `_naive` above, applied on the read side. `core.db.mixins.utcnow`'s own
    naive-storage convention is that every stored datetime *is* UTC — so a value read back from
    a `DateTime(timezone=False)` column is re-stamped `tzinfo=timezone.utc` rather than left
    naive, keeping a reloaded domain object's datetime fields directly comparable to a
    `Clock.now()`-derived value (`SystemClock` is tz-aware) without every call site needing to
    know which construction path produced the instance. Regression: `RefreshToken.is_expired`
    (`domain/entities.py`) compares `clock.now() >= self.expires_at` — before this helper
    existed, a `RefreshToken` reloaded via `model_to_refresh_token` carried a naive `expires_at`
    read straight off the model, so every real `POST /auth/refresh` call raised `TypeError:
    can't compare offset-naive and offset-aware datetimes` the moment it checked expiry against
    an actually-persisted token; a freshly-`.issue()`d, never-reloaded token never exercised this
    path, which is why no prior test caught it."""
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def user_to_model(user: User, *, existing: UserModel | None = None) -> UserModel:
    """Projects a `User` aggregate onto its ORM row. If `existing` is given, mutates and
    returns that same instance (so the SQLAlchemy session keeps tracking the one row it
    already knows about, rather than a duplicate) — otherwise constructs a new `UserModel`.
    """
    model = existing if existing is not None else UserModel(id=str(user.id))
    model.organization_id = (
        str(user.organization_id) if user.organization_id is not None else None
    )
    model.role = user.role.value.lower()
    model.email = str(user.email) if user.email is not None else None
    model.phone = str(user.phone) if user.phone is not None else None
    model.password_hash = user.password_hash
    model.full_name = user.full_name
    model.status = user.status.value
    model.mfa_enabled = user.mfa_enabled
    model.last_login_at = _naive(user.last_login_at)
    model.created_at = _naive(user.created_at)
    model.updated_at = _naive(user.updated_at)
    return model


def model_to_user(model: UserModel) -> User:
    return User(
        id=UserId(model.id),
        organization_id=(
            OrganizationId(model.organization_id) if model.organization_id else None
        ),
        role=Role(model.role.upper()),
        email=Email(model.email) if model.email else None,
        phone=PhoneNumber(model.phone) if model.phone else None,
        full_name=model.full_name,
        status=UserStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
        password_hash=model.password_hash,
        mfa_enabled=model.mfa_enabled,
        last_login_at=model.last_login_at,
    )


def refresh_token_to_model(
    token: RefreshToken, *, existing: RefreshTokenModel | None = None
) -> RefreshTokenModel:
    model = existing if existing is not None else RefreshTokenModel(id=str(token.id))
    model.user_id = str(token.user_id)
    model.token_hash = token.token_hash
    model.issued_at = _naive(token.issued_at)
    model.expires_at = _naive(token.expires_at)
    model.revoked_at = _naive(token.revoked_at)
    return model


def model_to_refresh_token(model: RefreshTokenModel) -> RefreshToken:
    return RefreshToken(
        id=RefreshTokenId(model.id),
        user_id=UserId(model.user_id),
        token_hash=model.token_hash,
        issued_at=_aware_utc(model.issued_at),
        expires_at=_aware_utc(model.expires_at),
        revoked_at=_aware_utc(model.revoked_at),
    )
