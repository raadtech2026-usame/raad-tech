"""iam: create role_permissions table, seed RBAC permission matrix

Revision ID: 5437a5d1651b
Revises: 1292703c3024
Create Date: 2026-07-21 09:00:00.000000

Seed data derives every (role, permission) grant from two sources only — never invented:
1. API Contracts §3.2's role -> capability table (Platform admin / Manage orgs / Ops
   monitoring / Live video / Billing / Start-End trip).
2. Every individual route's own documented "Role" column (API Contracts §4.1-§4.8) or, for
   routes with no API Contracts row at all (Driver CRUD, StudentParent linking, etc.), the
   role already encoded in that route's own `require_permission(...)` docstring when it was
   built in an earlier phase.

See `docs/architecture/adr/0004-rbac-permission-matrix.md` for the full derivation table and
the "in-scope admin" / RAAD-staff-vs-Org-Admin scoping rationale.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "5437a5d1651b"
down_revision: Union[str, None] = "1292703c3024"
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

_ALL_PERMISSIONS = [
    "iam.users.create",
    "iam.users.read",
    "iam.users.update",
    "organization.organizations.create",
    "organization.organizations.read",
    "organization.organizations.update",
    "organization.regions.create",
    "organization.regions.read",
    "organization.regions.update",
    "fleet_device.vehicles.create",
    "fleet_device.vehicles.read",
    "fleet_device.vehicles.update",
    "fleet_device.devices.create",
    "fleet_device.devices.read",
    "fleet_device.devices.update",
    "fleet_device.devices.activate",
    "fleet_device.devices.assign",
    "fleet_device.devices.reassign",
    "fleet_device.devices.unassign",
    "transport_ops.students.create",
    "transport_ops.students.list",
    "transport_ops.students.read",
    "transport_ops.students.update",
    "transport_ops.students.update_status",
    "transport_ops.parents.create",
    "transport_ops.parents.list",
    "transport_ops.parents.read",
    "transport_ops.parents.update",
    "transport_ops.student_parents.create",
    "transport_ops.student_parents.delete",
    "transport_ops.student_parents.list",
    "transport_ops.drivers.create",
    "transport_ops.drivers.list",
    "transport_ops.drivers.read",
    "transport_ops.drivers.update",
    "transport_ops.routes.create",
    "transport_ops.routes.list",
    "transport_ops.routes.read",
    "transport_ops.routes.update",
    "transport_ops.routes.stops.create",
    "transport_ops.routes.stops.list",
    "transport_ops.trips.create",
    "transport_ops.trips.list",
    "transport_ops.trips.read",
    "transport_ops.trips.start",
    "transport_ops.trips.end",
    "transport_ops.trips.change_driver",
    "transport_ops.student_assignments.create",
    "transport_ops.student_assignments.list",
    "transport_ops.student_assignments.read",
    "transport_ops.student_assignments.end",
    "tracking.vehicles.read_latest",
    "tracking.trips.read_positions",
    "billing.plans.list",
    "billing.subscriptions.list",
    "billing.invoices.list",
    "billing.payments.create",
    "notifications.tokens.create",
    "notifications.tokens.delete",
    "notifications.notifications.list",
    "notifications.notifications.read",
    "notifications.notifications.update",
    "reporting.reports.create",
    "reporting.reports.read",
    "video.live.start",
    "video.playback.start",
    "video.sessions.stop",
    "admin.audit.read",
    "admin.settings.read",
    "admin.settings.update",
]

_TRANSPORT_OPS_READ_ONLY = [
    "transport_ops.students.list",
    "transport_ops.students.read",
    "transport_ops.parents.list",
    "transport_ops.parents.read",
    "transport_ops.student_parents.list",
    "transport_ops.drivers.list",
    "transport_ops.drivers.read",
    "transport_ops.routes.list",
    "transport_ops.routes.read",
    "transport_ops.routes.stops.list",
    "transport_ops.trips.list",
    "transport_ops.trips.read",
    "transport_ops.student_assignments.list",
    "transport_ops.student_assignments.read",
]

_TRANSPORT_OPS_FULL_CRUD = [p for p in _ALL_PERMISSIONS if p.startswith("transport_ops.")]

_ORG_ADMIN_PERMISSIONS = (
    [
        "organization.organizations.read",
        "organization.organizations.update",
        "fleet_device.vehicles.create",
        "fleet_device.vehicles.read",
        "fleet_device.vehicles.update",
        "fleet_device.devices.create",
        "fleet_device.devices.read",
        "fleet_device.devices.update",
        "fleet_device.devices.activate",
        "fleet_device.devices.assign",
        "fleet_device.devices.reassign",
        "fleet_device.devices.unassign",
    ]
    + _TRANSPORT_OPS_FULL_CRUD
    + [
        "tracking.vehicles.read_latest",
        "tracking.trips.read_positions",
        "billing.plans.list",
        "billing.subscriptions.list",
        "billing.invoices.list",
        "billing.payments.create",
        "notifications.notifications.list",
        "notifications.notifications.read",
        "notifications.notifications.update",
        "notifications.tokens.delete",
        "reporting.reports.create",
        "reporting.reports.read",
        "video.live.start",
        "video.playback.start",
        "video.sessions.stop",
        "admin.settings.read",
        "admin.settings.update",
    ]
)

_RAAD_STAFF_READ_ONLY = (
    [
        "iam.users.read",
        "organization.organizations.read",
        "organization.regions.read",
        "fleet_device.vehicles.read",
        "fleet_device.devices.read",
    ]
    + _TRANSPORT_OPS_READ_ONLY
    + [
        "tracking.vehicles.read_latest",
        "tracking.trips.read_positions",
        "billing.plans.list",
        "admin.audit.read",
    ]
)

_REGIONAL_MANAGER_PERMISSIONS = _RAAD_STAFF_READ_ONLY + [
    "organization.organizations.update",  # region-scoped
    "video.live.start",
    "video.playback.start",
]

_SUPPORT_STAFF_PERMISSIONS = _RAAD_STAFF_READ_ONLY + [
    "fleet_device.devices.create",
    "fleet_device.devices.update",
    "fleet_device.devices.activate",
    "video.live.start",
    "video.playback.start",
]

_FINANCE_STAFF_PERMISSIONS = [
    "billing.plans.list",
    "billing.subscriptions.list",
    "billing.invoices.list",
    "billing.payments.create",
    "reporting.reports.create",
    "reporting.reports.read",
    "notifications.notifications.list",
    "notifications.notifications.read",
    "notifications.notifications.update",
    "notifications.tokens.delete",
]

_DRIVER_PERMISSIONS = [
    "transport_ops.trips.list",
    "transport_ops.trips.read",
    "transport_ops.trips.start",
    "transport_ops.trips.end",
    "notifications.tokens.create",
    "notifications.tokens.delete",
    "notifications.notifications.list",
    "notifications.notifications.read",
    "notifications.notifications.update",
]

_PARENT_PERMISSIONS = [
    "tracking.vehicles.read_latest",
    "tracking.trips.read_positions",
    "billing.plans.list",
    "billing.subscriptions.list",
    "billing.invoices.list",
    "billing.payments.create",
    "notifications.tokens.create",
    "notifications.tokens.delete",
    "notifications.notifications.list",
    "notifications.notifications.read",
    "notifications.notifications.update",
    "reporting.reports.read",
]

_MATRIX: dict[str, list[str]] = {
    "founder": _ALL_PERMISSIONS,
    "regional_manager": _REGIONAL_MANAGER_PERMISSIONS,
    "support_staff": _SUPPORT_STAFF_PERMISSIONS,
    "finance_staff": _FINANCE_STAFF_PERMISSIONS,
    "org_admin": _ORG_ADMIN_PERMISSIONS,
    "driver": _DRIVER_PERMISSIONS,
    "parent": _PARENT_PERMISSIONS,
}


def upgrade() -> None:
    op.create_table(
        "role_permissions",
        sa.Column(
            "role",
            sa.Enum(*_ROLE_VALUES, name="role_permission_role"),
            primary_key=True,
        ),
        sa.Column("permission", sa.VARCHAR(length=120), primary_key=True),
    )

    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
        sa.column("permission", sa.VARCHAR()),
    )
    rows = [
        {"role": role, "permission": permission}
        for role, permissions in _MATRIX.items()
        for permission in sorted(set(permissions))
    ]
    op.bulk_insert(role_permissions_table, rows)


def downgrade() -> None:
    op.drop_table("role_permissions")
    sa.Enum(name="role_permission_role").drop(op.get_bind(), checkfirst=True)
