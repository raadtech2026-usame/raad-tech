"""Reporting ORM models (Backend LLD §17 `db`; Database Design §8.6). SQLAlchemy is confined to
this infra layer — the domain and application layers never import it
(`.claude/rules/backend.md` #2). PostgreSQL types only (ADR-0002).

**`ReportRunModel` does not compose `AuditedTableMixin`.** §8.6 lists exactly its own columns
(its own `created_at`/`completed_at` pair, no `updated_at`/`created_by`/`updated_by`/
`deleted_at`/`row_version`) — the identical situation `billing.infra.models.PaymentModel`/
`notifications.infra.models.NotificationModel` already establish. Composes `UlidPrimaryKeyMixin`
only.

`report_runs.requested_by` (→ `iam.User`) is a plain indexed column, never a database
`ForeignKey` — a cross-context reference (`.claude/rules/database.md` #3; Database Design
§11.2/§11.3).

**`definition_key` has no documented length** — modeled as `VARCHAR(80)`, mirroring
`audit_entries.action VARCHAR(80)`'s precedent for an analogous short label-key column (see
`domain/value_objects.py`'s `ReportType` docstring for the full reasoning).

**`artifact_url` has no documented length** — modeled as `VARCHAR(500)`, mirroring
`notifications.infra.models.NotificationModel.body`'s identical "no documented length, pick a
generously-sized value, flag it" treatment for a similarly free-form field.

**`params_json` reuses the `JSONB` pattern `notifications.infra.models.NotificationModel.
data_json` established in Phase 16** — PostgreSQL native `JSONB` (ADR-0002), not the
dialect-generic `JSON` type.

**No partial unique index in this file** — Database Design §8.6 documents no uniqueness
constraint of any kind for `report_runs` (unlike `payments.idempotency_key`/`invoices.number`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, VARCHAR, DateTime
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import UlidPrimaryKeyMixin

_REPORT_STATUS_VALUES = ("queued", "running", "succeeded", "failed")

_DEFINITION_KEY_LENGTH = 80  # Database Design §8.6 gives no length - see module docstring
_ARTIFACT_URL_LENGTH = 500  # §8.6 gives no length - see module docstring


class ReportRunModel(UlidPrimaryKeyMixin, Base):
    """`report_runs` (Database Design §8.6) - see module docstring for why this composes
    `UlidPrimaryKeyMixin` only, not `AuditedTableMixin`."""

    __tablename__ = "report_runs"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    definition_key: Mapped[str] = mapped_column(
        VARCHAR(_DEFINITION_KEY_LENGTH), nullable=False
    )
    params_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_REPORT_STATUS_VALUES, name="report_run_status"), nullable=False, index=True
    )
    artifact_url: Mapped[str | None] = mapped_column(
        VARCHAR(_ARTIFACT_URL_LENGTH), nullable=True
    )
    requested_by: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
