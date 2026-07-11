"""IAM ORM models (Backend LLD §17 `db`; Database Design §4.3/§4.5). SQLAlchemy is confined
to this infra layer — the domain and application layers never import it (`.claude/rules
/backend.md`, and this phase's own "no direct SQLAlchemy usage outside Infrastructure" rule).

Role casing note: `core.tenancy.principal.Role` (Phase 4.3, already shipped) uses upper-case
values (`"FOUNDER"`), while Database Design §4.3's approved `role ENUM` uses lower-case values
(`founder`). Rather than changing the already-shipped `Role` enum or deviating from the
approved schema, the *mapper* (`mappers.py`) is the single place that translates between them
— this file just declares the lower-case-valued column, exactly as approved.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, VARCHAR, Boolean, CheckConstraint, ForeignKey
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.mysql import DATETIME as MySqlDateTime
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import (
    AuditActorMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UlidPrimaryKeyMixin,
)

_ROLE_VALUES = (
    "founder",
    "regional_manager",
    "support_staff",
    "finance_staff",
    "org_admin",
    "driver",
    "parent",
)
_STATUS_VALUES = ("active", "disabled", "invited")


class UserModel(
    UlidPrimaryKeyMixin, TimestampMixin, AuditActorMixin, SoftDeleteMixin, Base
):
    """`users` (Database Design §4.3): single identity table for every principal — RAAD
    staff, org admins, drivers, parents — discriminated by `role`.

    The two CHECK constraints mirror the schema's stated constraints exactly: "at least one
    of email/phone present" and "organization_id required when role ∈ {org_admin, driver,
    parent}". Uniqueness on `email`/`phone` is a plain unique index here (not the
    generated-column soft-delete-aware idiom used for e.g. `device_assignments`' active-
    binding keys, §9) — the Database Design doesn't call that idiom out for this table, so
    this stays a literal reading rather than an invented extension of the approved schema.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL", name="email_or_phone_present"
        ),
        CheckConstraint(
            "(role NOT IN ('org_admin', 'driver', 'parent')) OR (organization_id IS NOT NULL)",
            name="org_scoped_role_requires_organization_id",
        ),
    )

    organization_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True, index=True)
    role: Mapped[str] = mapped_column(
        SqlEnum(*_ROLE_VALUES, name="user_role"), nullable=False, index=True
    )
    email: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True, unique=True)
    phone: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True, unique=True)
    password_hash: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    full_name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_STATUS_VALUES, name="user_status"), nullable=False, index=True
    )
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(
        MySqlDateTime(fsp=3), nullable=True, default=None
    )


class RefreshTokenModel(UlidPrimaryKeyMixin, Base):
    """`refresh_tokens` (Database Design §4.5). No standard audit-column bundle — that note is
    only attached to the `users` table; this table's own `issued_at`/`revoked_at` already
    serve the equivalent purpose, and it has no soft delete."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(MySqlDateTime(fsp=3), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        MySqlDateTime(fsp=3), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        MySqlDateTime(fsp=3), nullable=True, default=None
    )
    user_agent: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(VARCHAR(45), nullable=True)
