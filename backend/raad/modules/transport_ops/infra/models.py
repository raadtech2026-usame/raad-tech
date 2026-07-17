"""Transport Operations ORM models (Backend LLD §17 `db`; Database Design §6.2). SQLAlchemy is
confined to this infra layer — the domain and application layers never import it
(`.claude/rules/backend.md` #2).

One model, matching Phase 10.1/10.2's own scope: `StudentModel` only (`students`). Database
Design §6.2 gives `students` a "+ standard audit cols" line, the same reading
`organization.infra.models`/`fleet_device.infra.models` give their own audited tables, so this
composes `AuditedTableMixin` (the full bundle) — not a partial mixin set.

`organization_id` is an **indexed plain column, not a database FK**: it references the
`organization` module's own table, and cross-context references are by ID only
(`.claude/rules/database.md` #3) — the same treatment `users.organization_id`/
`vehicles.organization_id` already get.

PostgreSQL types only (ADR-0002) — no MySQL dialect import anywhere in this file, matching
every other infra model rewritten during the PostgreSQL migration.
"""

from __future__ import annotations

from sqlalchemy import CHAR, VARCHAR
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import AuditedTableMixin

_STUDENT_STATUS_VALUES = ("active", "disabled", "graduated", "transferred")


class StudentModel(AuditedTableMixin, Base):
    """`students` (Database Design §6.2): a student enrolled with an organization."""

    __tablename__ = "students"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(VARCHAR(64), nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_STUDENT_STATUS_VALUES, name="student_status"),
        nullable=False,
        index=True,
    )
