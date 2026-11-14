"""transport_ops: make route_id, pickup_stop_id, dropoff_stop_id nullable in student_assignments

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-14 12:00:00.000000

Supports vehicle-only assignments for students and family transportation where
bus route and pickup/dropoff stops are assigned later or optional.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "student_assignments",
        "route_id",
        existing_type=sa.CHAR(length=26),
        nullable=True,
    )
    op.alter_column(
        "student_assignments",
        "pickup_stop_id",
        existing_type=sa.CHAR(length=26),
        nullable=True,
    )
    op.alter_column(
        "student_assignments",
        "dropoff_stop_id",
        existing_type=sa.CHAR(length=26),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "student_assignments",
        "dropoff_stop_id",
        existing_type=sa.CHAR(length=26),
        nullable=False,
    )
    op.alter_column(
        "student_assignments",
        "pickup_stop_id",
        existing_type=sa.CHAR(length=26),
        nullable=False,
    )
    op.alter_column(
        "student_assignments",
        "route_id",
        existing_type=sa.CHAR(length=26),
        nullable=False,
    )
