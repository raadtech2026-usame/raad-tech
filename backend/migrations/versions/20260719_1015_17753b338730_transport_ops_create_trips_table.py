"""transport_ops: create trips table

Revision ID: 17753b338730
Revises: 71b67f0e5709
Create Date: 2026-07-19 10:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "17753b338730"
down_revision: Union[str, None] = "71b67f0e5709"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trips",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("vehicle_id", sa.CHAR(length=26), nullable=False),
        sa.Column("driver_id", sa.CHAR(length=26), nullable=False),
        sa.Column("route_id", sa.CHAR(length=26), nullable=False),
        sa.Column(
            "trip_type",
            sa.Enum("morning", "afternoon", name="trip_type"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "scheduled",
                "in_progress",
                "interrupted",
                "completed",
                name="trip_status",
            ),
            nullable=False,
        ),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.CHAR(length=26), nullable=True),
        sa.Column("updated_by", sa.CHAR(length=26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["driver_id"], ["drivers.id"], name=op.f("fk_trips__drivers")
        ),
        sa.ForeignKeyConstraint(
            ["route_id"], ["routes.id"], name=op.f("fk_trips__routes")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trips")),
    )
    op.create_index(
        op.f("ix_trips__organization_id"), "trips", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_trips__vehicle_id"), "trips", ["vehicle_id"], unique=False)
    op.create_index(op.f("ix_trips__driver_id"), "trips", ["driver_id"], unique=False)
    op.create_index(op.f("ix_trips__route_id"), "trips", ["route_id"], unique=False)
    op.create_index(op.f("ix_trips__status"), "trips", ["status"], unique=False)
    op.create_index(
        op.f("ix_trips__scheduled_date"), "trips", ["scheduled_date"], unique=False
    )
    op.create_index(
        "ix_trips__organization_id_scheduled_date_status",
        "trips",
        ["organization_id", "scheduled_date", "status"],
        unique=False,
    )
    # One active (in_progress) trip per vehicle (Database Design §6.8) - PostgreSQL native
    # partial unique index (ADR-0002), the same mechanism already used for
    # ux_device_assignments__active_vehicle. autogenerate does not emit `postgresql_where`;
    # added by hand.
    op.create_index(
        "ux_trips__active_vehicle",
        "trips",
        ["vehicle_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )


def downgrade() -> None:
    op.drop_index("ux_trips__active_vehicle", table_name="trips")
    op.drop_index(
        "ix_trips__organization_id_scheduled_date_status", table_name="trips"
    )
    op.drop_index(op.f("ix_trips__scheduled_date"), table_name="trips")
    op.drop_index(op.f("ix_trips__status"), table_name="trips")
    op.drop_index(op.f("ix_trips__route_id"), table_name="trips")
    op.drop_index(op.f("ix_trips__driver_id"), table_name="trips")
    op.drop_index(op.f("ix_trips__vehicle_id"), table_name="trips")
    op.drop_index(op.f("ix_trips__organization_id"), table_name="trips")
    op.drop_table("trips")
    # PostgreSQL native ENUM types outlive their owning table's DROP (ADR-0002) and must be
    # dropped explicitly, or a later re-upgrade's CREATE TYPE collides with the orphaned one.
    # `autogenerate` does not emit this; added by hand (see 8ffa6434d344/71b67f0e5709 for the
    # same fix).
    sa.Enum(name="trip_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="trip_type").drop(op.get_bind(), checkfirst=True)
