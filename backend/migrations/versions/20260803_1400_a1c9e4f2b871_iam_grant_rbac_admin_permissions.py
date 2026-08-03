"""iam/organization: grant RBAC admin permissions

Revision ID: a1c9e4f2b871
Revises: d4fbe03f2b94
Create Date: 2026-08-03 14:00:00.000000

Priority 1 Item 6 (PROJECT_STATUS.md): the new role/permission-matrix and RAAD-staff
scope-assignment management routes (`POST /roles/{role}/permissions`,
`POST /scope-assignments/regions`, `POST /scope-assignments/support`, and their `/revoke`
counterparts + the two `GET` list routes) need a real RBAC grant to be reachable at all — every
other route in this codebase resolves through the same `require_permission` gate, and an
unseeded permission string means "nobody can ever call this," not "open to everyone."

Founder-only, deliberately: Database Design §4.4 names this "editable by Founder... without code
change" — the most sensitive action in the system, since it can grant any permission to any
role (including itself) or grant a Regional Manager/Support Staff scope assignment to any user.
No other role gets these grants.

New additive migration, not an edit to any prior seed — mirrors `7eb581884c39`'s own precedent
of never mutating an already-applied migration in place.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1c9e4f2b871"
down_revision: Union[str, None] = "d4fbe03f2b94"
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
    ("founder", "iam.role_permissions.list"),
    ("founder", "iam.role_permissions.grant"),
    ("founder", "iam.role_permissions.revoke"),
    ("founder", "organization.scope_assignments.list"),
    ("founder", "organization.scope_assignments.grant"),
    ("founder", "organization.scope_assignments.revoke"),
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
