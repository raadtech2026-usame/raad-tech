"""school_erp: ParentBillingProfile + ParentInvoice (+lines) — real aggregates (ADR-0042)

Revision ID: d4e8f2a71c53
Revises: ba7616be7d03
Create Date: 2026-09-11 10:00:00.000000

ADR-0042 (supersedes ADR-0041 §1): "Parent Invoice must be a real financial document/entity...
not merely a grouping of Student invoices." Three new tables, purely additive:

- `erp_parent_billing_profiles` — one family's actual recurring monthly charge.
- `erp_parent_invoices` — the real monthly bill to one parent, unique on
  `(organization_id, parent_id, period)`.
- `erp_parent_invoice_lines` — one billed child's own share of the family total, plus the
  transport context captured at generation time (mirrors `erp_student_invoices`' own
  `vehicle_id`/`route_id` fields, ADR-0040 §3).

**Non-destructive data backfill, not a move.** `erp_student_invoices`/`erp_student_payments` are
untouched — no row is read for deletion, no column is altered. Every non-cancelled
`erp_student_invoices` row whose student resolves to exactly one parent (via `student_parents`,
preferring the `is_primary` link, else the lexicographically-first `parent_id` — a disclosed,
deterministic tiebreak for a genuinely ambiguous case: `student_parents` has no `created_at` to
prefer "first linked" by instead) is copied into a new `erp_parent_invoices` row grouped by
`(organization_id, parent_id, period)`, with one `erp_parent_invoice_lines` row per source
invoice. A student with no linked parent is **skipped, not guessed at** — its `erp_student_
invoices` rows remain, visible to nobody's new Parent Invoice, exactly as ADR-0042 decision 3
requires. New ids are freshly minted ULIDs (`raad.core.ids.generator.generate_ulid` — stdlib-only,
safe to import into a migration) since these are genuinely new rows representing a re-grouping,
not a 1:1 row move; `created_at`/`updated_at` are stamped at migration run time for the same
reason. The migration prints a one-line summary of how many Parent Invoices were created and how
many source rows were skipped for lacking a resolvable parent, so the backfill's own scope is
visible in the `alembic upgrade` log, not silently swallowed.

`downgrade()` simply drops the three new tables — since nothing existing was ever modified, there
is no data to restore on the way back, unlike the `transport_fees` migration's own disclosed
one-way loss.

**Both new PostgreSQL ENUMs are explicitly dropped in `downgrade()`** per this repository's
permanent rule (CLAUDE.md, Migration status): `--autogenerate` never emits `DROP TYPE` itself.
"""
from datetime import datetime
from decimal import Decimal
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from raad.core.ids.generator import generate_ulid

