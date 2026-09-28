"""iam: RBAC grants for school_erp Parent Payments (ADR-0047 §10)

Revision ID: e5b1c8d2a4f7
Revises: e4a9c2b7d315
Create Date: 2026-09-28 10:15:00.000000

`school_erp.parent_payments.{list,manage}`, granted by the same split `a9c73e5f0b8d` uses for
`parent_invoices`: `org_admin` both (it is their school's own money), `founder`/
`regional_manager`/`support_staff`/`finance_staff` list only (`.claude/rules/security.md` #3 —
finance staff read school finance, never manage it), `parent` nothing. A parent reads their own
payments through `GET /me/invoices`, which is self-scoped and needs no grant.

Granted in the same change that introduces the routes checking them — the "a permission string
is not a grant" lesson this codebase learned when two ADR-0040 routes shipped ungranted.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5b1c8d2a4f7"
down_revision: Union[str, None] = "e4a9c2b7d315"
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

_PARENT_PAYMENTS_MANAGE = (
    "school_erp.parent_payments.list",
    "school_erp.parent_payments.manage",
)
_PARENT_PAYMENTS_READ = tuple(p for p in _PARENT_PAYMENTS_MANAGE if not p.endswith(".manage"))

_GRANTS: tuple[tuple[str, str], ...] = (
    *((("org_admin", p) for p in _PARENT_PAYMENTS_MANAGE)),
    *((("founder", p) for p in _PARENT_PAYMENTS_READ)),
    *((("regional_manager", p) for p in _PARENT_PAYMENTS_READ)),
    *((("support_staff", p) for p in _PARENT_PAYMENTS_READ)),
    *((("finance_staff", p) for p in _PARENT_PAYMENTS_READ)),
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
