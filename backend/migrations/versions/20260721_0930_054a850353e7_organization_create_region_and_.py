"""organization: create region_assignments, support_assignments tables

Revision ID: 054a850353e7
Revises: 5437a5d1651b
Create Date: 2026-07-21 09:30:00.000000

Backs `ScopeResolver` (Database Design §4.6, Phase 2 §17.4) — previously deferred pending an
explicit design decision (`organization.domain.entities`'s own module docstring), now resolved
under the Backend Stabilization phase's explicit authority. See
`docs/architecture/adr/0005-scope-resolver.md`.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "054a850353e7"
down_revision: Union[str, None] = "5437a5d1651b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "region_assignments",
        sa.Column("user_id", sa.CHAR(length=26), nullable=False),
        sa.Column("region_id", sa.CHAR(length=26), nullable=False),
        sa.Column("granted_by", sa.CHAR(length=26), nullable=True),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["region_id"], ["regions.id"], name=op.f("fk_region_assignments__regions")
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "region_id", name=op.f("pk_region_assignments")
        ),
    )
    op.create_index(
        op.f("ix_region_assignments__region_id"),
        "region_assignments",
        ["region_id"],
        unique=False,
    )

    op.create_table(
        "support_assignments",
        sa.Column("user_id", sa.CHAR(length=26), nullable=False),
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("granted_by", sa.CHAR(length=26), nullable=True),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_support_assignments__organizations"),
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "organization_id", name=op.f("pk_support_assignments")
        ),
    )
    op.create_index(
        op.f("ix_support_assignments__organization_id"),
        "support_assignments",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_support_assignments__organization_id"),
        table_name="support_assignments",
    )
    op.drop_table("support_assignments")

    op.drop_index(
        op.f("ix_region_assignments__region_id"), table_name="region_assignments"
    )
    op.drop_table("region_assignments")
