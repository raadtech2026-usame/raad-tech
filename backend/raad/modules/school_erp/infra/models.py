"""School ERP ORM models (ADR-0038 §2, ADR-0040 §2). SQLAlchemy is confined to this infra layer —
the domain and application layers never import it (`.claude/rules/backend.md` #2). PostgreSQL
types only (ADR-0002).

**Every table is tenant-owned and carries `organization_id`** (`.claude/rules/database.md` #2), a
plain indexed column and never a database FK — cross-context reference
(`.claude/rules/database.md` #3). That column is also what makes ADR-0021's central
`_apply_scope` work automatically on every read in this module.

**In-context FKs are real; cross-module ids are not.** `erp_student_invoices.fee_plan_id`,
`erp_student_payments.invoice_id` and `erp_financial_categories.parent_category_id` are genuine
`ForeignKey`s (all same-module). `student_id`, `route_id`, `vehicle_id` and `driver_id` are plain
indexed columns — they point at `transport_ops` and `fleet_device` aggregates.

**Money is `NUMERIC(12,2)`, never float** (ADR-0038 §3). The mappers convert to/from `Decimal`;
nothing in this module ever sees a binary float amount.

**Table names are prefixed `erp_`.** `invoices`/`payments` already exist in `billing` for the
RAAD->Organization flow, and ADR-0038 §2 requires the two to stay separate — an unprefixed
`student_invoices` would still read as "the invoices table's sibling" to someone scanning the
schema. The prefix makes the boundary visible in `\\dt` output.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    DATE,
    DECIMAL,
    VARCHAR,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import AuditedTableMixin

_CATEGORY_KIND_VALUES = ("income", "expense")
_CATEGORY_STATUS_VALUES = ("active", "inactive")
_FEE_PLAN_STATUS_VALUES = ("active", "inactive")
_STUDENT_INVOICE_STATUS_VALUES = (
    "draft",
    "issued",
    "partially_paid",
    "paid",
    "overdue",
    "cancelled",
)
_STUDENT_PAYMENT_METHOD_VALUES = (
    "cash",
    "bank_transfer",
    "mobile_money",
    "cheque",
    "card",
    "other",
)


class FinancialCategoryModel(AuditedTableMixin, Base):
    __tablename__ = "erp_financial_categories"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    name: Mapped[str] = mapped_column(VARCHAR(160), nullable=False)
    kind: Mapped[str] = mapped_column(
        SqlEnum(*_CATEGORY_KIND_VALUES, name="erp_category_kind"), nullable=False
    )
    parent_category_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("erp_financial_categories.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_CATEGORY_STATUS_VALUES, name="erp_category_status"), nullable=False
    )

    __table_args__ = (
        # A school cannot have two active categories with the same name on the same side of the
        # ledger — that is what makes a category picker unambiguous. Scoped by `kind` so
        # "Transport" can legitimately exist as both an income and an expense heading.
        UniqueConstraint(
            "organization_id",
            "kind",
            "name",
            name="ux_erp_financial_categories__org_kind_name",
        ),
        Index("ix_erp_financial_categories__org_kind", "organization_id", "kind"),
    )


class FeePlanModel(AuditedTableMixin, Base):
    __tablename__ = "erp_fee_plans"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    name: Mapped[str] = mapped_column(VARCHAR(160), nullable=False)
    amount: Mapped[Decimal] = mapped_column(DECIMAL(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    default_discount_amount: Mapped[Decimal] = mapped_column(
        DECIMAL(12, 2), nullable=False, default=Decimal("0.00")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_FEE_PLAN_STATUS_VALUES, name="erp_fee_plan_status"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="ux_erp_fee_plans__org_name"),
        Index("ix_erp_fee_plans__org_status", "organization_id", "status"),
    )


class StudentInvoiceModel(AuditedTableMixin, Base):
    """One period's transport charge to one student.

    The `student_id + period` unique constraint is the real enforcement behind
    `StudentInvoiceRepository.exists_for_student_period` — the application check catches the
    ordinary case with a clean error, and this index catches the concurrent one. Both are needed:
    a check alone loses a race, an index alone produces an opaque integrity error.
    """

    __tablename__ = "erp_student_invoices"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    fee_plan_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("erp_fee_plans.id"), nullable=True, index=True
    )
    period: Mapped[str] = mapped_column(CHAR(7), nullable=False)
    amount: Mapped[Decimal] = mapped_column(DECIMAL(12, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(
        DECIMAL(12, 2), nullable=False, default=Decimal("0.00")
    )
    amount_paid: Mapped[Decimal] = mapped_column(
        DECIMAL(12, 2), nullable=False, default=Decimal("0.00")
    )
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    due_date: Mapped[date] = mapped_column(DATE, nullable=False)
    status: Mapped[str] = mapped_column(
        SqlEnum(*_STUDENT_INVOICE_STATUS_VALUES, name="erp_student_invoice_status"),
        nullable=False,
    )
    # Transportation context captured at issue time (ADR-0040 §3) — cross-module references,
    # never FK-constrained, and never resolved live: a bill is a historical record.
    route_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True)
    vehicle_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True, index=True)
    driver_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "student_id", "period", name="ux_erp_student_invoices__student_period"
        ),
        # Backs the Vehicle Financial Overview's grouped query and the per-bus report.
        Index(
            "ix_erp_student_invoices__org_vehicle_period",
            "organization_id",
            "vehicle_id",
            "period",
        ),
        # Backs "who has not paid" and the overdue sweep.
        Index(
            "ix_erp_student_invoices__org_status_due",
            "organization_id",
            "status",
            "due_date",
        ),
    )


class StudentPaymentModel(AuditedTableMixin, Base):
    __tablename__ = "erp_student_payments"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    invoice_id: Mapped[str] = mapped_column(
        CHAR(26), ForeignKey("erp_student_invoices.id"), nullable=False, index=True
    )
    student_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(DECIMAL(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    method: Mapped[str] = mapped_column(
        SqlEnum(*_STUDENT_PAYMENT_METHOD_VALUES, name="erp_student_payment_method"),
        nullable=False,
    )
    reference: Mapped[str | None] = mapped_column(VARCHAR(120), nullable=True)
    received_on: Mapped[date] = mapped_column(DATE, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    voided_reason: Mapped[str | None] = mapped_column(VARCHAR(255), nullable=True)

    __table_args__ = (
        Index(
            "ix_erp_student_payments__org_received",
            "organization_id",
            "received_on",
        ),
    )


class IncomeModel(AuditedTableMixin, Base):
    __tablename__ = "erp_income"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    category_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("erp_financial_categories.id"), nullable=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(DECIMAL(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    occurred_on: Mapped[date] = mapped_column(DATE, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(VARCHAR(120), nullable=True)
    #: Nullable and never populated yet — no upload endpoint or blob store exists (ADR-0040
    #: Consequences). Present so adding one later is additive, not a financial-table migration.
    attachment_url: Mapped[str | None] = mapped_column(VARCHAR(500), nullable=True)
    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_erp_income__org_occurred", "organization_id", "occurred_on"),
    )


class ExpenseModel(AuditedTableMixin, Base):
    __tablename__ = "erp_expenses"

    organization_id: Mapped[str] = mapped_column(CHAR(26), nullable=False, index=True)
    category_id: Mapped[str | None] = mapped_column(
        CHAR(26), ForeignKey("erp_financial_categories.id"), nullable=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(DECIMAL(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    occurred_on: Mapped[date] = mapped_column(DATE, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(VARCHAR(120), nullable=True)
    #: Optional per-bus cost attribution (fuel, maintenance) — a cross-module reference to
    #: `fleet_device.Vehicle`, indexed so per-vehicle cost is a grouped query.
    vehicle_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True, index=True)
    attachment_url: Mapped[str | None] = mapped_column(VARCHAR(500), nullable=True)
    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_erp_expenses__org_occurred", "organization_id", "occurred_on"),
        Index("ix_erp_expenses__org_vehicle", "organization_id", "vehicle_id"),
    )
