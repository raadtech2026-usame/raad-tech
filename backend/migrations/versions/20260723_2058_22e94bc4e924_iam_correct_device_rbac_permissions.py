"""iam correct device rbac permissions

Revision ID: 22e94bc4e924
Revises: a43c7de2fad5
Create Date: 2026-07-23 20:58:48.542378

Corrects the seeded `role_permissions` matrix (`5437a5d1651b`) against RAAD's actual business
model (Device Domain Overhaul architecture review): RAAD owns all hardware and only RAAD staff
may register/configure/assign devices — schools (`org_admin`) never see or manage devices at
all, not even a read-only view (an `org_admin` session's device-connectivity visibility is
served instead by `fleet_device.vehicles.tracking_status`, which rides the `vehicles.*`
permission `org_admin` already holds unchanged).

Removes all seven `fleet_device.devices.*` grants from `org_admin`. Adds `.assign`/`.reassign`/
`.unassign` to `support_staff` (the operational "RAAD technician" role) — it already held
`.create`/`.update`/`.activate`, so was missing exactly the permissions needed to complete a
device-to-vehicle onboarding end to end. `founder` is unaffected (`_ALL_PERMISSIONS`).

This is a new additive migration rather than an edit to `5437a5d1651b` — that seed migration is
already applied in this and any other environment that has run the chain, and Alembic
migrations already run are never mutated in place.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '22e94bc4e924'
down_revision: Union[str, None] = 'a43c7de2fad5'
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

_ORG_ADMIN_DEVICE_PERMISSIONS_REMOVED = [
    "fleet_device.devices.create",
    "fleet_device.devices.read",
    "fleet_device.devices.update",
    "fleet_device.devices.activate",
    "fleet_device.devices.assign",
    "fleet_device.devices.reassign",
    "fleet_device.devices.unassign",
]

_SUPPORT_STAFF_PERMISSIONS_ADDED = [
    "fleet_device.devices.assign",
    "fleet_device.devices.reassign",
    "fleet_device.devices.unassign",
]

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)


def upgrade() -> None:
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.role == "org_admin",
            _role_permissions_table.c.permission.in_(
                _ORG_ADMIN_DEVICE_PERMISSIONS_REMOVED
            ),
        )
    )
    op.bulk_insert(
        _role_permissions_table,
        [
            {"role": "support_staff", "permission": permission}
            for permission in _SUPPORT_STAFF_PERMISSIONS_ADDED
        ],
    )


def downgrade() -> None:
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.role == "support_staff",
            _role_permissions_table.c.permission.in_(
                _SUPPORT_STAFF_PERMISSIONS_ADDED
            ),
        )
    )
    op.bulk_insert(
        _role_permissions_table,
        [
            {"role": "org_admin", "permission": permission}
            for permission in _ORG_ADMIN_DEVICE_PERMISSIONS_REMOVED
        ],
    )
