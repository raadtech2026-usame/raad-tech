"""iam: RBAC grants for school_erp Parent Billing Profile / Parent Invoice (ADR-0042)

Revision ID: a9c73e5f0b8d
Revises: d4e8f2a71c53
Create Date: 2026-09-11 10:15:00.000000

Mirrors `20260905_1200_b5c81f3d47a9_erp_finance_rbac_grants.py`'s own `_SCHOOL_ERP_MANAGE`/
`_SCHOOL_ERP_READ` split exactly, for the two new resources ADR-0042 introduces: `org_admin` gets
full manage+list (it is their school's own billing), `founder`/`regional_manager`/`support_staff`/
`finance_staff` get list-only (support/observe, never write another school's family billing —
`.claude/rules/security.md` #3), and `parent` gets neither — a role-wide `school_erp.parent_
invoices.list` grant would let a parent enumerate every family's invoices at their school, the
identical exposure the original migration's own docstring already flags for `student_invoices`.

New additive migration, never an edit to an already-applied seed — the same posture every prior
grant migration in this chain takes (`.claude/rules/workflow.md` #5).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a9c73e5f0b8d"
down_revision: Union[str, None] = "d4e8f2a71c53"
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

_PARENT_BILLING_MANAGE = (
    "school_erp.parent_billing_profiles.list",
    "school_erp.parent_billing_profiles.manage",
    "school_erp.parent_invoices.list",
    "school_erp.parent_invoices.manage",
)

#: The read-only subset RAAD staff get — filtered from the tuple above rather than retyped, the
#: same "a `.manage` permission cannot land on staff by copy-paste" precedent the original
#: migration already establishes for `_SCHOOL_ERP_READ`.
_PARENT_BILLING_READ = tuple(p for p in _PARENT_BILLING_MANAGE if not p.endswith(".manage"))

_GRANTS: tuple[tuple[str, str], ...] = (
    *((("org_admin", p) for p in _PARENT_BILLING_MANAGE)),
    *((("founder", p) for p in _PARENT_BILLING_READ)),
    *((("regional_manager", p) for p in _PARENT_BILLING_READ)),
    *((("support_staff", p) for p in _PARENT_BILLING_READ)),
    *((("finance_staff", p) for p in _PARENT_BILLING_READ)),
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