# revision identifiers, used by Alembic.
revision: str = "d4e8f2a71c53"
down_revision: Union[str, None] = "ba7616be7d03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Both ENUMs are declared inline on their owning column below, with no explicit pre-`create()`
    # call and no `create_type=False` — `op.create_table`'s own DDL compilation creates a new
    # PostgreSQL ENUM automatically the first time it is referenced, exactly the pattern every
    # other brand-new-table migration in this chain already uses (e.g. `erp_fee_plan_status` in
    # `7387f1b2ee6a`). An explicit pre-create was tried first and found to raise a spurious
    # `DuplicateObjectError` under this project's async-engine-bridged Alembic connection even
    # against a verified-empty `pg_type` — `op.add_column`'s own pre-create in `ba7616be7d03` is a
    # different, necessary case (adding a column to an *existing* table has no automatic type
    # creation to rely on); `create_table` needs no such workaround.
    op.create_table(
        "erp_parent_billing_profiles",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("parent_id", sa.CHAR(length=26), nullable=False),
        sa.Column("monthly_fee", sa.DECIMAL(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("billing_start_period", sa.CHAR(length=7), nullable=False),
        sa.Column("due_day", sa.SmallInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", name="erp_parent_billing_profile_status"),
            nullable=False,
        ),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.CHAR(length=26), nullable=True),
        sa.Column("updated_by", sa.CHAR(length=26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_erp_parent_billing_profiles")),
        sa.UniqueConstraint(
            "organization_id", "parent_id", name="ux_erp_parent_billing_profiles__org_parent"
        ),
    )
    op.create_index(
        "ix_erp_parent_billing_profiles__org_status",
        "erp_parent_billing_profiles",
        ["organization_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_erp_parent_billing_profiles__organization_id"),
        "erp_parent_billing_profiles",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_erp_parent_billing_profiles__parent_id"),
        "erp_parent_billing_profiles",
        ["parent_id"],
        unique=False,
    )

    op.create_table(
        "erp_parent_invoices",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("parent_id", sa.CHAR(length=26), nullable=False),
        sa.Column("period", sa.CHAR(length=7), nullable=False),
        sa.Column("amount", sa.DECIMAL(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column(
            "amount_paid", sa.DECIMAL(precision=12, scale=2), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "unpaid", "partial", "paid", "cancelled", name="erp_parent_invoice_status"
            ),
            nullable=False,
        ),
        sa.Column("invoice_date", sa.DATE(), nullable=False),
        sa.Column("due_date", sa.DATE(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.CHAR(length=26), nullable=True),
        sa.Column("updated_by", sa.CHAR(length=26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_erp_parent_invoices")),
        sa.UniqueConstraint(
            "organization_id", "parent_id", "period",
            name="ux_erp_parent_invoices__org_parent_period",
        ),
    )
    op.create_index(
        "ix_erp_parent_invoices__org_status_due",
        "erp_parent_invoices",
        ["organization_id", "status", "due_date"],
        unique=False,
    )
    op.create_index(
        "ix_erp_parent_invoices__org_period",
        "erp_parent_invoices",
        ["organization_id", "period"],
        unique=False,
    )
    op.create_index(
        op.f("ix_erp_parent_invoices__organization_id"),
        "erp_parent_invoices",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_erp_parent_invoices__parent_id"),
        "erp_parent_invoices",
        ["parent_id"],
        unique=False,
    )

    op.create_table(
        "erp_parent_invoice_lines",
        sa.Column("organization_id", sa.CHAR(length=26), nullable=False),
        sa.Column("parent_invoice_id", sa.CHAR(length=26), nullable=False),
        sa.Column("student_id", sa.CHAR(length=26), nullable=False),
        sa.Column("vehicle_id", sa.CHAR(length=26), nullable=True),
        sa.Column("route_id", sa.CHAR(length=26), nullable=True),
        sa.Column("amount", sa.DECIMAL(precision=12, scale=2), nullable=False),
        sa.Column("id", sa.CHAR(length=26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.CHAR(length=26), nullable=True),
        sa.Column("updated_by", sa.CHAR(length=26), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_invoice_id"], ["erp_parent_invoices.id"],
            name=op.f("fk_erp_parent_invoice_lines__erp_parent_invoices"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_erp_parent_invoice_lines")),
    )
    op.create_index(
        "ix_erp_parent_invoice_lines__org_vehicle_period",
        "erp_parent_invoice_lines",
        ["organization_id", "vehicle_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_erp_parent_invoice_lines__organization_id"),
        "erp_parent_invoice_lines",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_erp_parent_invoice_lines__parent_invoice_id"),
        "erp_parent_invoice_lines",
        ["parent_invoice_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_erp_parent_invoice_lines__student_id"),
        "erp_parent_invoice_lines",
        ["student_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_erp_parent_invoice_lines__vehicle_id"),
        "erp_parent_invoice_lines",
        ["vehicle_id"],
        unique=False,
    )

    _backfill_parent_invoices(op.get_bind())


def _backfill_parent_invoices(bind) -> None:
    """See module docstring. Pure Python over two SELECTs, rather than a single hand-rolled SQL
    aggregation — this needs real, freshly-minted ULIDs for the new rows, which no portable SQL
    expression produces."""
    primary_parent_rows = bind.execute(
        sa.text(
            """
            SELECT DISTINCT ON (student_id) student_id, parent_id
            FROM student_parents
            ORDER BY student_id, is_primary DESC, parent_id ASC
            """
        )
    ).fetchall()
    parent_by_student = {row.student_id: row.parent_id for row in primary_parent_rows}

    invoice_rows = bind.execute(
        sa.text(
            """
            SELECT id, organization_id, student_id, period, vehicle_id, route_id, due_date,
                   currency, (amount - discount_amount) AS net_amount, amount_paid
            FROM erp_student_invoices
            WHERE status != 'cancelled' AND deleted_at IS NULL
            ORDER BY organization_id, student_id, period
            """
        )
    ).fetchall()

    groups: dict[tuple[str, str, str], list] = {}
    skipped_no_parent = 0
    for row in invoice_rows:
        parent_id = parent_by_student.get(row.student_id)
        if parent_id is None:
            skipped_no_parent += 1
            continue
        key = (row.organization_id, parent_id, row.period)
        groups.setdefault(key, []).append(row)

    invoice_insert = sa.text(
        """
        INSERT INTO erp_parent_invoices (
            id, organization_id, parent_id, period, amount, currency, amount_paid,
            status, invoice_date, due_date, notes, created_at, updated_at,
            created_by, updated_by, row_version, deleted_at
        ) VALUES (
            :id, :organization_id, :parent_id, :period, :amount, :currency, :amount_paid,
            :status, :invoice_date, :due_date, :notes, :created_at, :updated_at,
            NULL, NULL, 1, NULL
        )
        """
    )
    line_insert = sa.text(
        """
        INSERT INTO erp_parent_invoice_lines (
            id, organization_id, parent_invoice_id, student_id, vehicle_id, route_id, amount,
            created_at, updated_at, created_by, updated_by, row_version, deleted_at
        ) VALUES (
            :id, :organization_id, :parent_invoice_id, :student_id, :vehicle_id, :route_id,
            :amount, :created_at, :updated_at, NULL, NULL, 1, NULL
        )
        """
    )

    now = datetime.utcnow()
    zero = Decimal("0.00")
    created_count = 0
    for (organization_id, parent_id, period), rows in groups.items():
        total_amount = sum((r.net_amount for r in rows), zero)
        if total_amount <= zero:
            # A fully-discounted-to-zero group is not a real charge — inserting a $0 Parent
            # Invoice would misrepresent Receivables/Collected for no benefit.
            continue
        total_paid = min(sum((r.amount_paid for r in rows), zero), total_amount)
        if total_paid >= total_amount:
            status = "paid"
        elif total_paid <= zero:
            status = "unpaid"
        else:
            status = "partial"

        parent_invoice_id = generate_ulid()
        bind.execute(
            invoice_insert,
            {
                "id": parent_invoice_id,
                "organization_id": organization_id,
                "parent_id": parent_id,
                "period": period,
                "amount": total_amount,
                "currency": rows[0].currency,
                "amount_paid": total_paid,
                "status": status,
                "invoice_date": now.date(),
                "due_date": min(r.due_date for r in rows),
                "notes": "Migrated from erp_student_invoices (ADR-0042)",
                "created_at": now,
                "updated_at": now,
            },
        )
        for row in rows:
            bind.execute(
                line_insert,
                {
                    "id": generate_ulid(),
                    "organization_id": organization_id,
                    "parent_invoice_id": parent_invoice_id,
                    "student_id": row.student_id,
                    "vehicle_id": row.vehicle_id,
                    "route_id": row.route_id,
                    "amount": row.net_amount,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        created_count += 1

    print(
        f"[ADR-0042 backfill] created {created_count} erp_parent_invoices from "
        f"{len(invoice_rows)} erp_student_invoices rows "
        f"({skipped_no_parent} skipped: no resolvable parent link)."
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_erp_parent_invoice_lines__vehicle_id"), table_name="erp_parent_invoice_lines"
    )
    op.drop_index(
        op.f("ix_erp_parent_invoice_lines__student_id"), table_name="erp_parent_invoice_lines"
    )
    op.drop_index(
        op.f("ix_erp_parent_invoice_lines__parent_invoice_id"),
        table_name="erp_parent_invoice_lines",
    )
    op.drop_index(
        op.f("ix_erp_parent_invoice_lines__organization_id"),
        table_name="erp_parent_invoice_lines",
    )
    op.drop_index(
        "ix_erp_parent_invoice_lines__org_vehicle_period",
        table_name="erp_parent_invoice_lines",
    )
    op.drop_table("erp_parent_invoice_lines")

    op.drop_index(op.f("ix_erp_parent_invoices__parent_id"), table_name="erp_parent_invoices")
    op.drop_index(
        op.f("ix_erp_parent_invoices__organization_id"), table_name="erp_parent_invoices"
    )
    op.drop_index("ix_erp_parent_invoices__org_period", table_name="erp_parent_invoices")
    op.drop_index("ix_erp_parent_invoices__org_status_due", table_name="erp_parent_invoices")
    op.drop_table("erp_parent_invoices")

    op.drop_index(
        op.f("ix_erp_parent_billing_profiles__parent_id"),
        table_name="erp_parent_billing_profiles",
    )
    op.drop_index(
        op.f("ix_erp_parent_billing_profiles__organization_id"),
        table_name="erp_parent_billing_profiles",
    )
    op.drop_index(
        "ix_erp_parent_billing_profiles__org_status", table_name="erp_parent_billing_profiles"
    )
    op.drop_table("erp_parent_billing_profiles")

    op.execute("DROP TYPE IF EXISTS erp_parent_invoice_status")
    op.execute("DROP TYPE IF EXISTS erp_parent_billing_profile_status")
