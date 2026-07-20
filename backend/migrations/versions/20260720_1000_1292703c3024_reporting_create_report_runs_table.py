"""reporting: create report_runs table

Revision ID: 1292703c3024
Revises: 56e86806baa2
Create Date: 2026-07-20 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1292703c3024"
down_revision: Union[str, None] = "56e86806baa2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- report_runs (Database Design §8.6) -----------------------------------------------
    op.create_table(
        "report_runs",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("definition_key", sa.VARCHAR(length=80), nullable=False),
        sa.Column("params_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "succeeded", "failed", name="report_run_status"),
            nullable=False,
        ),
        sa.Column("artifact_url", sa.VARCHAR(length=500), nullable=True),
        sa.Column("requested_by", sa.CHAR(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_runs")),
    )
    op.create_index(
        op.f("ix_report_runs__organization_id"), "report_runs", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_report_runs__status"), "report_runs", ["status"], unique=False)
    op.create_index(
        op.f("ix_report_runs__requested_by"), "report_runs", ["requested_by"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_report_runs__requested_by"), table_name="report_runs")
    op.drop_index(op.f("ix_report_runs__status"), table_name="report_runs")
    op.drop_index(op.f("ix_report_runs__organization_id"), table_name="report_runs")
    op.drop_table("report_runs")

    # PostgreSQL native ENUM types outlive their owning table's DROP (ADR-0002) and must be
    # dropped explicitly, or a later re-upgrade's CREATE TYPE collides with the orphaned one.
    # `autogenerate` does not emit this; added by hand (see every prior ENUM-creating revision
    # this chain has, most recently 56e86806baa2).
    sa.Enum(name="report_run_status").drop(op.get_bind(), checkfirst=True)
