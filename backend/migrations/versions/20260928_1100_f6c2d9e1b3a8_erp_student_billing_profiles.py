"""school_erp: per-student monthly fees (ADR-0048)

Revision ID: f6c2d9e1b3a8
Revises: e5b1c8d2a4f7
Create Date: 2026-09-28 11:00:00.000000

ADR-0048 replaces "one family fee split equally across the children" with each student's own
fee. A Parent Invoice line's amount is now the student's fee, and the invoice total their sum.

**Schema:**

- `erp_student_billing_profiles` — one row per `(organization_id, student_id)`: the student's
  monthly fee and currency. `monthly_fee >= 0`; zero records a student who rides free.
- `erp_parent_billing_profiles.monthly_fee` becomes **nullable** and is no longer read or
  written. It is kept, not dropped, so the family figure each profile carried under ADR-0042
  stays visible as history.
- `ux_erp_parent_invoices__org_parent_period` becomes a **partial** unique index
  (`WHERE status <> 'cancelled'`). As an unconditional constraint it made generation fail for
  any period in which one of the organization's invoices had been cancelled, and it made a
  corrected invoice impossible to issue after cancelling a wrong one.

**Backfill — no fee is invented.** Existing invoice amounts are untouched: every line keeps the
amount it was generated with. A student gets a fee only if they have actually been billed:
their fee becomes the amount of their line on their most recent non-cancelled Parent Invoice
(latest period, then latest generated), in that invoice's currency. That is the figure the
family has been paying for that child, so next month's invoice for an unchanged family equals
this month's.

A student who has never been on a Parent Invoice gets **no** fee. The monthly run skips them and
reports them as `no_fee` until an admin sets one — dividing a family figure by a head count is
exactly the equal split ADR-0048 retires, so it is not done here either. The migration prints
how many fees it created and how many active billing profiles still have unpriced children.

`downgrade()` drops the new table, fills any NULL `monthly_fee` back in from the sum of the
linked students' fees (0 where there are none) and restores NOT NULL, and restores the
unconditional unique constraint. It refuses — rather than deleting a financial row — if a period
now holds both a cancelled and a live invoice for the same family.
"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from raad.core.ids.generator import generate_ulid

revision: str = "f6c2d9e1b3a8"
down_revision: Union[str, None] = "e5b1c8d2a4f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INVOICE_UNIQUE = "ux_erp_parent_invoices__org_parent_period"


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("created_by", sa.CHAR(26), nullable=True),
        sa.Column("updated_by", sa.CHAR(26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=False), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "erp_student_billing_profiles",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("student_id", sa.CHAR(26), nullable=False),
        sa.Column("monthly_fee", sa.DECIMAL(12, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_erp_student_billing_profiles")),
        sa.UniqueConstraint(
            "organization_id", "student_id", name="ux_erp_student_billing_profiles__org_student"
        ),
        sa.CheckConstraint("monthly_fee >= 0", name="ck_erp_student_billing_profiles__fee"),
    )
    op.create_index(
        "ix_erp_student_billing_profiles__organization_id",
        "erp_student_billing_profiles",
        ["organization_id"],
    )

    op.alter_column(
        "erp_parent_billing_profiles",
        "monthly_fee",
        existing_type=sa.DECIMAL(12, 2),
        nullable=True,
    )

    op.drop_constraint(_INVOICE_UNIQUE, "erp_parent_invoices", type_="unique")
    op.create_index(
        _INVOICE_UNIQUE,
        "erp_parent_invoices",
        ["organization_id", "parent_id", "period"],
        unique=True,
        postgresql_where=sa.text("status <> 'cancelled'"),
    )

    _backfill_student_fees()


def _backfill_student_fees() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    latest_lines = bind.execute(
        sa.text(
            "SELECT DISTINCT ON (l.organization_id, l.student_id) "
            "l.organization_id, l.student_id, l.amount, i.currency "
            "FROM erp_parent_invoice_lines l "
            "JOIN erp_parent_invoices i ON i.id = l.parent_invoice_id "
            "WHERE i.status <> 'cancelled' AND i.deleted_at IS NULL AND l.deleted_at IS NULL "
            "ORDER BY l.organization_id, l.student_id, i.period DESC, i.created_at DESC, "
            "l.id DESC"
        )
    ).fetchall()
    for line in latest_lines:
        bind.execute(
            sa.text(
                "INSERT INTO erp_student_billing_profiles (id, created_at, updated_at, "
                "row_version, organization_id, student_id, monthly_fee, currency) "
                "VALUES (:id, :now, :now, 1, :org, :student, :fee, :currency)"
            ),
            {
                "id": generate_ulid(),
                "now": now,
                "org": line.organization_id,
                "student": line.student_id,
                "fee": line.amount,
                "currency": line.currency,
            },
        )

    unpriced = bind.execute(
        sa.text(
            "SELECT COUNT(DISTINCT sp.student_id) FROM erp_parent_billing_profiles b "
            "JOIN student_parents sp ON sp.parent_id = b.parent_id "
            "JOIN students s ON s.id = sp.student_id AND s.status = 'active' "
            "AND s.deleted_at IS NULL "
            "LEFT JOIN erp_student_billing_profiles f ON f.student_id = sp.student_id "
            "AND f.organization_id = b.organization_id "
            "WHERE b.status = 'active' AND b.deleted_at IS NULL AND f.id IS NULL"
        )
    ).scalar()
    print(
        f"f6c2d9e1b3a8: {len(latest_lines)} student fee(s) taken from each student's most "
        f"recent invoice line; {unpriced} active student(s) under an active billing profile "
        "have no fee yet and will not be invoiced until one is set."
    )


def downgrade() -> None:
    bind = op.get_bind()
    clashes = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT 1 FROM erp_parent_invoices "
            "GROUP BY organization_id, parent_id, period HAVING COUNT(*) > 1) AS dup"
        )
    ).scalar()
    if clashes:
        raise RuntimeError(
            f"f6c2d9e1b3a8 downgrade refused: {clashes} family/period(s) hold a cancelled and a "
            "live Parent Invoice, which the restored unconditional unique constraint cannot "
            "hold. Financial rows are never deleted by a migration; resolve them first."
        )
    op.drop_index(_INVOICE_UNIQUE, table_name="erp_parent_invoices")
    op.create_unique_constraint(
        _INVOICE_UNIQUE, "erp_parent_invoices", ["organization_id", "parent_id", "period"]
    )

    bind.execute(
        sa.text(
            "UPDATE erp_parent_billing_profiles b SET monthly_fee = COALESCE(("
            "SELECT SUM(f.monthly_fee) FROM student_parents sp "
            "JOIN erp_student_billing_profiles f ON f.student_id = sp.student_id "
            "AND f.organization_id = b.organization_id "
            "WHERE sp.parent_id = b.parent_id), 0) "
            "WHERE b.monthly_fee IS NULL"
        )
    )
    op.alter_column(
        "erp_parent_billing_profiles",
        "monthly_fee",
        existing_type=sa.DECIMAL(12, 2),
        nullable=False,
    )

    op.drop_index(
        "ix_erp_student_billing_profiles__organization_id",
        table_name="erp_student_billing_profiles",
    )
    op.drop_table("erp_student_billing_profiles")
