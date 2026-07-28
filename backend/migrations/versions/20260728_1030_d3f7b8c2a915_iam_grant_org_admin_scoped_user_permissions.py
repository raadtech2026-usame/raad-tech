"""iam: grant org_admin scoped iam.users.* permissions

Revision ID: d3f7b8c2a915
Revises: c1a2e9f6d4b7
Create Date: 2026-07-28 10:30:00.000000

RAAD business model realignment (ADR-0003 accepted + ADR-0017): "Organization creates users
only for its own organization" (Parents, Drivers, additional Org Admin seats). `org_admin`
previously held zero `iam.users.*` grants at all — correct for the generic, unrestricted
`POST /users` invite flow (which has no per-caller scoping), but that also meant `Parent`/
`Driver` registration (`transport_ops`, which requires an already-existing `iam.User.id`,
Database Design §6.3/§6.1) could never actually be completed by an `org_admin`, since nothing
could create that prerequisite `User`.

This migration grants `org_admin` `iam.users.create`/`.read`/`.update` — safe now because
`UserApplicationService.invite_user`/`create_user_with_temporary_password` (`application/
services.py`) both enforce, in the application layer (not just at this permission-string level,
`.claude/rules/security.md` #2 defense-in-depth), that an `org_admin` actor may only create
`org_admin`/`driver`/`parent` roles, only within their own `organization_id` — never a
platform-staff role, never another organization. `founder`/`regional_manager`/`support_staff`
are unaffected (their existing `iam.users.*` grants already predate this migration and carry no
new restriction).

This is a new additive migration rather than an edit to `5437a5d1651b`/`22e94bc4e924` — those
seed migrations are already applied in any environment that has run the chain, and Alembic
migrations already run are never mutated in place (mirrors `22e94bc4e924`'s own precedent).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d3f7b8c2a915"
down_revision: Union[str, None] = "c1a2e9f6d4b7"
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

_ORG_ADMIN_PERMISSIONS_ADDED = [
    "iam.users.create",
    "iam.users.read",
    "iam.users.update",
]

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)


def upgrade() -> None:
    op.bulk_insert(
        _role_permissions_table,
        [
            {"role": "org_admin", "permission": permission}
            for permission in _ORG_ADMIN_PERMISSIONS_ADDED
        ],
    )


def downgrade() -> None:
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.role == "org_admin",
            _role_permissions_table.c.permission.in_(_ORG_ADMIN_PERMISSIONS_ADDED),
        )
    )
