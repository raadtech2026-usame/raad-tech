"""ORM <-> Domain mappers for `school_erp` (Backend LLD §7.1 "aggregate-in/aggregate-out").

Mappers own **every** conversion between SQLAlchemy rows and domain objects — repositories never
construct or read ORM columns directly outside calling these functions. Mirrors
`billing.infra.mappers`'s `existing=` in-place-update pattern exactly, including reusing its
`_to_naive_utc` fix (`SystemClock` returns tz-aware datetimes; every `DateTime(timezone=False)`
column needs naive ones).

**`_to_naive_utc` is applied to every datetime field on every mapper here, not only the one that
would first crash.** That is a permanent lesson this codebase already paid for once
(`model_to_user` missed three of four fields even after the fourth was fixed and understood).

**Amounts round-trip as `Decimal`.** `DECIMAL(12,2)` comes back from asyncpg as a `Decimal`
already, so `_money_in` only normalises the rare `None`/int case; nothing here ever casts through
`float`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from raad.modules.school_erp.domain.entities import (
    Expense,
    FeePlan,
    FinancialCategory,
    Income,
    ParentBillingProfile,
    ParentInvoice,
    ParentInvoiceLine,
    StudentInvoice,
    StudentPayment,
)
from raad.modules.school_erp.domain.value_objects import (
    BillingPeriod,
    CategoryKind,
    CategoryStatus,
    DriverId,
    ExpenseId,
    FeePlanId,
    FeePlanStatus,
    FinancialCategoryId,
    IncomeId,
    Money,
    OrganizationId,
    ParentBillingProfileId,
    ParentBillingProfileStatus,
    ParentId,
    ParentInvoiceId,
    ParentInvoiceLineId,
    ParentInvoiceStatus,
    RouteId,
    StudentId,
    StudentInvoiceId,
    StudentInvoiceStatus,
    StudentPaymentId,
    StudentPaymentMethod,
    VehicleId,
)
from raad.modules.school_erp.infra.models import (
    ExpenseModel,
    FeePlanModel,
    FinancialCategoryModel,
    IncomeModel,
    ParentBillingProfileModel,
    ParentInvoiceLineModel,
    ParentInvoiceModel,
    StudentInvoiceModel,
    StudentPaymentModel,
)

_ZERO = Decimal("0.00")


def _char(value: str | None) -> str | None:
    """Strips PostgreSQL's `CHAR(n)` blank padding.

    A permanent rule in this codebase (CLAUDE.md, Permanent Engineering Lessons): PostgreSQL
    blank-pads `CHAR(n)` on `SELECT`, unlike `VARCHAR`, and the domain layer must never see the
    padding artifact. `billing.model_to_payment` already strips `payments.idempotency_key` for
    the same reason.

    It matters more here than it looks. Every cross-module id on these tables is `CHAR(26)`, and
    a padded `vehicle_id` silently breaks three things at once: the `GROUP BY vehicle_id` behind
    the Vehicle Financial Overview splits one bus into two rows, the invoice-to-expense join in
    `get_vehicle_financial_overview` stops matching, and any comparison against an unpadded id
    handed over by `fleet_device` fails. Caught by
    `tests/integration/test_school_erp_repository.py`, which is exactly the class of defect a
    fake-backed unit test cannot see.
    """
    return value.rstrip() if value is not None else None



def _to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _dec(value: object) -> Decimal:
    """Normalises whatever the driver hands back into an exact two-place `Decimal`. Never routes
    through `float` — that is the whole reason this module uses `Decimal` at all."""
    if value is None:
        return _ZERO
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))


# --------------------------------------------------------------------------------------------
# FinancialCategory
# --------------------------------------------------------------------------------------------


def financial_category_to_model(
    category: FinancialCategory, *, existing: FinancialCategoryModel | None = None
) -> FinancialCategoryModel:
    model = (
        existing if existing is not None else FinancialCategoryModel(id=str(category.id))
    )
    model.organization_id = str(category.organization_id)
    model.name = category.name
    model.kind = category.kind.value
    model.parent_category_id = (
        str(category.parent_category_id) if category.parent_category_id else None
    )
    model.description = category.description
    model.status = category.status.value
    model.created_at = _to_naive_utc(category.created_at)
    model.updated_at = _to_naive_utc(category.updated_at)
    return model


def model_to_financial_category(model: FinancialCategoryModel) -> FinancialCategory:
    return FinancialCategory(
        id=FinancialCategoryId(_char(model.id)),
        organization_id=OrganizationId(_char(model.organization_id)),
        name=model.name,
        kind=CategoryKind(model.kind),
        parent_category_id=(
            FinancialCategoryId(_char(model.parent_category_id)) if model.parent_category_id else None
        ),
        description=model.description,
        status=CategoryStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# --------------------------------------------------------------------------------------------
# FeePlan
# --------------------------------------------------------------------------------------------


def fee_plan_to_model(
    fee_plan: FeePlan, *, existing: FeePlanModel | None = None
) -> FeePlanModel:
    model = existing if existing is not None else FeePlanModel(id=str(fee_plan.id))
    model.organization_id = str(fee_plan.organization_id)
    model.name = fee_plan.name
    model.amount = fee_plan.amount.amount
    model.currency = fee_plan.amount.currency
    model.default_discount_amount = fee_plan.default_discount_amount
    model.description = fee_plan.description
    model.status = fee_plan.status.value
    model.created_at = _to_naive_utc(fee_plan.created_at)
    model.updated_at = _to_naive_utc(fee_plan.updated_at)
    return model


def model_to_fee_plan(model: FeePlanModel) -> FeePlan:
    return FeePlan(
        id=FeePlanId(_char(model.id)),
        organization_id=OrganizationId(_char(model.organization_id)),
        name=model.name,
        amount=Money(amount=_dec(model.amount), currency=_char(model.currency)),
        default_discount_amount=_dec(model.default_discount_amount),
        description=model.description,
        status=FeePlanStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# --------------------------------------------------------------------------------------------
# StudentInvoice
# --------------------------------------------------------------------------------------------


def student_invoice_to_model(
    invoice: StudentInvoice, *, existing: StudentInvoiceModel | None = None
) -> StudentInvoiceModel:
    model = existing if existing is not None else StudentInvoiceModel(id=str(invoice.id))
    model.organization_id = str(invoice.organization_id)
    model.student_id = str(invoice.student_id)
    model.fee_plan_id = str(invoice.fee_plan_id) if invoice.fee_plan_id else None
    model.period = str(invoice.period)
    model.amount = invoice.amount.amount
    model.currency = invoice.amount.currency
    model.discount_amount = invoice.discount_amount
    model.amount_paid = invoice.amount_paid
    model.due_date = invoice.due_date
    model.status = invoice.status.value
    model.route_id = str(invoice.route_id) if invoice.route_id else None
    model.vehicle_id = str(invoice.vehicle_id) if invoice.vehicle_id else None
    model.driver_id = str(invoice.driver_id) if invoice.driver_id else None
    model.notes = invoice.notes
    model.issued_at = _to_naive_utc(invoice.issued_at)
    model.paid_at = _to_naive_utc(invoice.paid_at)
    model.created_at = _to_naive_utc(invoice.created_at)
    model.updated_at = _to_naive_utc(invoice.updated_at)
    return model


def model_to_student_invoice(model: StudentInvoiceModel) -> StudentInvoice:
    return StudentInvoice(
        id=StudentInvoiceId(_char(model.id)),
        organization_id=OrganizationId(_char(model.organization_id)),
        student_id=StudentId(_char(model.student_id)),
        fee_plan_id=FeePlanId(_char(model.fee_plan_id)) if model.fee_plan_id else None,
        period=BillingPeriod(_char(model.period)),
        amount=Money(amount=_dec(model.amount), currency=_char(model.currency)),
        discount_amount=_dec(model.discount_amount),
        amount_paid=_dec(model.amount_paid),
        due_date=model.due_date,
        status=StudentInvoiceStatus(model.status),
        route_id=RouteId(_char(model.route_id)) if model.route_id else None,
        vehicle_id=VehicleId(_char(model.vehicle_id)) if model.vehicle_id else None,
        driver_id=DriverId(_char(model.driver_id)) if model.driver_id else None,
        notes=model.notes,
        issued_at=model.issued_at,
        paid_at=model.paid_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# --------------------------------------------------------------------------------------------
# StudentPayment
# --------------------------------------------------------------------------------------------


def student_payment_to_model(
    payment: StudentPayment, *, existing: StudentPaymentModel | None = None
) -> StudentPaymentModel:
    model = existing if existing is not None else StudentPaymentModel(id=str(payment.id))
    model.organization_id = str(payment.organization_id)
    model.invoice_id = str(payment.invoice_id)
    model.student_id = str(payment.student_id)
    model.amount = payment.amount.amount
    model.currency = payment.amount.currency
    model.method = payment.method.value
    model.reference = payment.reference
    model.received_on = payment.received_on
    model.notes = payment.notes
    model.is_voided = payment.is_voided
    model.voided_reason = payment.voided_reason
    model.created_at = _to_naive_utc(payment.created_at)
    model.updated_at = _to_naive_utc(payment.updated_at)
    return model


def model_to_student_payment(model: StudentPaymentModel) -> StudentPayment:
    return StudentPayment(
        id=StudentPaymentId(_char(model.id)),
        organization_id=OrganizationId(_char(model.organization_id)),
        invoice_id=StudentInvoiceId(_char(model.invoice_id)),
        student_id=StudentId(_char(model.student_id)),
        amount=Money(amount=_dec(model.amount), currency=_char(model.currency)),
        method=StudentPaymentMethod(model.method),
        reference=model.reference,
        received_on=model.received_on,
        notes=model.notes,
        is_voided=model.is_voided,
        voided_reason=model.voided_reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# --------------------------------------------------------------------------------------------
# Income / Expense
# --------------------------------------------------------------------------------------------


def income_to_model(income: Income, *, existing: IncomeModel | None = None) -> IncomeModel:
    model = existing if existing is not None else IncomeModel(id=str(income.id))
    model.organization_id = str(income.organization_id)
    model.category_id = str(income.category_id) if income.category_id else None
    model.amount = income.amount.amount
    model.currency = income.amount.currency
    model.occurred_on = income.occurred_on
    model.description = income.description
    model.reference = income.reference
    model.attachment_url = income.attachment_url
    model.is_voided = income.is_voided
    model.created_at = _to_naive_utc(income.created_at)
    model.updated_at = _to_naive_utc(income.updated_at)
    return model


def model_to_income(model: IncomeModel) -> Income:
    return Income(
        id=IncomeId(_char(model.id)),
        organization_id=OrganizationId(_char(model.organization_id)),
        category_id=FinancialCategoryId(_char(model.category_id)) if model.category_id else None,
        amount=Money(amount=_dec(model.amount), currency=_char(model.currency)),
        occurred_on=model.occurred_on,
        description=model.description,
        reference=model.reference,
        attachment_url=model.attachment_url,
        is_voided=model.is_voided,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def expense_to_model(expense: Expense, *, existing: ExpenseModel | None = None) -> ExpenseModel:
    model = existing if existing is not None else ExpenseModel(id=str(expense.id))
    model.organization_id = str(expense.organization_id)
    model.category_id = str(expense.category_id) if expense.category_id else None
    model.amount = expense.amount.amount
    model.currency = expense.amount.currency
    model.occurred_on = expense.occurred_on
    model.description = expense.description
    model.reference = expense.reference
    model.vehicle_id = str(expense.vehicle_id) if expense.vehicle_id else None
    model.attachment_url = expense.attachment_url
    model.is_voided = expense.is_voided
    model.created_at = _to_naive_utc(expense.created_at)
    model.updated_at = _to_naive_utc(expense.updated_at)
    return model


def model_to_expense(model: ExpenseModel) -> Expense:
    return Expense(
        id=ExpenseId(_char(model.id)),
        organization_id=OrganizationId(_char(model.organization_id)),
        category_id=FinancialCategoryId(_char(model.category_id)) if model.category_id else None,
        amount=Money(amount=_dec(model.amount), currency=_char(model.currency)),
        occurred_on=model.occurred_on,
        description=model.description,
        reference=model.reference,
        vehicle_id=VehicleId(_char(model.vehicle_id)) if model.vehicle_id else None,
        attachment_url=model.attachment_url,
        is_voided=model.is_voided,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# --------------------------------------------------------------------------------------------
# ParentBillingProfile / ParentInvoice (ADR-0042)
# --------------------------------------------------------------------------------------------


def parent_billing_profile_to_model(
    profile: ParentBillingProfile, *, existing: ParentBillingProfileModel | None = None
) -> ParentBillingProfileModel:
    model = (
        existing if existing is not None else ParentBillingProfileModel(id=str(profile.id))
    )
    model.organization_id = str(profile.organization_id)
    model.parent_id = str(profile.parent_id)
    model.monthly_fee = profile.monthly_fee.amount
    model.currency = profile.monthly_fee.currency
    model.billing_start_period = str(profile.billing_start_period)
    model.due_day = profile.due_day
    model.status = profile.status.value
    model.created_at = _to_naive_utc(profile.created_at)
    model.updated_at = _to_naive_utc(profile.updated_at)
    return model


def model_to_parent_billing_profile(model: ParentBillingProfileModel) -> ParentBillingProfile:
    return ParentBillingProfile(
        id=ParentBillingProfileId(_char(model.id)),
        organization_id=OrganizationId(_char(model.organization_id)),
        parent_id=ParentId(_char(model.parent_id)),
        monthly_fee=Money(amount=_dec(model.monthly_fee), currency=_char(model.currency)),
        billing_start_period=BillingPeriod(_char(model.billing_start_period)),
        due_day=model.due_day,
        status=ParentBillingProfileStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _parent_invoice_line_to_model(
    line: ParentInvoiceLine,
    *,
    parent_invoice_id: str,
    organization_id: str,
    currency: str,
    existing: ParentInvoiceLineModel | None = None,
) -> ParentInvoiceLineModel:
    model = existing if existing is not None else ParentInvoiceLineModel(id=str(line.id))
    model.organization_id = organization_id
    model.parent_invoice_id = parent_invoice_id
    model.student_id = str(line.student_id)
    model.vehicle_id = str(line.vehicle_id) if line.vehicle_id else None
    model.route_id = str(line.route_id) if line.route_id else None
    model.amount = line.amount.amount
    return model


def _model_to_parent_invoice_line(model: ParentInvoiceLineModel, *, currency: str) -> ParentInvoiceLine:
    return ParentInvoiceLine(
        id=ParentInvoiceLineId(_char(model.id)),
        student_id=StudentId(_char(model.student_id)),
        amount=Money(amount=_dec(model.amount), currency=currency),
        vehicle_id=VehicleId(_char(model.vehicle_id)) if model.vehicle_id else None,
        route_id=RouteId(_char(model.route_id)) if model.route_id else None,
    )


def parent_invoice_to_model(
    invoice: ParentInvoice, *, existing: ParentInvoiceModel | None = None
) -> ParentInvoiceModel:
    """Projects a `ParentInvoice` aggregate (including its lines) onto its ORM row — mirrors
    `route_to_model`'s exact add/update/remove child-collection sync rules (this module's own
    first parent/child aggregate before ADR-0042)."""
    model = existing if existing is not None else ParentInvoiceModel(id=str(invoice.id))
    model.organization_id = str(invoice.organization_id)
    model.parent_id = str(invoice.parent_id)
    model.period = str(invoice.period)
    model.amount = invoice.amount.amount
    model.currency = invoice.amount.currency
    model.amount_paid = invoice.amount_paid
    model.status = invoice.status.value
    model.invoice_date = invoice.invoice_date
    model.due_date = invoice.due_date
    model.notes = invoice.notes
    model.created_at = _to_naive_utc(invoice.created_at)
    model.updated_at = _to_naive_utc(invoice.updated_at)

    existing_rows = {row.id: row for row in model.lines}
    current_ids = {str(line.id) for line in invoice.lines}
    for row_id, row in list(existing_rows.items()):
        if row_id not in current_ids:
            model.lines.remove(row)  # cascade="all, delete-orphan" deletes the orphaned row

    for line in invoice.lines:
        row = existing_rows.get(str(line.id))
        if row is not None:
            _parent_invoice_line_to_model(
                line,
                parent_invoice_id=str(invoice.id),
                organization_id=str(invoice.organization_id),
                currency=invoice.amount.currency,
                existing=row,
            )
        else:
            model.lines.append(
                _parent_invoice_line_to_model(
                    line,
                    parent_invoice_id=str(invoice.id),
                    organization_id=str(invoice.organization_id),
                    currency=invoice.amount.currency,
                )
            )
    return model


def model_to_parent_invoice(model: ParentInvoiceModel) -> ParentInvoice:
    currency = _char(model.currency)
    return ParentInvoice(
        id=ParentInvoiceId(_char(model.id)),
        organization_id=OrganizationId(_char(model.organization_id)),
        parent_id=ParentId(_char(model.parent_id)),
        period=BillingPeriod(_char(model.period)),
        amount=Money(amount=_dec(model.amount), currency=currency),
        amount_paid=_dec(model.amount_paid),
        status=ParentInvoiceStatus(model.status),
        invoice_date=model.invoice_date,
        due_date=model.due_date,
        notes=model.notes,
        created_at=model.created_at,
        updated_at=model.updated_at,
        lines=[_model_to_parent_invoice_line(row, currency=currency) for row in model.lines],
    )
