"""transport_ops: add composite performance indexes for list and search queries

Revision ID: f7b8c9d0e1a2
Revises: e3a7c5d91b24
Create Date: 2026-11-01 12:00:00.000000

Adds composite indexes on students, parents, and student assignments to accelerate
tenant-scoped name lookups, sorting, and vehicle/route assignment joins.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f7b8c9d0e1a2"
down_revision: Union[str, None] = "e3a7c5d91b24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_students__organization_id_full_name",
        "students",
        ["organization_id", "full_name"],
        unique=False,
    )
    op.create_index(
        "ix_parents__organization_id_full_name",
        "parents",
        ["organization_id", "full_name"],
        unique=False,
    )
    op.create_index(
        "ix_student_assignments__route_vehicle_status",
        "student_assignments",
        ["route_id", "vehicle_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_student_assignments__route_vehicle_status", table_name="student_assignments")
    op.drop_index("ix_parents__organization_id_full_name", table_name="parents")
    op.drop_index("ix_students__organization_id_full_name", table_name="students")
