"""platform_audit: create system_settings table

Revision ID: 6dfdcc8b1b09
Revises: 57ccbb4bfda1
Create Date: 2026-07-21 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6dfdcc8b1b09"
down_revision: Union[str, None] = "57ccbb4bfda1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- system_settings (Database Design §8.9) ---------------------------------------------
    # `key` is the primary key (not a ULID `id`) - capped at 26 chars, matching
    # domain/value_objects.SystemSettingKey's own enforced max (see that VO's docstring: the
    # shared DomainEvent.aggregate_id / audit_entries.entity_id CHAR(26) constraint).
    op.create_table(
        "system_settings",
        sa.Column("key", sa.VARCHAR(length=26), nullable=False),
        sa.Column("value_json", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("scope", sa.VARCHAR(length=60), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_settings")),
    )


def downgrade() -> None:
    op.drop_table("system_settings")
