"""Reusable ORM mixins implementing the standard audit columns (Database Design §1) that
every business table carries. Modules compose these onto their own ORM models
(`modules/<context>/infra/models.py`) — no module-specific table is defined here (foundation
only, Backend LLD §17 `db`).

    id · created_at · updated_at · created_by · updated_by · deleted_at · row_version

Split into four mixins (id, timestamps, audit actor, soft delete) rather than one, since a few
tables intentionally deviate from the full set — e.g. `audit_entries` is append-only with no
`updated_at`/`deleted_at` (Database Design §8.7) — and should only take what applies.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CHAR, Integer
from sqlalchemy.dialects.mysql import DATETIME as MySqlDateTime
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from raad.core.ids.generator import generate_ulid


# MySQL's DATETIME has no timezone concept (Database Design §1: "DATETIME(3)"), so values are
# stored naive but the application-wide discipline is that every stored datetime *is* UTC —
# hence stripping tzinfo here rather than using a timezone-aware column type MySQL can't
# actually honor. Public (not `_`-prefixed): `core/events/outbox.py` reuses it for the same
# naive-UTC convention on `outbox.created_at`.
def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UlidPrimaryKeyMixin:
    """`id CHAR(26)` ULID primary key (Database Design §1, resolving Backend LLD §20.2)."""

    id: Mapped[str] = mapped_column(CHAR(26), primary_key=True, default=generate_ulid)


class TimestampMixin:
    """`created_at`/`updated_at`, UTC, app-maintained (not DB-clock-maintained) per Database
    Design §1 — set from Python so behavior is identical across dialects and testable via
    `core/time.Clock` at the application layer (columns themselves just need *a* value)."""

    created_at: Mapped[datetime] = mapped_column(
        MySqlDateTime(fsp=3), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        MySqlDateTime(fsp=3), nullable=False, default=utcnow, onupdate=utcnow
    )


class AuditActorMixin:
    """`created_by`/`updated_by` actor references (nullable — null means "system") plus the
    optimistic-locking `row_version` counter (Database Design §1)."""

    created_by: Mapped[str | None] = mapped_column(CHAR(26), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(CHAR(26), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, object]:  # noqa: N805 - SQLAlchemy convention
        """Enables SQLAlchemy's built-in optimistic-concurrency check against `row_version`
        (an `UPDATE ... WHERE row_version = :old` that raises `StaleDataError` on a
        conflicting concurrent write). A model composing another mixin that also defines
        `__mapper_args__` must merge them explicitly — not a concern for any model today."""
        return {"version_id_col": cls.row_version}


class SoftDeleteMixin:
    """`deleted_at`, null = live (Database Design §1/§9). Filtering `deleted_at IS NULL` by
    default is a repository-layer concern (`core/db/repository.py`), not enforced by the
    column itself."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        MySqlDateTime(fsp=3), nullable=True, default=None
    )


class AuditedTableMixin(
    UlidPrimaryKeyMixin, TimestampMixin, AuditActorMixin, SoftDeleteMixin
):
    """Convenience bundle: the full standard audit-column set for the common case (Database
    Design §1's "present on all business tables unless noted"). Tables that deviate — e.g.
    `audit_entries` (append-only, no `updated_at`/`deleted_at`) — compose the individual
    mixins above directly instead of this bundle."""
