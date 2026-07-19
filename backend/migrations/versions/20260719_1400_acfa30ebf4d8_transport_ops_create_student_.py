"""transport_ops: create student_assignments table

Revision ID: acfa30ebf4d8
Revises: 17753b338730
Create Date: 2026-07-19 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "acfa30ebf4d8"
down_revision: Union[str, None] = "17753b338730"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "student_assignments",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("student_id", sa.CHAR(length=26), nullable=False),
        sa.Column("route_id", sa.CHAR(length=26), nullable=False),
        sa.Column("pickup_stop_id", sa.CHAR(length=26), nullable=False),
        sa.Column("dropoff_stop_id", sa.CHAR(length=26), nullable=False),
        sa.Column("vehicle_id", sa.CHAR(length=26), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "removed",
                "transferred",
                "graduated",
                "disabled",
                name="student_assignment_status",
            ),
            nullable=False,
        ),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.CHAR(length=26), nullable=True),
        sa.Column("updated_by", sa.CHAR(length=26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"], name=op.f("fk_student_assignments__students")
        ),
        sa.ForeignKeyConstraint(
            ["route_id"], ["routes.id"], name=op.f("fk_student_assignments__routes")
        ),
        sa.ForeignKeyConstraint(
            ["pickup_stop_id"],
            ["stops.id"],
            name="fk_student_assignments__stops_pickup",
        ),
        sa.ForeignKeyConstraint(
            ["dropoff_stop_id"],
            ["stops.id"],
            name="fk_student_assignments__stops_dropoff",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_assignments")),
    )
    op.create_index(
        op.f("ix_student_assignments__organization_id"),
        "student_assignments",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_student_assignments__student_id"),
        "student_assignments",
        ["student_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_student_assignments__route_id"),
        "student_assignments",
        ["route_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_student_assignments__vehicle_id"),
        "student_assignments",
        ["vehicle_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_student_assignments__status"),
        "student_assignments",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_student_assignments__organization_id_status",
        "student_assignments",
        ["organization_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_student_assignments__student_id_status",
        "student_assignments",
        ["student_id", "status"],
        unique=False,
    )
    # One active (status='active') assignment per student (Database Design §6.7) - PostgreSQL
    # native partial unique index (ADR-0002), the same mechanism already used for
    # ux_device_assignments__active_vehicle / ux_trips__active_vehicle. autogenerate does not
    # emit `postgresql_where`; added by hand.
    op.create_index(
        "ux_student_assignments__active_student",
        "student_assignments",
        ["student_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_student_assignments__active_student", table_name="student_assignments"
    )
    op.drop_index(
        "ix_student_assignments__student_id_status", table_name="student_assignments"
    )
    op.drop_index(
        "ix_student_assignments__organization_id_status",
        table_name="student_assignments",
    )
    op.drop_index(
        op.f("ix_student_assignments__status"), table_name="student_assignments"
    )
    op.drop_index(
        op.f("ix_student_assignments__vehicle_id"), table_name="student_assignments"
    )
    op.drop_index(
        op.f("ix_student_assignments__route_id"), table_name="student_assignments"
    )
    op.drop_index(
        op.f("ix_student_assignments__student_id"), table_name="student_assignments"
    )
    op.drop_index(
        op.f("ix_student_assignments__organization_id"),
        table_name="student_assignments",
    )
    op.drop_table("student_assignments")
    # PostgreSQL native ENUM types outlive their owning table's DROP (ADR-0002) and must be
    # dropped explicitly, or a later re-upgrade's CREATE TYPE collides with the orphaned one.
    # `autogenerate` does not emit this; added by hand (see 8ffa6434d344/71b67f0e5709/
    # 17753b338730 for the same fix).
    sa.Enum(name="student_assignment_status").drop(op.get_bind(), checkfirst=True)
