"""Domain events for the `school_erp` module (ADR-0038, ADR-0040; naming per
`.claude/rules/naming.md`: PascalCase, past-tense). Each factory returns the shared `DomainEvent`
envelope (`core.events.base`), populated with `school_erp`-specific
`event_type`/`aggregate_type`/`payload`, mirroring every other module's identical `_new_event`
pattern.

Factories take primitive values only, never the aggregate objects themselves — serializable for
`outbox.payload_json` (Database Design §8.8), and it avoids a circular import with `entities.py`.

**Every event here also becomes an `audit_entries` row automatically**, via the shared
`UnitOfWork.commit()` -> `AuditWriter` pipeline (ADR-0007). That is the whole reason a financial
module gets its audit trail for free: no `school_erp` code writes an audit row, and none should.

**Naming provenance.** No approved document names any of these — ADR-0038 defines the aggregates
but not their events. Each is named 1:1 after the domain method that raises it, the same posture
`RouteCreated`/`TripScheduled`/`PlanCreated` already establish for their own unnamed lifecycle
events. `event_type` strings are namespaced `school_erp.*` so they can never collide with
`billing`'s own `Invoice`/`Payment` events — the two invoice aggregates coexist deliberately
(ADR-0038 §2), and their event streams must stay distinguishable.

**Amounts are serialised as strings, not floats.** `Decimal` is not JSON-serialisable, and
casting to `float` on the way into the outbox would reintroduce exactly the binary-floating-point
error `value_objects.Money` exists to avoid. A consumer that needs arithmetic parses the string
back into a `Decimal`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from raad.core.events.base import DomainEvent
from raad.core.ids.generator import generate_ulid


def _new_event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    org_id: str | None,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> DomainEvent:
    return DomainEvent(
        event_id=generate_ulid(),
        event_type=event_type,
        version=1,
        occurred_at=occurred_at,
        org_id=org_id,
        correlation_id=None,
        payload=payload,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
    )


def _money(amount: Decimal) -> str:
    """See module docstring: `Decimal` crosses the outbox as an exact decimal string."""
    return str(amount)


# --------------------------------------------------------------------------------------------
# FinancialCategory
# --------------------------------------------------------------------------------------------


def financial_category_created(
    *,
    category_id: str,
    organization_id: str,
    name: str,
    kind: str,
    parent_category_id: str | None,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.FinancialCategoryCreated",
        aggregate_type="FinancialCategory",
        aggregate_id=category_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "category_id": category_id,
            "organization_id": organization_id,
            "name": name,
            "kind": kind,
            "parent_category_id": parent_category_id,
            "actor_id": actor_id,
        },
    )


def financial_category_renamed(
    *,
    category_id: str,
    organization_id: str,
    name: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.FinancialCategoryRenamed",
        aggregate_type="FinancialCategory",
        aggregate_id=category_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"category_id": category_id, "name": name, "actor_id": actor_id},
    )


def financial_category_archived(
    *,
    category_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.FinancialCategoryArchived",
        aggregate_type="FinancialCategory",
        aggregate_id=category_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"category_id": category_id, "actor_id": actor_id},
    )


# --------------------------------------------------------------------------------------------
# FeePlan
# --------------------------------------------------------------------------------------------


def fee_plan_created(
    *,
    fee_plan_id: str,
    organization_id: str,
    name: str,
    amount: Decimal,
    currency: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.FeePlanCreated",
        aggregate_type="FeePlan",
        aggregate_id=fee_plan_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "fee_plan_id": fee_plan_id,
            "organization_id": organization_id,
            "name": name,
            "amount": _money(amount),
            "currency": currency,
            "actor_id": actor_id,
        },
    )


def fee_plan_updated(
    *,
    fee_plan_id: str,
    organization_id: str,
    name: str,
    amount: Decimal,
    currency: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.FeePlanUpdated",
        aggregate_type="FeePlan",
        aggregate_id=fee_plan_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "fee_plan_id": fee_plan_id,
            "name": name,
            "amount": _money(amount),
            "currency": currency,
            "actor_id": actor_id,
        },
    )


def fee_plan_archived(
    *,
    fee_plan_id: str,
    organization_id: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.FeePlanArchived",
        aggregate_type="FeePlan",
        aggregate_id=fee_plan_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"fee_plan_id": fee_plan_id, "actor_id": actor_id},
    )


# --------------------------------------------------------------------------------------------
# StudentInvoice
# --------------------------------------------------------------------------------------------


def student_invoice_issued(
    *,
    invoice_id: str,
    organization_id: str,
    student_id: str,
    period: str,
    amount: Decimal,
    discount_amount: Decimal,
    currency: str,
    vehicle_id: str | None,
    route_id: str | None,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.StudentInvoiceIssued",
        aggregate_type="StudentInvoice",
        aggregate_id=invoice_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "invoice_id": invoice_id,
            "organization_id": organization_id,
            "student_id": student_id,
            "period": period,
            "amount": _money(amount),
            "discount_amount": _money(discount_amount),
            "currency": currency,
            "vehicle_id": vehicle_id,
            "route_id": route_id,
            "actor_id": actor_id,
        },
    )


def student_invoice_partially_paid(
    *,
    invoice_id: str,
    organization_id: str,
    amount_paid: Decimal,
    balance_due: Decimal,
    currency: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.StudentInvoicePartiallyPaid",
        aggregate_type="StudentInvoice",
        aggregate_id=invoice_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "invoice_id": invoice_id,
            "amount_paid": _money(amount_paid),
            "balance_due": _money(balance_due),
            "currency": currency,
            "actor_id": actor_id,
        },
    )


def student_invoice_paid(
    *,
    invoice_id: str,
    organization_id: str,
    amount_paid: Decimal,
    currency: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.StudentInvoicePaid",
        aggregate_type="StudentInvoice",
        aggregate_id=invoice_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "invoice_id": invoice_id,
            "amount_paid": _money(amount_paid),
            "currency": currency,
            "actor_id": actor_id,
        },
    )


def student_invoice_marked_overdue(
    *,
    invoice_id: str,
    organization_id: str,
    balance_due: Decimal,
    currency: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.StudentInvoiceMarkedOverdue",
        aggregate_type="StudentInvoice",
        aggregate_id=invoice_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "invoice_id": invoice_id,
            "balance_due": _money(balance_due),
            "currency": currency,
            "actor_id": actor_id,
        },
    )


def student_invoice_cancelled(
    *,
    invoice_id: str,
    organization_id: str,
    reason: str | None,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.StudentInvoiceCancelled",
        aggregate_type="StudentInvoice",
        aggregate_id=invoice_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"invoice_id": invoice_id, "reason": reason, "actor_id": actor_id},
    )


# --------------------------------------------------------------------------------------------
# StudentPayment
# --------------------------------------------------------------------------------------------


def student_payment_recorded(
    *,
    payment_id: str,
    organization_id: str,
    invoice_id: str,
    student_id: str,
    amount: Decimal,
    currency: str,
    method: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.StudentPaymentRecorded",
        aggregate_type="StudentPayment",
        aggregate_id=payment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "payment_id": payment_id,
            "organization_id": organization_id,
            "invoice_id": invoice_id,
            "student_id": student_id,
            "amount": _money(amount),
            "currency": currency,
            "method": method,
            "actor_id": actor_id,
        },
    )


def student_payment_voided(
    *,
    payment_id: str,
    organization_id: str,
    invoice_id: str,
    reason: str | None,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.StudentPaymentVoided",
        aggregate_type="StudentPayment",
        aggregate_id=payment_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "payment_id": payment_id,
            "invoice_id": invoice_id,
            "reason": reason,
            "actor_id": actor_id,
        },
    )


# --------------------------------------------------------------------------------------------
# Income / Expense
# --------------------------------------------------------------------------------------------


def income_recorded(
    *,
    income_id: str,
    organization_id: str,
    category_id: str | None,
    amount: Decimal,
    currency: str,
    occurred_on: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.IncomeRecorded",
        aggregate_type="Income",
        aggregate_id=income_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "income_id": income_id,
            "organization_id": organization_id,
            "category_id": category_id,
            "amount": _money(amount),
            "currency": currency,
            "occurred_on": occurred_on,
            "actor_id": actor_id,
        },
    )


def income_voided(
    *,
    income_id: str,
    organization_id: str,
    reason: str | None,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.IncomeVoided",
        aggregate_type="Income",
        aggregate_id=income_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"income_id": income_id, "reason": reason, "actor_id": actor_id},
    )


def expense_recorded(
    *,
    expense_id: str,
    organization_id: str,
    category_id: str | None,
    amount: Decimal,
    currency: str,
    occurred_on: str,
    vehicle_id: str | None,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.ExpenseRecorded",
        aggregate_type="Expense",
        aggregate_id=expense_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "expense_id": expense_id,
            "organization_id": organization_id,
            "category_id": category_id,
            "amount": _money(amount),
            "currency": currency,
            "occurred_on": occurred_on,
            "vehicle_id": vehicle_id,
            "actor_id": actor_id,
        },
    )


def expense_voided(
    *,
    expense_id: str,
    organization_id: str,
    reason: str | None,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.ExpenseVoided",
        aggregate_type="Expense",
        aggregate_id=expense_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"expense_id": expense_id, "reason": reason, "actor_id": actor_id},
    )


# --------------------------------------------------------------------------------------------
# ParentBillingProfile / ParentInvoice (ADR-0042, 2026-09-11 — supersedes ADR-0041 §1)
# --------------------------------------------------------------------------------------------


def parent_billing_profile_created(
    *,
    billing_profile_id: str,
    organization_id: str,
    parent_id: str,
    monthly_fee: Decimal,
    currency: str,
    billing_start_period: str,
    due_day: int,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.ParentBillingProfileCreated",
        aggregate_type="ParentBillingProfile",
        aggregate_id=billing_profile_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "billing_profile_id": billing_profile_id,
            "organization_id": organization_id,
            "parent_id": parent_id,
            "monthly_fee": _money(monthly_fee),
            "currency": currency,
            "billing_start_period": billing_start_period,
            "due_day": due_day,
            "actor_id": actor_id,
        },
    )


def parent_billing_profile_updated(
    *,
    billing_profile_id: str,
    organization_id: str,
    monthly_fee: Decimal,
    currency: str,
    due_day: int,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.ParentBillingProfileUpdated",
        aggregate_type="ParentBillingProfile",
        aggregate_id=billing_profile_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "billing_profile_id": billing_profile_id,
            "monthly_fee": _money(monthly_fee),
            "currency": currency,
            "due_day": due_day,
            "actor_id": actor_id,
        },
    )


def parent_billing_profile_status_changed(
    *,
    billing_profile_id: str,
    organization_id: str,
    status: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.ParentBillingProfileStatusChanged",
        aggregate_type="ParentBillingProfile",
        aggregate_id=billing_profile_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "billing_profile_id": billing_profile_id,
            "status": status,
            "actor_id": actor_id,
        },
    )


def parent_invoice_generated(
    *,
    invoice_id: str,
    organization_id: str,
    parent_id: str,
    period: str,
    amount: Decimal,
    currency: str,
    child_count: int,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.ParentInvoiceGenerated",
        aggregate_type="ParentInvoice",
        aggregate_id=invoice_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "invoice_id": invoice_id,
            "organization_id": organization_id,
            "parent_id": parent_id,
            "period": period,
            "amount": _money(amount),
            "currency": currency,
            "child_count": child_count,
            "actor_id": actor_id,
        },
    )


def parent_invoice_payment_status_updated(
    *,
    invoice_id: str,
    organization_id: str,
    status: str,
    amount_paid: Decimal,
    balance_due: Decimal,
    currency: str,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.ParentInvoicePaymentStatusUpdated",
        aggregate_type="ParentInvoice",
        aggregate_id=invoice_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={
            "invoice_id": invoice_id,
            "status": status,
            "amount_paid": _money(amount_paid),
            "balance_due": _money(balance_due),
            "currency": currency,
            "actor_id": actor_id,
        },
    )


def parent_invoice_cancelled(
    *,
    invoice_id: str,
    organization_id: str,
    reason: str | None,
    occurred_at: datetime,
    actor_id: str | None = None,
) -> DomainEvent:
    return _new_event(
        event_type="school_erp.ParentInvoiceCancelled",
        aggregate_type="ParentInvoice",
        aggregate_id=invoice_id,
        org_id=organization_id,
        occurred_at=occurred_at,
        payload={"invoice_id": invoice_id, "reason": reason, "actor_id": actor_id},
    )
