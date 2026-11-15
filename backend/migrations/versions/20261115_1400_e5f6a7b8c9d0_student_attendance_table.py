"""transport_ops: create student_attendance table for daily trip attendance

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-15 14:00:00.000000

Supports driver daily student attendance tracking per trip and organization
admin attendance reporting with filters per bus, student, date and status.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "student_attendance",
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("trip_id", sa.CHAR(length=26), nullable=False),
        sa.Column("student_id", sa.CHAR(length=26), nullable=False),
        sa.Column("vehicle_id", sa.CHAR(length=26), nullable=True),
        sa.Column("route_id", sa.CHAR(length=26), nullable=True),
        sa.Column("attendance_date", sa.Date(), nullable=False),
        sa.Column("status", sa.VARCHAR(length=32), nullable=False, server_default="present"),
        sa.Column("marked_by_user_id", sa.CHAR(length=26), nullable=True),
        sa.Column("marked_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("notes", sa.VARCHAR(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], name=op.f("fk_student_attendance__students")),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], name=op.f("fk_student_attendance__trips")),
        sa.ForeignKeyConstraint(["route_id"], ["routes.id"], name=op.f("fk_student_attendance__routes")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_attendance")),
        sa.UniqueConstraint(
            "organization_id",
            "trip_id",
            "student_id",
            "attendance_date",
            name="ux_student_attendance__org_trip_student_date",
        ),
    )
    op.create_index(
        "ix_student_attendance__org_date",
        "student_attendance",
        ["organization_id", "attendance_date"],
        unique=False,
    )
    op.create_index(
        "ix_student_attendance__student_date",
        "student_attendance",
        ["student_id", "attendance_date"],
        unique=False,
    )
    op.create_index(
        "ix_student_attendance__trip_student",
        "student_attendance",
        ["trip_id", "student_id"],
        unique=False,
    )
    op.create_index(
        "ix_student_attendance__vehicle_date",
        "student_attendance",
        ["vehicle_id", "attendance_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_student_attendance__vehicle_date", table_name="student_attendance")
    op.drop_index("ix_student_attendance__trip_student", table_name="student_attendance")
    op.drop_index("ix_student_attendance__student_date", table_name="student_attendance")
    op.drop_index("ix_student_attendance__org_date", table_name="student_attendance")
    op.drop_table("student_attendance")
