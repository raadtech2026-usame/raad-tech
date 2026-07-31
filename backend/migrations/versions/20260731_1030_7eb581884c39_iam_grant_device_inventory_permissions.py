"""iam: grant device_inventory permissions

Revision ID: 7eb581884c39
Revises: eb259ea3aa0e
Create Date: 2026-07-31 10:30:00.000000

ADR-0018 §3: `org_admin` gains `fleet_device.devices.read` — a narrow, tenant-scoped, read-only
reversal of `22e94bc4e924`'s earlier removal of every `fleet_device.devices.*` grant from this
role, satisfying "Organization immediately sees the assigned device" without reopening device
management (`org_admin` still holds no `.create`/`.update`/`.activate`/`.assign`/`.reassign`/
`.unassign`). Also grants `founder`/`support_staff` the two new ADR-0018 §2 routes'
permissions: `fleet_device.device_inventory.create` (`POST /device-inventory`) and
`fleet_device.device_inventory.allocate` (`POST /device-inventory/{id}/allocate`) — the same
role pair that already holds every other `fleet_device.devices.*` write permission
(`5437a5d1651b`).

New additive migration, not an edit to any prior seed — mirrors `d3f7b8c2a915`'s,
`22e94bc4e924`'s, and `b8e2f4a91c67`'s own precedent of never mutating an already-applied
migration in place.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7eb581884c39"
down_revision: Union[str, None] = "eb259ea3aa0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE_VALUES = (
    "founder",
    "regional_manager",
    "support_staff",
    "finance_staff",
    "org_admin",
    "driver",
    "parent",
)

_GRANTS = (
    ("org_admin", "fleet_device.devices.read"),
    ("founder", "fleet_device.device_inventory.create"),
    ("support_staff", "fleet_device.device_inventory.create"),
    ("founder", "fleet_device.device_inventory.allocate"),
    ("support_staff", "fleet_device.device_inventory.allocate"),
)

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)


def upgrade() -> None:
    op.bulk_insert(
        _role_permissions_table,
        [{"role": role, "permission": permission} for role, permission in _GRANTS],
    )


def downgrade() -> None:
    for role, permission in _GRANTS:
        op.execute(
            _role_permissions_table.delete().where(
                _role_permissions_table.c.role == role,
                _role_permissions_table.c.permission == permission,
            )
        )
