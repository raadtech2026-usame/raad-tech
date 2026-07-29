"""iam: grant iam.users.reset_password permission

Revision ID: b8e2f4a91c67
Revises: f4a1c9e7b302
Create Date: 2026-07-29 09:00:00.000000

ADR-0017 Amendment (2026-07-29): a real gap surfaced during a platform verification pass — an
Org Admin who loses their one-time temporary password before ever logging in had no recovery
path at all, since `POST /auth/change-password` is self-service-only. This migration seeds the
new `iam.users.reset_password` permission (backing `POST /users/{user_id}/reset-password`) for
the same roles that already hold `iam.users.update` as of `d3f7b8c2a915`: founder,
regional_manager, support_staff — mirroring that existing grant shape rather than deciding a
new access-control policy from scratch. `org_admin` is deliberately NOT granted this permission
this phase — the request this migration satisfies scopes the capability to "RAAD Super Admin
resets an Org Admin," not "an Org Admin resets their own org's users," so extending it to
`org_admin` is left for a future, separately-decided phase rather than assumed here.

New additive migration, not an edit to any prior seed — mirrors `d3f7b8c2a915`'s and
`22e94bc4e924`'s own precedent of never mutating an already-applied migration in place.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b8e2f4a91c67"
down_revision: Union[str, None] = "f4a1c9e7b302"
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
_PERMISSION_ADDED = "iam.users.reset_password"

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role", sa.Enum(*_ROLE_VALUES, name="role_permission_role")),
    sa.column("permission", sa.VARCHAR()),
)


def upgrade() -> None:
    op.bulk_insert(
        _role_permissions_table,
        [
            {"role": role, "permission": _PERMISSION_ADDED}
            for role in _ROLES_GRANTED
        ],
    )


def downgrade() -> None:
    op.execute(
        _role_permissions_table.delete().where(
            _role_permissions_table.c.role.in_(_ROLES_GRANTED),
            _role_permissions_table.c.permission == _PERMISSION_ADDED,
        )
    )
