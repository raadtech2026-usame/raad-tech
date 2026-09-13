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
    StudentInvoice,
    StudentPayment,
)
from raad.modules.school_erp.domain.repositories import (
    FinanceTotals,
    VehicleFinancialSummary,
)


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
    created_at: datetime


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
        created_at=income.created_at,
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
        created_at=expense.created_at,
    )


@dataclass(frozen=True)
class VehicleFinanceDTO:
    """One bus's financial line. `vehicle_id` is `None` for invoices issued before the student
    was assigned to a bus — surfaced as its own row rather than dropped, so the rows still add up
    to the organization total shown beside them."""

    vehicle_id: str | None
    student_count: int
    invoice_count: int
    billed_amount: str
    collected_amount: str
    outstanding_amount: str
    paid_student_count: int
    unpaid_student_count: int
    expense_amount: str
    net_amount: str
    currency: str


def vehicle_finance_to_dto(
    summary: VehicleFinancialSummary, *, expense_amount: Decimal
) -> VehicleFinanceDTO:
    return VehicleFinanceDTO(
        vehicle_id=summary.vehicle_id,
        student_count=summary.student_count,
        invoice_count=summary.invoice_count,
        billed_amount=_money(summary.billed_amount),
        collected_amount=_money(summary.collected_amount),
        outstanding_amount=_money(summary.outstanding_amount),
        paid_student_count=summary.paid_student_count,
        unpaid_student_count=summary.unpaid_student_count,
        expense_amount=_money(expense_amount),
        # Cash actually in, minus cost actually attributed to this bus. Deliberately built from
        # `collected`, not `billed`: an unpaid invoice is not profit.
        net_amount=_money(summary.collected_amount - expense_amount),
        currency=summary.currency,
    )


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
    student_revenue: str
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
            )
            for line in invoice.lines
        ],
    )
