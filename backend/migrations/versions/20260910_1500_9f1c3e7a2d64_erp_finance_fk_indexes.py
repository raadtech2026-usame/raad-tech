"""school_erp/platform_finance: index the FK columns no existing composite index leads with

Revision ID: 9f1c3e7a2d64
Revises: c2f4a9d18e37
Create Date: 2026-09-10 15:00:00.000000

**Pre-deployment audit finding (§F), confirmed against the actual migration before writing
this.** `7387f1b2ee6a` (the original ERP finance migration) indexes every tenant/reporting
access path it anticipated — `(organization_id, occurred_on)`, `(organization_id, vehicle_id)`,
`(organization_id, status, due_date)` and so on — but five FK columns end up with no index that
*leads* with them: `erp_expenses.category_id`, `erp_income.category_id`,
`erp_student_invoices.fee_plan_id`, `platform_expenses.category_id`,
`platform_income.category_id`. A "show me everything under this category" or "everyone on this
fee plan" query — the natural next feature once `FeePlanForm`/`CategoryForm` grow an edit view —
would full-scan these tables today. `platform_expenses.category_id`/`platform_income.category_id`
are the sharper case: those tables carry no `organization_id` at all (ADR-0040 §1, deliberately —
RBAC is the whole tenant gate), so there is no other leading column a category lookup could ride
on.

Purely additive — no column, constraint, or data change. Safe to apply against a live database;
`CONCURRENTLY` is not used because Alembic's default migration transaction already wraps this
file, and none of the five tables is large enough yet for a plain `CREATE INDEX`'s brief lock to
matter operationally.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f1c3e7a2d64"
down_revision: Union[str, None] = "c2f4a9d18e37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_erp_expenses__category_id"), "erp_expenses", ["category_id"], unique=False
    )
    op.create_index(
        op.f("ix_erp_income__category_id"), "erp_income", ["category_id"], unique=False
    )
    op.create_index(
        op.f("ix_erp_student_invoices__fee_plan_id"),
        "erp_student_invoices",
        ["fee_plan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_platform_expenses__category_id"),
        "platform_expenses",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_platform_income__category_id"),
        "platform_income",
        ["category_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_platform_income__category_id"), table_name="platform_income")
    op.drop_index(op.f("ix_platform_expenses__category_id"), table_name="platform_expenses")
    op.drop_index(
        op.f("ix_erp_student_invoices__fee_plan_id"), table_name="erp_student_invoices"
    )
    op.drop_index(op.f("ix_erp_income__category_id"), table_name="erp_income")
    op.drop_index(op.f("ix_erp_expenses__category_id"), table_name="erp_expenses")
