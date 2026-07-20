"""Notifications ORM models (Backend LLD §17 `db`; Database Design §7.5-§7.6). SQLAlchemy is
confined to this infra layer — the domain and application layers never import it
(`.claude/rules/backend.md` #2). PostgreSQL types only (ADR-0002).

**Neither `NotificationModel` nor `DeviceTokenModel` composes `AuditedTableMixin`.** §7.5/§7.6
list exactly their own columns (each with its own `created_at`, no `updated_at`/`created_by`/
`updated_by`/`deleted_at`/`row_version`) — the identical situation `billing.infra.models.
PaymentModel`/`transport_ops.infra.models.StudentParentModel` already establish for a table
whose own timestamp columns already serve the audit purpose. Both compose `UlidPrimaryKeyMixin`
only.

`notifications.recipient_user_id`, `device_tokens.user_id` (both → `iam.User`), and
`notifications.trip_id` (→ `transport_ops.Trip`) are plain indexed columns, never database
`ForeignKey`s — cross-context references (`.claude/rules/database.md` #3; Database Design
§11.2/§11.3: "cross-context reference columns indexed but not FK-constrained"). **This
deliberately does not follow §7.6's own compact-table literal wording** ("`user_id FK`") —
re-read in full, §11.3's "Referential integrity summary" gives the *general* rule
("cross-context references: by id... e.g. `parents.user_id`") that every other cross-module
reference in this entire codebase already follows without exception; §7.6's terse one-line
notation is read as loose shorthand, not a deliberate carve-out contradicting the architecture's
own stated module-seam rule.

**`notifications.data_json` is the first JSON column in this codebase** — no existing precedent
to mirror. Uses PostgreSQL's native `JSONB` (binary, indexable, queryable) rather than the
dialect-generic `JSON` type, per ADR-0002's "PostgreSQL provides a native, better-suited
feature" principle, applied here for the first time rather than carried over from any prior
module.

**`device_tokens.fcm_token`'s column length is undocumented** (§7.6 gives no explicit
`VARCHAR(n)`) — modeled as `VARCHAR(255)`, mirroring `iam.UserModel.email`'s identical
"no other precedent, pick a generously-sized opaque-string length" reasoning; flagged here
rather than silently presented as a documented value.

**No partial unique index in this file** — no "one active X" invariant is documented for either
table (unlike `trips`/`student_assignments`). The one documented uniqueness constraint,
`ux_device_tokens__token`, is a plain global unique constraint, not conditional on
`revoked_at IS NULL` — re-registering an already-revoked token's same value is still rejected,
exactly as §7.6 states it ("Unique `ux_device_tokens__token (fcm_token)`", no qualifier).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, VARCHAR, DateTime, Index
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import UlidPrimaryKeyMixin

_NOTIFICATION_TYPE_VALUES = (
    "trip_started",
    "approaching_stop",
    "arrived_org",
    "trip_completed",
    "subscription",
    "system",
)
_PLATFORM_VALUES = ("android", "ios")

_TITLE_LENGTH = 160  # Database Design §7.5: title VARCHAR(160)
_BODY_LENGTH = 500  # §7.5: body VARCHAR(500)
_FCM_TOKEN_LENGTH = 255  # §7.6 gives no length - see module docstring


class NotificationModel(UlidPrimaryKeyMixin, Base):
    """`notifications` (Database Design §7.5) - see module docstring for why this composes
    `UlidPrimaryKeyMixin` only, not `AuditedTableMixin`."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "ix_notifications__recipient_created",
            "recipient_user_id",
            "created_at",
        ),
    )

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    recipient_user_id: Mapped[str] = mapped_column(CHAR(26), nullable=False)
    type: Mapped[str] = mapped_column(
        SqlEnum(*_NOTIFICATION_TYPE_VALUES, name="notification_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(VARCHAR(_TITLE_LENGTH), nullable=False)
    body: Mapped[str] = mapped_column(VARCHAR(_BODY_LENGTH), nullable=False)
    data_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    trip_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class DeviceTokenModel(UlidPrimaryKeyMixin, Base):
    """`device_tokens` (Database Design §7.6) - see module docstring for the FK/length notes."""

    __tablename__ = "device_tokens"

    user_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    fcm_token: Mapped[str] = mapped_column(
        VARCHAR(_FCM_TOKEN_LENGTH), nullable=False, unique=True
    )
    platform: Mapped[str] = mapped_column(
        SqlEnum(*_PLATFORM_VALUES, name="device_token_platform"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
