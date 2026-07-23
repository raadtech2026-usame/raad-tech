"""fleet_device add device hardware identity columns

Revision ID: a43c7de2fad5
Revises: 6dfdcc8b1b09
Create Date: 2026-07-23 20:58:40.843637

Adds `imei`/`iccid`/`serial_number` to `devices` (Database Design §5.2's previously-flagged
gap — RAAD technician hardware-intake needs these for theft/fraud checks, SIM-swap detection,
and warehouse/RMA workflows, per the Device Domain Overhaul architecture review). All three
are nullable (a technician may not have all three on hand at registration time, same posture
as the existing `model`/`vendor`/`sim_msisdn`) with a global `UNIQUE` constraint each, mirroring
`terminal_id`'s existing precedent — PostgreSQL's standard UNIQUE already permits multiple NULLs,
so no partial index is needed.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a43c7de2fad5"
down_revision: Union[str, None] = "6dfdcc8b1b09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("imei", sa.VARCHAR(length=32), nullable=True))
    op.add_column("devices", sa.Column("iccid", sa.VARCHAR(length=32), nullable=True))
    op.add_column(
        "devices", sa.Column("serial_number", sa.VARCHAR(length=64), nullable=True)
    )
    op.create_unique_constraint(op.f("ux_devices__imei"), "devices", ["imei"])
    op.create_unique_constraint(op.f("ux_devices__iccid"), "devices", ["iccid"])
    op.create_unique_constraint(
        op.f("ux_devices__serial_number"), "devices", ["serial_number"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ux_devices__serial_number"), "devices", type_="unique")
    op.drop_constraint(op.f("ux_devices__iccid"), "devices", type_="unique")
    op.drop_constraint(op.f("ux_devices__imei"), "devices", type_="unique")
    op.drop_column("devices", "serial_number")
    op.drop_column("devices", "iccid")
    op.drop_column("devices", "imei")
