"""core: create audit_entries table

Revision ID: 57ccbb4bfda1
Revises: 65009ecd235a
Create Date: 2026-07-21 10:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "57ccbb4bfda1"
down_revision: Union[str, None] = "65009ecd235a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- audit_entries (Database Design §8.7, ADR-0007) ------------------------------------
    # Shared-kernel table, mirroring `outbox` (Database Design §8.8): not owned by any single
    # bounded-context module's own migration chain the way `video_sessions`/`trips` are — see
    # `raad/core/audit/writer.py`'s module docstring and ADR-0007 for why. No `updated_at`/
    # `deleted_at` — append-only, immutable (§8.7's own note).
    op.create_table(
        "audit_entries",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=True),
        sa.Column("actor_user_id", sa.CHAR(length=26), nullable=True),
        sa.Column("action", sa.VARCHAR(length=80), nullable=False),
        sa.Column("entity_type", sa.VARCHAR(length=60), nullable=True),
        sa.Column("entity_id", sa.CHAR(length=26), nullable=True),
        sa.Column("metadata_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.VARCHAR(length=45), nullable=True),
        sa.Column("correlation_id", sa.CHAR(length=26), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_entries")),
    )
    op.create_index(
        op.f("ix_audit_entries__organization_id"),
        "audit_entries",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_entries__actor_user_id"),
        "audit_entries",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_entries__action"), "audit_entries", ["action"], unique=False
    )
    op.create_index(
        op.f("ix_audit_entries__correlation_id"),
        "audit_entries",
        ["correlation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_entries__created_at"), "audit_entries", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_entries__created_at"), table_name="audit_entries")
    op.drop_index(op.f("ix_audit_entries__correlation_id"), table_name="audit_entries")
    op.drop_index(op.f("ix_audit_entries__action"), table_name="audit_entries")
    op.drop_index(op.f("ix_audit_entries__actor_user_id"), table_name="audit_entries")
    op.drop_index(op.f("ix_audit_entries__organization_id"), table_name="audit_entries")
    op.drop_table("audit_entries")
