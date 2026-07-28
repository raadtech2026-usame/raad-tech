"""iam: add users.is_password_change_required

Revision ID: c1a2e9f6d4b7
Revises: b6f2a19d3e7c
Create Date: 2026-07-28 10:00:00.000000

RAAD business model realignment (ADR-0017): backs the forced-password-change gate for
temporary, hand-off credentials (RAAD onboarding an Organization Admin; an Org Admin creating a
Parent/Driver account) — `users.is_password_change_required`, `NOT NULL BOOLEAN`, defaulting
`false` (an existing/self-registered user has no pending forced change). Backfilled `false` on
every existing row via the column's own server default, matching `approaching_distance_m`'s
identical backfill-via-server-default precedent (ADR-0014 amendment).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c1a2e9f6d4b7"
down_revision: Union[str, None] = "b6f2a19d3e7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_password_change_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_password_change_required")
