"""Pydantic request/response schemas for `school_erp` (Backend LLD §16.2). The wire contract —
Pydantic is confined to this layer; the application layer speaks DTOs and the domain speaks
value objects.

**Monetary fields are `str` on the wire, both directions.** JSON has one numeric type and it is
a float; `{"amount": 12.10}` is already `12.099999999999999` by the time any Python code sees it,
and quantising that back is a guess. Accepting and returning a decimal *string* keeps the value
exact end to end, and `MoneyStr` below validates it as a real two-place decimal rather than
trusting the caller. This is the same discipline the domain layer's `Decimal`-only `Money`
enforces further in — the wire is simply where it has to start.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, ClassVar

from pydantic import BaseModel, Field, field_validator


def _validate_money(value: object) -> str:
    """Accepts a string or a number, returns an exact two-place decimal string.

    A number is accepted (clients do send `12.5`) but is stringified through `Decimal(str(v))`,
    which reads the shortest repr rather than the full binary expansion — so `12.1` becomes
    "12.10", not "12.099999999999999".

    **`ROUND_HALF_UP`, matching `school_erp.Money`.** This layer quantises *before* the domain
    sees the value, so leaving it on `quantize`'s default would silently overrule the domain's
    own explicit choice: Python defaults to ROUND_HALF_EVEN, which turns 10.005 into 10.00, and
    `Money` would then have nothing left to round. Two layers rounding the same amount must round
    it the same way, or the documented rule holds only where a value happens to bypass this one.
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ArithmeticError, ValueError) as exc:
        raise ValueError(f"must be a decimal amount, got {value!r}") from exc
    if amount < 0:
        raise ValueError("must not be negative")
    return f"{amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


MoneyStr = Annotated[str, Field(examples=["150.00"])]
CurrencyStr = Annotated[str, Field(min_length=3, max_length=3, examples=["USD"])]
PeriodStr = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", examples=["2026-09"])]


class _MoneyValidatingModel(BaseModel):
    """Base for every request carrying an amount. Subclasses list their monetary fields in
    `MONEY_FIELDS`; the validator below is declared once here instead of being repeated (and
    eventually forgotten) on each schema.

    **`MONEY_FIELDS` is a `ClassVar` with a non-underscore name, and both halves matter.**
    Pydantic v2 turns any underscore-prefixed class attribute into a `ModelPrivateAttr`
    descriptor, so reading it off `cls` inside a validator returns the descriptor rather than the
    tuple — `info.field_name in cls._money_fields` then raised
    `TypeError: argument of type 'ModelPrivateAttr' is not iterable` on **every** request
    carrying an amount. That was live: creating a fee plan, issuing an invoice, recording a
    payment, an income or an expense all returned `500`, i.e. the whole school-finance write
    surface, while the test suite stayed green because the unit tests call the application
    service directly and never build these models. `ClassVar` is what keeps Pydantic's hands off
    it; the plain name is what keeps it obvious.
    """

    MONEY_FIELDS: ClassVar[tuple[str, ...]] = ()

    @field_validator("*", mode="before")
    @classmethod
    def _coerce_money(cls, value: object, info) -> object:
        if info.field_name in cls.MONEY_FIELDS and value is not None:
            return _validate_money(value)
        return value


# ---- FinancialCategory ---------------------------------------------------------------------


class CreateFinancialCategoryRequest(BaseModel):
    organization_id: str | None = Field(
        default=None,
        description=(
            "Omit as an Org Admin — the server uses your own organization. Platform staff must "
            "supply it explicitly."
        ),
    )
    name: str = Field(min_length=1, max_length=160)
    kind: str = Field(pattern="^(income|expense)$")
    parent_category_id: str | None = None
    description: str | None = Field(default=None, max_length=500)


class UpdateFinancialCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=500)


class FinancialCategoryResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    kind: str
    parent_category_id: str | None
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


# ---- FeePlan -------------------------------------------------------------------------------


