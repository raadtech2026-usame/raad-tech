"""Organization ORM models (Backend LLD §17 `db`; Database Design §4.1/§4.2). SQLAlchemy is
confined to this infra layer — the domain and application layers never import it
(`.claude/rules/backend.md` #2).

Both tables get the full standard audit-column bundle (Database Design §1: `id, created_at,
updated_at, created_by, updated_by, deleted_at, row_version`) — `organizations` says so
explicitly ("+ standard audit cols ... soft delete supported", §4.2), and `regions` lists the
same "+ standard audit cols" line (§4.1) — so both compose `AuditedTableMixin` (the bundle),
unlike `iam.infra.models.RefreshTokenModel`, which deviates from the bundle only because its
own table spec explicitly has no such line.
"""

from __future__ import annotations

from sqlalchemy import CHAR, VARCHAR, ForeignKey
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import AuditedTableMixin

_ORG_TYPE_VALUES = ("school",)
_BILLING_MODEL_VALUES = ("organization_pays", "parent_pays")
_ORGANIZATION_STATUS_VALUES = ("active", "suspended", "inactive")
_REGION_STATUS_VALUES = ("active", "inactive")


class RegionModel(AuditedTableMixin, Base):
    """`regions` (Database Design §4.1): RAAD-internal region scoping — every `Organization`
    belongs to exactly one region."""

    __tablename__ = "regions"

    name: Mapped[str] = mapped_column(VARCHAR(120), nullable=False, unique=True)
    geographic_scope: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_REGION_STATUS_VALUES, name="region_status"), nullable=False
    )


class OrganizationModel(AuditedTableMixin, Base):
    """`organizations` (Database Design §4.2): tenant root. `parent_org_id`/`region_id` are
    both **in-context** FKs (this module owns `organizations` and `regions` both), so both are
    real database-enforced foreign keys per `.claude/rules/database.md` #3 — unlike a
    cross-module reference, which would be an indexed column with no FK constraint.

    Indexes match Database Design §4.2's list exactly (`ix_organizations__region`,
    `ix_organizations__parent`, `ix_organizations__status`) in substance — the literal
    generated names follow `core.db.base`'s naming convention off the real column names
    (`region_id`, `parent_org_id`, `status`), the same as every other module's table so far
    (e.g. `iam`'s `ix_users__organization_id`, not a hand-picked abbreviation).
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(VARCHAR(200), nullable=False)
    org_type: Mapped[str] = mapped_column(
        SqlEnum(*_ORG_TYPE_VALUES, name="org_type"), nullable=False
    )
    parent_org_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("organizations.id"), nullable=True, index=True
    )
    region_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("regions.id"), nullable=False, index=True
    )
    billing_model: Mapped[str] = mapped_column(
        SqlEnum(*_BILLING_MODEL_VALUES, name="billing_model"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        SqlEnum(*_ORGANIZATION_STATUS_VALUES, name="organization_status"),
        nullable=False,
        index=True,
    )
