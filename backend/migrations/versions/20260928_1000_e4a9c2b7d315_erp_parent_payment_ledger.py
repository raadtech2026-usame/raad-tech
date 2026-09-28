"""school_erp: parent payment ledger, per-student paid amounts, vehicle income (ADR-0047)

Revision ID: e4a9c2b7d315
Revises: b3d7e1f94a26
Create Date: 2026-09-28 10:00:00.000000

ADR-0047 (amending ADR-0042 §4) replaces "set a paid amount on the invoice" with real payment
records allocated to each student's invoice line.

**Schema, all additive:**

- `erp_parent_payments` — one row per payment: method, reference, received date, void state,
  optional `idempotency_key` (partial unique per organization).
- `erp_parent_payment_allocations` — which student's line each part of a payment paid, with the
  line's frozen `vehicle_id` copied in (ADR-0047 §5).
- `erp_parent_invoice_lines.amount_paid` — what each student has paid, kept equal to the sum of
  that line's non-voided allocations.
- `erp_income.income_type` (`daily_vehicle`/`other`, existing rows become `other`) and
  `erp_income.vehicle_id` (ADR-0047 §6).

**Backfill.** Every non-cancelled invoice whose `amount_paid > 0` was paid through the old
Unpaid/Partial/Paid control and has no payment record. Each becomes exactly one payment:

| Field | Value |
|---|---|
| method | `other` |
| reference | `Recorded before payment ledger` |
| received_on | the invoice's last `updated_at` date — the closest recorded fact about when it was marked paid |
| created_by | NULL, i.e. "system" |

The amount is allocated to the invoice's lines pro-rata by line amount, rounding each share down
to the cent and handing leftover cents to lines in order (the ADR-0047 §3 rule, applied to
charges instead of balances since nothing is paid yet). Invoice totals and statuses are not
touched — only the ledger that explains them is created. An invoice with no lines cannot be
allocated and is skipped; the count is printed.

`downgrade()` drops the new tables and columns and both new enum types. Invoices keep their
`amount_paid`/`status`, so the ADR-0042 status model is intact after a downgrade.

**Enum creation.** `erp_parent_payment_method` is declared inline on `op.create_table`, the
pattern ADR-0042's migration established for brand-new tables. `erp_income_type` goes onto an
*existing* table through `op.add_column`, which never creates a type implicitly, so it is created
explicitly first and referenced with `create_type=False` (the `ba7616be7d03` precedent).
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from raad.core.ids.generator import generate_ulid

revision: str = "e4a9c2b7d315"
down_revision: Union[str, None] = "b3d7e1f94a26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PAYMENT_METHODS = ("cash", "bank_transfer", "mobile_money", "cheque", "card", "other")
_BACKFILL_REFERENCE = "Recorded before payment ledger"
_BACKFILL_NOTE = (
    "Created by migration e4a9c2b7d315 from the amount marked paid under the previous "
    "Unpaid/Partial/Paid control (ADR-0047 §4)."
)


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
        "erp_parent_payments",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column("parent_id", sa.CHAR(26), nullable=False),
        sa.Column(
            "parent_invoice_id",
            sa.CHAR(26),
            sa.ForeignKey(
                "erp_parent_invoices.id", name="fk_erp_parent_payments__erp_parent_invoices"
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.DECIMAL(12, 2), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("method", sa.Enum(*_PAYMENT_METHODS, name="erp_parent_payment_method"), nullable=False),
        sa.Column("reference", sa.VARCHAR(120), nullable=True),
        sa.Column("received_on", sa.DATE(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_voided", sa.Boolean(), nullable=False),
        sa.Column("voided_reason", sa.VARCHAR(255), nullable=True),
        sa.Column("idempotency_key", sa.VARCHAR(64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_erp_parent_payments")),
    )
    op.create_index(
        "ix_erp_parent_payments__organization_id", "erp_parent_payments", ["organization_id"]
    )
    op.create_index("ix_erp_parent_payments__parent_id", "erp_parent_payments", ["parent_id"])
    op.create_index(
        "ix_erp_parent_payments__parent_invoice_id", "erp_parent_payments", ["parent_invoice_id"]
    )
    op.create_index(
        "ix_erp_parent_payments__org_received",
        "erp_parent_payments",
        ["organization_id", "received_on"],
    )
    op.create_index(
        "ux_erp_parent_payments__org_idempotency_key",
        "erp_parent_payments",
        ["organization_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "erp_parent_payment_allocations",
        *_audit_columns(),
        sa.Column("organization_id", sa.CHAR(26), nullable=False),
        sa.Column(
            "parent_payment_id",
            sa.CHAR(26),
            sa.ForeignKey(
                "erp_parent_payments.id",
                name="fk_erp_parent_payment_allocations__erp_parent_payments",
            ),
            nullable=False,
        ),
        sa.Column(
            "parent_invoice_line_id",
            sa.CHAR(26),
            sa.ForeignKey(
                "erp_parent_invoice_lines.id",
                name="fk_erp_parent_payment_allocations__erp_parent_invoice_lines",
            ),
            nullable=False,
        ),
        sa.Column("student_id", sa.CHAR(26), nullable=False),
        sa.Column("vehicle_id", sa.CHAR(26), nullable=True),
        sa.Column("amount", sa.DECIMAL(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_erp_parent_payment_allocations")),
    )
    for name, columns in (
        ("ix_erp_parent_payment_allocations__organization_id", ["organization_id"]),
        ("ix_erp_parent_payment_allocations__parent_payment_id", ["parent_payment_id"]),
        ("ix_erp_parent_payment_allocations__parent_invoice_line_id", ["parent_invoice_line_id"]),
        ("ix_erp_parent_payment_allocations__student_id", ["student_id"]),
        ("ix_erp_parent_payment_allocations__org_vehicle", ["organization_id", "vehicle_id"]),
    ):
        op.create_index(name, "erp_parent_payment_allocations", columns)

    op.add_column(
        "erp_parent_invoice_lines",
        sa.Column("amount_paid", sa.DECIMAL(12, 2), nullable=False, server_default="0"),
    )

    income_type = sa.Enum("daily_vehicle", "other", name="erp_income_type")
    income_type.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "erp_income",
        sa.Column(
            "income_type",
            sa.Enum("daily_vehicle", "other", name="erp_income_type", create_type=False),
            nullable=False,
            server_default="other",
        ),
    )
    op.add_column("erp_income", sa.Column("vehicle_id", sa.CHAR(26), nullable=True))
    op.create_index("ix_erp_income__org_vehicle", "erp_income", ["organization_id", "vehicle_id"])

    _backfill_payments()


def _allocate(total: Decimal, capacities: list[Decimal]) -> list[Decimal]:
    """Pro-rata by capacity, each share rounded down to the cent, leftover cents to lines in
    order while they have room — sums exactly to `total`, never over a line's capacity."""
    total_cents = int((total * 100).to_integral_value())
    caps = [int((c * 100).to_integral_value()) for c in capacities]
    capacity_total = sum(caps)
    shares = [total_cents * cap // capacity_total for cap in caps]
    leftover = total_cents - sum(shares)
    index = 0
    while leftover > 0:
        position = index % len(caps)
        if shares[position] < caps[position]:
            shares[position] += 1
            leftover -= 1
        index += 1
    return [Decimal(cents) / 100 for cents in shares]


def _backfill_payments() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    invoices = bind.execute(
        sa.text(
            "SELECT id, organization_id, parent_id, amount_paid, currency, updated_at "
            "FROM erp_parent_invoices "
            "WHERE amount_paid > 0 AND status <> 'cancelled' AND deleted_at IS NULL "
            "ORDER BY id"
        )
    ).fetchall()

    migrated = skipped = 0
    for invoice in invoices:
        lines = bind.execute(
            sa.text(
                "SELECT id, student_id, vehicle_id, amount FROM erp_parent_invoice_lines "
                "WHERE parent_invoice_id = :invoice_id AND deleted_at IS NULL ORDER BY id"
            ),
            {"invoice_id": invoice.id},
        ).fetchall()
        capacities = [Decimal(line.amount) for line in lines]
        paid = Decimal(invoice.amount_paid)
        if not lines or sum(capacities) <= 0 or paid > sum(capacities):
            skipped += 1
            continue

        payment_id = generate_ulid()
        bind.execute(
            sa.text(
                "INSERT INTO erp_parent_payments (id, created_at, updated_at, row_version, "
                "organization_id, parent_id, parent_invoice_id, amount, currency, method, "
                "reference, received_on, notes, is_voided) VALUES (:id, :now, :now, 1, :org, "
                ":parent, :invoice, :amount, :currency, 'other', :reference, :received_on, "
                ":notes, false)"
            ),
            {
                "id": payment_id,
                "now": now,
                "org": invoice.organization_id,
                "parent": invoice.parent_id,
                "invoice": invoice.id,
                "amount": paid,
                "currency": invoice.currency,
                "reference": _BACKFILL_REFERENCE,
                "received_on": invoice.updated_at.date(),
                "notes": _BACKFILL_NOTE,
            },
        )
        for line, share in zip(lines, _allocate(paid, capacities)):
            if share <= 0:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO erp_parent_payment_allocations (id, created_at, updated_at, "
                    "row_version, organization_id, parent_payment_id, parent_invoice_line_id, "
                    "student_id, vehicle_id, amount) VALUES (:id, :now, :now, 1, :org, "
                    ":payment, :line, :student, :vehicle, :amount)"
                ),
                {
                    "id": generate_ulid(),
                    "now": now,
                    "org": invoice.organization_id,
                    "payment": payment_id,
                    "line": line.id,
                    "student": line.student_id,
                    "vehicle": line.vehicle_id,
                    "amount": share,
                },
            )
            bind.execute(
                sa.text("UPDATE erp_parent_invoice_lines SET amount_paid = :paid WHERE id = :id"),
                {"paid": share, "id": line.id},
            )
        migrated += 1

    print(
        f"e4a9c2b7d315: {migrated} parent invoice(s) given a payment record, "
        f"{skipped} skipped (no lines to allocate to)."
    )


def downgrade() -> None:
    op.drop_index("ix_erp_income__org_vehicle", table_name="erp_income")
    op.drop_column("erp_income", "vehicle_id")
    op.drop_column("erp_income", "income_type")
    op.execute("DROP TYPE IF EXISTS erp_income_type")

    op.drop_column("erp_parent_invoice_lines", "amount_paid")

    op.drop_table("erp_parent_payment_allocations")
    op.drop_table("erp_parent_payments")
    op.execute("DROP TYPE IF EXISTS erp_parent_payment_method")
