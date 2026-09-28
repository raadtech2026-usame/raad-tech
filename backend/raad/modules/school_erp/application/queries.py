"""Read-side query DTOs for `school_erp` (Backend LLD §4.1).

DTOs are the module's public read shape — the API layer serialises these, never domain
aggregates, so a domain refactor cannot silently change the wire contract.

**Monetary fields cross this boundary as `str`, not `float`.** A `Decimal` is not JSON-
serialisable and casting to `float` on the way out would reintroduce exactly the rounding error
this module chose `Decimal` to avoid — "1234.56" is exact, `1234.5599999999999` is what a float
round-trip produces. Every consumer (the frontend included) parses the string.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from raad.modules.school_erp.domain.entities import (
    Expense,
    FeePlan,
    FinancialCategory,
    Income,
    ParentBillingProfile,
    ParentInvoice,
    ParentPayment,
    StudentInvoice,
    StudentPayment,
)
from raad.modules.school_erp.domain.repositories import FinanceTotals


def _money(value: Decimal) -> str:
    """See module docstring: exact decimal string, never a float."""
    return f"{value:.2f}"


# ---- Query objects -------------------------------------------------------------------------


@dataclass(frozen=True)
class GetStudentInvoiceByIdQuery:
    invoice_id: str


@dataclass(frozen=True)
class ListStudentInvoicesForStudentQuery:
    student_id: str


@dataclass(frozen=True)
class VehicleFinancialOverviewQuery:
    """`period` is optional — omitted means "all time", which is what an outstanding-balance view
    needs, while a supplied `YYYY-MM` gives the month's own revenue."""

    period: str | None = None


@dataclass(frozen=True)
class ProfitAndLossQuery:
    start: date
    end: date


# ---- DTOs ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class FinancialCategoryDTO:
    id: str
    organization_id: str
    name: str
    kind: str
    parent_category_id: str | None
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


