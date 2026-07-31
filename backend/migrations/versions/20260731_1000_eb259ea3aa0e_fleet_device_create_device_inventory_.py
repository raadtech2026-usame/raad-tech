"""fleet_device: create device_inventory, link devices.inventory_id

Revision ID: eb259ea3aa0e
Revises: d5f1b3a7c924
Create Date: 2026-07-31 10:00:00.000000

ADR-0018 (Device Inventory & Allocation) — implements the previously-drafted, then-formalized
`device_inventory` design (`docs/architecture/RAAD_DevicePlane_Architecture_v0_1_draft.md`
§3.5's Option 3). New table `device_inventory`: a platform-scoped, pre-tenant hardware pool —
deliberately **no `organization_id` column**, "like `regions`/`plans`, this is platform-level
stock" (ADR-0018 verbatim). Also adds `devices.inventory_id` (nullable FK, in-context since both
tables are owned by this same `fleet_device` module) so a device created via
`POST /device-inventory/{id}/allocate` links back to the inventory item it came from — zero
change to `devices.organization_id`'s existing `NOT NULL` constraint or to `Device`'s existing
lifecycle state machine.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "eb259ea3aa0e"
down_revision: Union[str, None] = "d5f1b3a7c924"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_inventory",
        sa.Column("serial_number", sa.VARCHAR(length=64), nullable=False),
        sa.Column("imei", sa.VARCHAR(length=32), nullable=True),
        sa.Column("iccid", sa.VARCHAR(length=32), nullable=True),
        sa.Column("model", sa.VARCHAR(length=120), nullable=True),
        sa.Column("vendor", sa.VARCHAR(length=120), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "manufactured",
                "in_stock",
                "allocated",
                "scrapped",
                name="device_inventory_state",
            ),
            nullable=False,
        ),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.CHAR(length=26), nullable=True),
        sa.Column("updated_by", sa.CHAR(length=26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device_inventory")),
        sa.UniqueConstraint(
            "serial_number", name=op.f("ux_device_inventory__serial_number")
        ),
        sa.UniqueConstraint("imei", name=op.f("ux_device_inventory__imei")),
        sa.UniqueConstraint("iccid", name=op.f("ux_device_inventory__iccid")),
    )
    op.create_index(
        op.f("ix_device_inventory__state"), "device_inventory", ["state"], unique=False
    )

    op.add_column("devices", sa.Column("inventory_id", sa.CHAR(length=26), nullable=True))
    op.create_index(
        op.f("ix_devices__inventory_id"), "devices", ["inventory_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_devices__device_inventory"),
        "devices",
        "device_inventory",
        ["inventory_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_devices__device_inventory"), "devices", type_="foreignkey"
    )
    op.drop_index(op.f("ix_devices__inventory_id"), table_name="devices")
    op.drop_column("devices", "inventory_id")

    op.drop_index(op.f("ix_device_inventory__state"), table_name="device_inventory")
    op.drop_table("device_inventory")
    # PostgreSQL native ENUM types outlive their owning table's DROP (ADR-0002) and must be
    # dropped explicitly, or a later re-upgrade's CREATE TYPE collides with the orphaned one —
    # same gotcha every prior `fleet_device` migration's downgrade already documents.
    sa.Enum(name="device_inventory_state").drop(op.get_bind(), checkfirst=True)
