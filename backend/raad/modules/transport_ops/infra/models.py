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

**Phase 10.7 addition: `StudentParentModel`.** `student_parents` (Database Design §6.4) is
composite-keyed by `(student_id, parent_id)` with no independent `id`/audit columns — §6.4
lists exactly four columns and no "+ standard audit cols" line, unlike every other table in
that document, including `students`/`parents` above (confirmed with the user before
implementing, since `.claude/rules/database.md` #4's general audit-column convention would
otherwise conflict with this table's own narrower, explicit spec). `student_id`/`parent_id`
**are** real database foreign keys here — unlike `organization_id`/`user_id` above — because
`students`, `parents`, and `student_parents` are all owned by this same module: in-context FKs
are enforced by the database (`.claude/rules/database.md` #3), the same treatment
`fleet_device.CameraModel.device_id → devices.id` already gets for an identical
same-module reference.

PostgreSQL types only (ADR-0002) — no MySQL dialect import anywhere in this file, matching
every other infra model rewritten during the PostgreSQL migration.
"""

from __future__ import annotations

from sqlalchemy import CHAR, VARCHAR, Boolean, ForeignKey
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


class StudentParentModel(Base):
    """`student_parents` (Database Design §6.4, M:N): see module docstring's Phase 10.7
    addition for why this composes `Base` directly rather than `AuditedTableMixin` (or any of
    its constituent mixins) — no `id`, no `created_at`/`updated_at`, no `row_version`, no
    `deleted_at`.

    `parent_id` carries an explicit secondary index: the composite PK `(student_id, parent_id)`
    only serves left-prefix lookups by `student_id` (`list_by_student`, `infra/repositories.py`)
    — `list_by_parent`'s `WHERE parent_id = ...` needs its own index, the same reasoning
    `fleet_device.CameraModel.device_id`/`DeviceAssignmentModel.vehicle_id` already get
    dedicated indexes for. `student_id` needs no equivalent index of its own — it's the PK's
    leading column, already covered."""

    __tablename__ = "student_parents"

    student_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("students.id"), primary_key=True
    )
    parent_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("parents.id"), primary_key=True, index=True
    )
    relationship: Mapped[str | None] = mapped_column(VARCHAR(40), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
