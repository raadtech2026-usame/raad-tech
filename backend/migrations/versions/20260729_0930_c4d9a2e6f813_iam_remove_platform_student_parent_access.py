"""iam: remove RAAD Platform access to transport_ops students/parents

Revision ID: c4d9a2e6f813
Revises: b8e2f4a91c67
Create Date: 2026-07-29 09:30:00.000000

Platform verification (2026-07-29) found the original `5437a5d1651b` seed grants founder (full
CRUD) and regional_manager/support_staff (list+read) unrestricted, platform-wide access to
`transport_ops.students.*`/`transport_ops.parents.*` — directly contradicting this project's own
already-approved Business Model (CLAUDE.md: "RAAD does not manage students or parents directly
... that stays this project's permanent out-of-scope boundary"). This is a correction to an
existing deviation, not a new access-control decision: `org_admin` already holds the correct,
unaffected full-CRUD grant (organizations manage their own students/parents), and
finance_staff/driver/parent already hold none.

Removes:
- founder: transport_ops.students.{create,list,read,update,update_status},
  transport_ops.parents.{create,list,read,update}
- regional_manager, support_staff: transport_ops.students.{list,read},
  transport_ops.parents.{list,read}

Exact precedent: `22e94bc4e924` (Device Domain Overhaul's `org_admin` device-permission revoke) —
same `delete().where(role.in_([...]), permission.in_([...]))` shape, new additive migration,
symmetric `downgrade()`, never editing the original seed migration in place.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4d9a2e6f813"
down_revision: Union[str, None] = "b8e2f4a91c67"
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

_FOUNDER_PERMISSIONS_REMOVED = [
    "transport_ops.students.create",
    "transport_ops.students.list",
    "transport_ops.students.read",
    "transport_ops.students.update",
    "transport_ops.students.update_status",
    "transport_ops.parents.create",
    "transport_ops.parents.list",
    "transport_ops.parents.read",
    "transport_ops.parents.update",
]

_READ_ONLY_STAFF_ROLES = ("regional_manager", "support_staff")

_READ_ONLY_STAFF_PERMISSIONS_REMOVED = [
    "transport_ops.students.list",
    "transport_ops.students.read",
    "transport_ops.parents.list",
    "transport_ops.parents.read",
]

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)


def upgrade() -> None:
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.role == "founder",
            _role_permissions_table.c.permission.in_(_FOUNDER_PERMISSIONS_REMOVED),
        )
    )
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.role.in_(_READ_ONLY_STAFF_ROLES),
            _role_permissions_table.c.permission.in_(
                _READ_ONLY_STAFF_PERMISSIONS_REMOVED
            ),
        )
    )


def downgrade() -> None:
    op.bulk_insert(
        _role_permissions_table,
        [
            {"role": "founder", "permission": permission}
            for permission in _FOUNDER_PERMISSIONS_REMOVED
        ]
        + [
            {"role": role, "permission": permission}
            for role in _READ_ONLY_STAFF_ROLES
            for permission in _READ_ONLY_STAFF_PERMISSIONS_REMOVED
        ],
    )