def financial_category_to_dto(category: FinancialCategory) -> FinancialCategoryDTO:
    return FinancialCategoryDTO(
        id=str(category.id),
        organization_id=str(category.organization_id),
        name=category.name,
        kind=category.kind.value,
        parent_category_id=(
            str(category.parent_category_id) if category.parent_category_id else None
        ),
        description=category.description,
        status=category.status.value,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


@dataclass(frozen=True)
class FeePlanDTO:
    id: str
    organization_id: str
    name: str
    amount: str
    currency: str
    default_discount_amount: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


def fee_plan_to_dto(fee_plan: FeePlan) -> FeePlanDTO:
    return FeePlanDTO(
        id=str(fee_plan.id),
        organization_id=str(fee_plan.organization_id),
        name=fee_plan.name,
        amount=_money(fee_plan.amount.amount),
        currency=fee_plan.amount.currency,
        default_discount_amount=_money(fee_plan.default_discount_amount),
        description=fee_plan.description,
        status=fee_plan.status.value,
        created_at=fee_plan.created_at,
        updated_at=fee_plan.updated_at,
    )


@dataclass(frozen=True)
class StudentInvoiceDTO:
    id: str
    organization_id: str
    student_id: str
    fee_plan_id: str | None
    period: str
    amount: str
    discount_amount: str
    #: `amount - discount_amount` — the authoritative figure every balance derives from. Exposed
    #: so no client re-derives it and risks rounding differently.
    net_amount: str
    amount_paid: str
    balance_due: str
    currency: str
    due_date: date
    status: str
    route_id: str | None
    vehicle_id: str | None
    driver_id: str | None
    notes: str | None
    issued_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime


def student_invoice_to_dto(invoice: StudentInvoice) -> StudentInvoiceDTO:
    return StudentInvoiceDTO(
        id=str(invoice.id),
        organization_id=str(invoice.organization_id),
        student_id=str(invoice.student_id),
        fee_plan_id=str(invoice.fee_plan_id) if invoice.fee_plan_id else None,
        period=str(invoice.period),
        amount=_money(invoice.amount.amount),
        discount_amount=_money(invoice.discount_amount),
        net_amount=_money(invoice.net_amount),
        amount_paid=_money(invoice.amount_paid),
        balance_due=_money(invoice.balance_due),
        currency=invoice.amount.currency,
        due_date=invoice.due_date,
        status=invoice.status.value,
        route_id=str(invoice.route_id) if invoice.route_id else None,
        vehicle_id=str(invoice.vehicle_id) if invoice.vehicle_id else None,
        driver_id=str(invoice.driver_id) if invoice.driver_id else None,
        notes=invoice.notes,
        issued_at=invoice.issued_at,
        paid_at=invoice.paid_at,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
    )


@dataclass(frozen=True)
class StudentPaymentDTO:
    id: str
    organization_id: str
    invoice_id: str
    student_id: str
    amount: str
    currency: str
    method: str
    reference: str | None
    received_on: date
    notes: str | None
    is_voided: bool
    voided_reason: str | None
    created_at: datetime


def student_payment_to_dto(payment: StudentPayment) -> StudentPaymentDTO:
    return StudentPaymentDTO(
        id=str(payment.id),
        organization_id=str(payment.organization_id),
        invoice_id=str(payment.invoice_id),
        student_id=str(payment.student_id),
        amount=_money(payment.amount.amount),
        currency=payment.amount.currency,
        method=payment.method.value,
        reference=payment.reference,
        received_on=payment.received_on,
        notes=payment.notes,
        is_voided=payment.is_voided,
        voided_reason=payment.voided_reason,
        created_at=payment.created_at,
    )


@dataclass(frozen=True)
class IncomeDTO:
    id: str
    organization_id: str
    category_id: str | None
    amount: str
    currency: str
    occurred_on: date
    description: str | None
    reference: str | None
    attachment_url: str | None
    is_voided: bool
    voided_reason: str | None
    created_at: datetime
    income_type: str
    vehicle_id: str | None


def income_to_dto(income: Income) -> IncomeDTO:
    return IncomeDTO(
        id=str(income.id),
        organization_id=str(income.organization_id),
        category_id=str(income.category_id) if income.category_id else None,
        amount=_money(income.amount.amount),
        currency=income.amount.currency,
        occurred_on=income.occurred_on,
        description=income.description,
        reference=income.reference,
        attachment_url=income.attachment_url,
        is_voided=income.is_voided,
        voided_reason=income.voided_reason,
        created_at=income.created_at,
        income_type=income.income_type.value,
        vehicle_id=str(income.vehicle_id) if income.vehicle_id else None,
    )


@dataclass(frozen=True)
class ExpenseDTO:
    id: str
    organization_id: str
    category_id: str | None
    amount: str
    currency: str
    occurred_on: date
    description: str | None
    reference: str | None
    vehicle_id: str | None
    attachment_url: str | None
    is_voided: bool
    voided_reason: str | None
    created_at: datetime


def expense_to_dto(expense: Expense) -> ExpenseDTO:
    return ExpenseDTO(
        id=str(expense.id),
        organization_id=str(expense.organization_id),
        category_id=str(expense.category_id) if expense.category_id else None,
        amount=_money(expense.amount.amount),
        currency=expense.amount.currency,
        occurred_on=expense.occurred_on,
        description=expense.description,
        reference=expense.reference,
        vehicle_id=str(expense.vehicle_id) if expense.vehicle_id else None,
        attachment_url=expense.attachment_url,
        is_voided=expense.is_voided,
        voided_reason=expense.voided_reason,
        created_at=expense.created_at,
    )


@dataclass(frozen=True)
class VehicleFinanceDTO:
    """One bus's financial line for a date window (ADR-0047 §7).

    Income is three separate figures, never one unexplained total: `student_income` (payment
    allocations received in the window, attributed by each invoice line's frozen vehicle),
    `daily_income` and `other_income` (manual `Income` rows naming this bus). `billed_amount`/
    `outstanding_amount` describe what was invoiced to this bus's students in the window — a
    billing position, not cash. `vehicle_id` is `None` for the "Unassigned" row: student money
    from lines generated before the student had a bus, surfaced rather than dropped.
    """

    vehicle_id: str | None
    student_count: int
    billed_amount: str
    outstanding_amount: str
    student_income: str
    daily_income: str
    other_income: str
    total_income: str
    expense_amount: str
    net_amount: str
    currency: str


@dataclass(frozen=True)
class FinanceSummaryDTO:
    """The organization finance KPI row."""

    billed_amount: str
    collected_amount: str
    outstanding_amount: str
    invoice_count: int
    paid_invoice_count: int
    overdue_invoice_count: int
    currency: str


def finance_totals_to_dto(totals: FinanceTotals) -> FinanceSummaryDTO:
    return FinanceSummaryDTO(
        billed_amount=_money(totals.billed_amount),
        collected_amount=_money(totals.collected_amount),
        outstanding_amount=_money(totals.outstanding_amount),
        invoice_count=totals.invoice_count,
        paid_invoice_count=totals.paid_invoice_count,
        overdue_invoice_count=totals.overdue_invoice_count,
        currency=totals.currency,
    )


@dataclass(frozen=True)
class ProfitAndLossDTO:
    """Income against expenses for a window, derived from actual recorded transactions.

    Student revenue and other income are reported as **two separate lines** rather than one
    total: student fees reach the ledger through `StudentPayment`, other income through the
    `Income` table, and merging them here would make it impossible to tell transport revenue
    from a donation — besides which, a school that also recorded a student fee as `Income` would
    silently double-count. Keeping the lines apart is what makes the double-count visible.
    """

    start: date
    end: date
    #: Student income: allocations of payments *received* in the window (cash basis).
    student_revenue: str
    #: `Income` rows of type `daily_vehicle`.
    daily_vehicle_income: str
    #: `Income` rows of type `other` only (ADR-0047 §6 — no longer every manual income row).
    other_income: str
    total_income: str
    total_expenses: str
    net_profit: str
    income_by_category: dict[str, str]
    expenses_by_category: dict[str, str]
    currency: str


# ==============================================================================================
# Parent financial summary (2026-09-10 explicit user directive, "Parent & Student Domain
# Restructure + Parent Payments")
# ==============================================================================================
#
# No new financial domain, no new aggregate: `ParentFinancialSummaryDTO` is a read-side
# *aggregation* over the same `StudentInvoice`/`StudentPayment` rows every other view in this
# module already reads, grouped by "this parent's children" instead of "this organization" or
# "this vehicle" — `ParentFinanceApplicationService` (`application/services.py`) is what resolves
# that child list (via `transport_ops`'s own application services, never a cross-module DB read)
# and builds these DTOs from it.


@dataclass(frozen=True)
class ParentChildFinancialDTO:
    """One child's own contribution to the parent-level total — fee attribution stays
    per-student even when the parent sees only the family sum (see this module's own
    docstring in `application/services.py`)."""

    student_id: str
    full_name: str
    status: str
    total_due: str
    total_paid: str
    outstanding: str
    invoice_count: int


@dataclass(frozen=True)
class ParentFinancialSummaryDTO:
    """The Parent detail page's "Financial Summary" — a family-level sum of every non-cancelled
    invoice issued to any of this parent's children.

    `status` is one of `paid`/`partially_paid`/`unpaid`/`no_invoices`. The fourth value is
    deliberate, not an omission of the task's own three-value list: a family with zero invoices
    (no fee plan billed yet) genuinely owes nothing — reporting that as `unpaid` would read as a
    debt that does not exist. Every consumer must treat `no_invoices` as a neutral, not alarming,
    state.
    """

    parent_id: str
    currency: str
    total_due: str
    total_paid: str
    outstanding: str
    status: str
    children: list[ParentChildFinancialDTO]


# ==============================================================================================
# ParentBillingProfile / ParentInvoice — real aggregates (ADR-0042, 2026-09-11, supersedes
# ADR-0041 §1's StudentInvoice-grouping read model)
# ==============================================================================================
#
# `ParentInvoice`/`ParentInvoiceLine` are genuine `school_erp` aggregates now — these DTOs project
# real rows, not a read-side grouping. `invoice_number` remains a synthesized, display-only string
# (now `{period}-{id[-6:].upper()}`, using the invoice's own real id) — still never persisted as a
# second sequence, matching ADR-0041 §1's original reasoning for why one was rejected, which
# ADR-0042 does not revisit.


@dataclass(frozen=True)
class ParentBillingProfileDTO:
    id: str
    organization_id: str
    parent_id: str
    monthly_fee: str
    currency: str
    billing_start_period: str
    due_day: int
    status: str
    created_at: datetime
    updated_at: datetime


def parent_billing_profile_to_dto(profile: ParentBillingProfile) -> ParentBillingProfileDTO:
    return ParentBillingProfileDTO(
        id=str(profile.id),
        organization_id=str(profile.organization_id),
        parent_id=str(profile.parent_id),
        monthly_fee=_money(profile.monthly_fee.amount),
        currency=profile.monthly_fee.currency,
        billing_start_period=str(profile.billing_start_period),
        due_day=profile.due_day,
        status=profile.status.value,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _synthesize_invoice_number(invoice_id: str, period: str) -> str:
    """Display-only — never persisted, never a real sequence. See module docstring above."""
    return f"{period}-{invoice_id[-6:].upper()}"


@dataclass(frozen=True)
class ParentInvoiceLineDTO:
    """One billed child's own share of a `ParentInvoice`'s frozen total — the "which children
    generated the amount" breakdown (the directive's Part 8)."""

    student_id: str
    full_name: str
    amount: str
    vehicle_id: str | None
    route_id: str | None
    line_id: str
    amount_paid: str
    balance_due: str


@dataclass(frozen=True)
class ParentInvoiceSummaryDTO:
    """One row of the real Parent Invoice list."""

    id: str
    parent_id: str
    parent_name: str
    period: str
    invoice_number: str
    children_count: int
    amount: str
    amount_paid: str
    balance_due: str
    status: str
    invoice_date: str
    due_date: str
    currency: str


def parent_invoice_to_summary_dto(
    invoice: ParentInvoice, *, parent_name: str
) -> ParentInvoiceSummaryDTO:
    return ParentInvoiceSummaryDTO(
        id=str(invoice.id),
        parent_id=str(invoice.parent_id),
        parent_name=parent_name,
        period=str(invoice.period),
        invoice_number=_synthesize_invoice_number(str(invoice.id), str(invoice.period)),
        children_count=len(invoice.lines),
        amount=_money(invoice.amount.amount),
        amount_paid=_money(invoice.amount_paid),
        balance_due=_money(invoice.balance_due),
        status=invoice.status.value,
        invoice_date=invoice.invoice_date.isoformat(),
        due_date=invoice.due_date.isoformat(),
        currency=invoice.amount.currency,
    )


@dataclass(frozen=True)
class ParentInvoiceDetailDTO:
    """The Parent Invoice detail view — the summary fields plus its own child line items."""

    id: str
    parent_id: str
    parent_name: str
    period: str
    invoice_number: str
    amount: str
    amount_paid: str
    balance_due: str
    status: str
    currency: str
    invoice_date: str
    due_date: str
    notes: str | None
    lines: list[ParentInvoiceLineDTO]


def parent_invoice_to_detail_dto(
    invoice: ParentInvoice, *, parent_name: str, student_names: dict[str, str]
) -> ParentInvoiceDetailDTO:
    return ParentInvoiceDetailDTO(
        id=str(invoice.id),
        parent_id=str(invoice.parent_id),
        parent_name=parent_name,
        period=str(invoice.period),
        invoice_number=_synthesize_invoice_number(str(invoice.id), str(invoice.period)),
        amount=_money(invoice.amount.amount),
        amount_paid=_money(invoice.amount_paid),
        balance_due=_money(invoice.balance_due),
        status=invoice.status.value,
        currency=invoice.amount.currency,
        invoice_date=invoice.invoice_date.isoformat(),
        due_date=invoice.due_date.isoformat(),
        notes=invoice.notes,
        lines=[
            ParentInvoiceLineDTO(
                student_id=str(line.student_id),
                full_name=student_names.get(str(line.student_id), str(line.student_id)),
                amount=_money(line.amount.amount),
                vehicle_id=str(line.vehicle_id) if line.vehicle_id else None,
                route_id=str(line.route_id) if line.route_id else None,
                line_id=str(line.id),
                amount_paid=_money(line.amount_paid),
                balance_due=_money(line.balance_due),
            )
            for line in invoice.lines
        ],
    )


# ==============================================================================================
# ParentPayment / student finance / vehicle finance report (ADR-0047)
# ==============================================================================================


@dataclass(frozen=True)
class ParentPaymentAllocationDTO:
    student_id: str
    full_name: str
    amount: str
    vehicle_id: str | None


@dataclass(frozen=True)
class ParentPaymentDTO:
    id: str
    parent_id: str
    invoice_id: str
    invoice_number: str
    period: str
    amount: str
    currency: str
    method: str
    reference: str | None
    received_on: date
    notes: str | None
    is_voided: bool
    voided_reason: str | None
    created_at: datetime
    allocations: list[ParentPaymentAllocationDTO]


def parent_payment_to_dto(
    payment: ParentPayment, *, period: str, student_names: dict[str, str]
) -> ParentPaymentDTO:
    return ParentPaymentDTO(
        id=str(payment.id),
        parent_id=str(payment.parent_id),
        invoice_id=str(payment.invoice_id),
        invoice_number=_synthesize_invoice_number(str(payment.invoice_id), period),
        period=period,
        amount=_money(payment.amount.amount),
        currency=payment.amount.currency,
        method=payment.method.value,
        reference=payment.reference,
        received_on=payment.received_on,
        notes=payment.notes,
        is_voided=payment.is_voided,
        voided_reason=payment.voided_reason,
        created_at=payment.created_at,
        allocations=[
            ParentPaymentAllocationDTO(
                student_id=str(a.student_id),
                full_name=student_names.get(str(a.student_id), str(a.student_id)),
                amount=_money(a.amount.amount),
                vehicle_id=str(a.vehicle_id) if a.vehicle_id else None,
            )
            for a in payment.allocations
        ],
    )


@dataclass(frozen=True)
class StudentChargeDTO:
    """One period's charge to one student — the student's own line on a Parent Invoice."""

    invoice_id: str
    invoice_number: str
    line_id: str
    period: str
    parent_id: str
    parent_name: str
    amount: str
    amount_paid: str
    balance_due: str
    invoice_status: str
    due_date: str
    vehicle_id: str | None
    currency: str


@dataclass(frozen=True)
class StudentPaymentEntryDTO:
    """The part of one family payment that paid for this student."""

    payment_id: str
    invoice_id: str
    invoice_number: str
    period: str
    received_on: date
    method: str
    reference: str | None
    amount: str
    payment_total: str
    currency: str
    is_voided: bool
    voided_reason: str | None


@dataclass(frozen=True)
class StudentParentDTO:
    parent_id: str
    full_name: str
    is_primary: bool


@dataclass(frozen=True)
class StudentFinanceDTO:
    """A student's own financial history (ADR-0047 §2): charges, payments allocated to them, and
    the resulting balance. `legacy_invoices`/`legacy_payments` are the pre-ADR-0042 per-student
    records, shown read-only; their money is already represented in the Parent Invoices the
    ADR-0042 migration copied from them, so they never add to the totals here."""

    student_id: str
    full_name: str
    status: str
    parents: list[StudentParentDTO]
    currency: str
    total_charged: str
    total_paid: str
    balance_due: str
    charges: list[StudentChargeDTO]
    payments: list[StudentPaymentEntryDTO]
    legacy_invoices: list[StudentInvoiceDTO]
    legacy_payments: list[StudentPaymentDTO]


@dataclass(frozen=True)
class VehicleStudentIncomeDTO:
    student_id: str
    full_name: str
    parent_id: str
    parent_name: str
    amount: str


@dataclass(frozen=True)
class VehicleParentIncomeDTO:
    parent_id: str
    full_name: str
    amount: str


@dataclass(frozen=True)
class VehicleFinanceReportDTO:
    """The per-vehicle financial report (ADR-0047 §7) for one bus and a date window. Every
    figure is a sum of real rows listed alongside it — no estimate, no projection."""

    vehicle_id: str
    start: date
    end: date
    currency: str
    student_income: str
    daily_income: str
    other_income: str
    total_income: str
    total_expenses: str
    net_amount: str
    billed_amount: str
    outstanding_amount: str
    income_by_student: list[VehicleStudentIncomeDTO]
    income_by_parent: list[VehicleParentIncomeDTO]
    daily_entries: list[IncomeDTO]
    other_entries: list[IncomeDTO]
    expenses_by_category: dict[str, str]
    expense_entries: list[ExpenseDTO]


@dataclass(frozen=True)
class MyInvoicesDTO:
    """`GET /me/invoices` — the calling parent's own invoices and payments, and nothing else."""

    parent_id: str
    currency: str
    total_due: str
    total_paid: str
    balance_due: str
    invoices: list[ParentInvoiceDetailDTO]
    payments: list[ParentPaymentDTO]