class CreateFeePlanRequest(_MoneyValidatingModel):
    MONEY_FIELDS: ClassVar[tuple[str, ...]] = ("amount", "default_discount_amount")

    organization_id: str | None = None
    name: str = Field(min_length=1, max_length=160)
    amount: MoneyStr
    currency: CurrencyStr
    default_discount_amount: MoneyStr = "0.00"
    description: str | None = Field(default=None, max_length=500)


class UpdateFeePlanRequest(_MoneyValidatingModel):
    MONEY_FIELDS: ClassVar[tuple[str, ...]] = ("amount", "default_discount_amount")

    name: str = Field(min_length=1, max_length=160)
    amount: MoneyStr
    currency: CurrencyStr
    default_discount_amount: MoneyStr = "0.00"
    description: str | None = Field(default=None, max_length=500)


class FeePlanResponse(BaseModel):
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


# ---- StudentInvoice ------------------------------------------------------------------------


class IssueStudentInvoiceRequest(_MoneyValidatingModel):
    MONEY_FIELDS: ClassVar[tuple[str, ...]] = ("amount", "discount_amount")

    organization_id: str | None = None
    student_id: str
    period: PeriodStr
    due_date: date
    fee_plan_id: str | None = Field(
        default=None,
        description=(
            "When supplied, its amount and default discount fill in whatever is omitted below."
        ),
    )
    amount: MoneyStr | None = None
    currency: CurrencyStr | None = None
    discount_amount: MoneyStr | None = None
    notes: str | None = Field(default=None, max_length=500)


class GenerateStudentInvoicesRequest(BaseModel):
    """The monthly billing run. Idempotent: students already invoiced for the period are
    skipped, so re-running a partially-failed batch never double-charges."""

    organization_id: str | None = None
    period: PeriodStr
    due_date: date
    fee_plan_id: str
    student_ids: list[str] = Field(min_length=1, max_length=500)


class CancelStudentInvoiceRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class StudentInvoiceResponse(BaseModel):
    id: str
    organization_id: str
    student_id: str
    fee_plan_id: str | None
    period: str
    amount: str
    discount_amount: str
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


# ---- StudentPayment ------------------------------------------------------------------------


class RecordStudentPaymentRequest(_MoneyValidatingModel):
    MONEY_FIELDS: ClassVar[tuple[str, ...]] = ("amount",)

    amount: MoneyStr
    currency: CurrencyStr
    method: str = Field(pattern="^(cash|bank_transfer|mobile_money|cheque|card|other)$")
    received_on: date
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=500)


class VoidStudentPaymentRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class StudentPaymentResponse(BaseModel):
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


# ---- Income / Expense ----------------------------------------------------------------------


class RecordIncomeRequest(_MoneyValidatingModel):
    MONEY_FIELDS: ClassVar[tuple[str, ...]] = ("amount",)

    organization_id: str | None = None
    category_id: str | None = None
    amount: MoneyStr
    currency: CurrencyStr
    occurred_on: date
    description: str | None = Field(default=None, max_length=500)
    reference: str | None = Field(default=None, max_length=120)


class RecordExpenseRequest(_MoneyValidatingModel):
    MONEY_FIELDS: ClassVar[tuple[str, ...]] = ("amount",)

    organization_id: str | None = None
    category_id: str | None = None
    amount: MoneyStr
    currency: CurrencyStr
    occurred_on: date
    description: str | None = Field(default=None, max_length=500)
    reference: str | None = Field(default=None, max_length=120)
    vehicle_id: str | None = Field(
        default=None, description="Attributes this cost to one bus, for per-vehicle reporting."
    )


class VoidLedgerEntryRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class IncomeResponse(BaseModel):
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


class ExpenseResponse(BaseModel):
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


# ---- Read models ---------------------------------------------------------------------------


class FinanceSummaryResponse(BaseModel):
    billed_amount: str
    collected_amount: str
    outstanding_amount: str
    invoice_count: int
    paid_invoice_count: int
    overdue_invoice_count: int
    currency: str


class VehicleFinanceResponse(BaseModel):
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


class ProfitAndLossResponse(BaseModel):
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
