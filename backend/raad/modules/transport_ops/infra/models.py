"""Transport Operations ORM models (Backend LLD §17 `db`; Database Design §6.2/§6.3).
SQLAlchemy is confined to this infra layer — the domain and application layers never import it
(`.claude/rules/backend.md` #2).

`StudentModel` (`students`) and, as of Phase 10.6, `ParentModel` (`parents`). Both tables get
Database Design's "+ standard audit cols" line (§6.2/§6.3), the same reading
`organization.infra.models`/`fleet_device.infra.models` give their own audited tables, so both
compose `AuditedTableMixin` (the full bundle) — not a partial mixin set.

`organization_id` is an **indexed plain column, not a database FK**: it references the
`organization` module's own table, and cross-context references are by ID only
(`.claude/rules/database.md` #3) — the same treatment `users.organization_id`/
`vehicles.organization_id` already get. `ParentModel.user_id` is likewise a cross-context
reference (to `iam.UserModel`, Database Design §6.3's "FK→users" shorthand) — despite the
doc's "FK" wording, `users` is owned by `iam`, not `transport_ops`, so this is an indexed plain
column too, never a real `ForeignKey`, mirroring `organization_id`'s own treatment exactly
(see `domain/value_objects.py`'s `UserId` docstring for the full reasoning).

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
_PARENT_STATUS_VALUES = ("active", "inactive")


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


class ParentModel(AuditedTableMixin, Base):
    """`parents` (Database Design §6.3): a parent/guardian's transport-facing profile, linked
    to an `iam.User` login. `full_name`/`phone` use `VARCHAR(200)`/`VARCHAR(32)` — the lengths
    already established for the identically-named columns elsewhere in this schema
    (`users.full_name`/`users.phone`, `iam/infra/models.py`), since §6.3's compact notation
    gives no explicit lengths of its own (see `domain/value_objects.py`'s module docstring).
    """

    __tablename__ = "parents"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(VARCHAR(32), nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_PARENT_STATUS_VALUES, name="parent_status"),
        nullable=False,
        index=True,
    )
