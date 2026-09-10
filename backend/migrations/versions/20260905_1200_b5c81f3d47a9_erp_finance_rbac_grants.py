"""iam: RBAC grants for school_erp (C11), platform_finance (C12) and plan management

Revision ID: b5c81f3d47a9
Revises: 7387f1b2ee6a
Create Date: 2026-09-05 12:00:00.000000

ADR-0040 §7. Three new permission namespaces, granted on three different principles:

**`school_erp.*` — the Organization -> Student money flow.**
`org_admin` gets full manage+list (it is their school's own money). The three RAAD staff roles
that already hold organization-wide read (`founder`, `regional_manager`, `support_staff`) get
**list only** — they support schools, they do not run their books. `finance_staff` gets list too:
`.claude/rules/security.md` #3 scopes that role to "billing scope only", and school finance is
squarely financial.

**`parent` receives nothing here, deliberately.** ADR-0038's closing constraint requires parent
access to school invoices to be *per-student-ownership* scoped, which is a separate design. A
role-wide `school_erp.student_invoices.list` grant would let any parent enumerate every family's
invoices at their school — exactly the stale-grant exposure ADR-0039 §7 had to clean up on the
SaaS billing surface. Not repeated.

**`platform_finance.*` — RAAD's own books.**
`founder` and `finance_staff` only. Not `regional_manager`, not `support_staff`, and above all
not `org_admin`: these tables carry no `organization_id`, so RBAC is the *only* gate on them
(there is no tenant column for a scope filter to match). A grant here is the whole control.

**`billing.plans.manage` — the plan catalogue's first write permission.**
Founder-only, and deliberately distinct from the read-only `billing.plans.list` that five roles
already hold: changing what RAAD charges is materially more sensitive than reading the price
list (`.claude/rules/security.md` #1, least privilege).

New additive migration, never an edit to an already-applied seed — the same posture every prior
grant migration in this chain takes.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b5c81f3d47a9"
down_revision: Union[str, None] = "7387f1b2ee6a"
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

#: Everything an Org Admin needs to run their school's finance end to end.
_SCHOOL_ERP_MANAGE = (
    "school_erp.categories.list",
    "school_erp.categories.manage",
    "school_erp.fee_plans.list",
    "school_erp.fee_plans.manage",
    "school_erp.student_invoices.list",
    "school_erp.student_invoices.manage",
    "school_erp.student_payments.list",
    "school_erp.student_payments.manage",
    "school_erp.income.list",
    "school_erp.income.manage",
    "school_erp.expenses.list",
    "school_erp.expenses.manage",
    "school_erp.reports.read",
)

#: The read-only subset RAAD staff get. Every `.manage` grant is absent by construction — this
#: tuple is filtered from the one above rather than retyped, so a future `.manage` permission
#: cannot be added to staff by accidentally copy-pasting it into the wrong list.
_SCHOOL_ERP_READ = tuple(p for p in _SCHOOL_ERP_MANAGE if not p.endswith(".manage"))

_PLATFORM_FINANCE = (
    "platform_finance.categories.list",
    "platform_finance.categories.manage",
    "platform_finance.expenses.list",
    "platform_finance.expenses.manage",
    "platform_finance.income.list",
    "platform_finance.income.manage",
    "platform_finance.reports.read",
)

_GRANTS: tuple[tuple[str, str], ...] = (
    # -- school_erp: the school runs its own books --------------------------------------------
    *((("org_admin", p) for p in _SCHOOL_ERP_MANAGE)),
    # -- school_erp: RAAD staff observe, never write ------------------------------------------
    *((("founder", p) for p in _SCHOOL_ERP_READ)),
    *((("regional_manager", p) for p in _SCHOOL_ERP_READ)),
    *((("support_staff", p) for p in _SCHOOL_ERP_READ)),
    *((("finance_staff", p) for p in _SCHOOL_ERP_READ)),
    # -- platform_finance: RAAD's own books, two roles only -----------------------------------
    *((("founder", p) for p in _PLATFORM_FINANCE)),
    *((("finance_staff", p) for p in _PLATFORM_FINANCE)),
    # -- billing plan catalogue management, Founder only ---------------------------------------
    ("founder", "billing.plans.manage"),
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
