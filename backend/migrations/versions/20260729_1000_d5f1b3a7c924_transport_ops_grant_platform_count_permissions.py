"""transport_ops: grant platform-wide students/parents count permissions

Revision ID: d5f1b3a7c924
Revises: c4d9a2e6f813
Create Date: 2026-07-29 10:00:00.000000

RAAD business model realignment: the same platform verification that produced `c4d9a2e6f813`
(revoking founder/regional_manager/support_staff's `transport_ops.students.*`/`.parents.*`
access) also surfaced the user's own explicit requirement that the RAAD Platform "may only
display aggregated statistics... Total Students (count only), Total Parents (count only)" —
i.e., a count is wanted even though individual listing must not be. `c4d9a2e6f813` alone left
no way to satisfy that: the only route that ever produced a total (`GET /students`/`GET
/parents`'s own `.total`) requires `.list`, exactly what was just revoked.

This migration grants the new, narrower `transport_ops.students.count`/`.parents.count`
permissions (backing the new `GET /students/count`/`GET /parents/count` routes, which return
only `{total: int}`, never row data) to the same three roles `c4d9a2e6f813` revoked `.list`/
`.create`/etc. from: founder, regional_manager, support_staff. `org_admin` is not granted
either — it already has full `.list` and has no need for a count-only route.

New additive migration, not an edit to any prior migration — same precedent as every other
RBAC-grant migration in this chain (`d3f7b8c2a915`, `22e94bc4e924`, `b8e2f4a91c67`,
`c4d9a2e6f813`).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d5f1b3a7c924"
down_revision: Union[str, None] = "c4d9a2e6f813"
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

_ROLES_GRANTED = ("founder", "regional_manager", "support_staff")
_PERMISSIONS_ADDED = ("transport_ops.students.count", "transport_ops.parents.count")

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)


def upgrade() -> None:
    op.bulk_insert(
        _role_permissions_table,
        [
            {"role": role, "permission": permission}
            for role in _ROLES_GRANTED
            for permission in _PERMISSIONS_ADDED
        ],
    )


def downgrade() -> None:
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.role.in_(_ROLES_GRANTED),
            _role_permissions_table.c.permission.in_(_PERMISSIONS_ADDED),
        )
    )
