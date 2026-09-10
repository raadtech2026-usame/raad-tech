"""Write-side command DTOs for `school_erp` (Backend LLD §4.1). Plain frozen dataclasses — no
Pydantic (that lives in `api/schemas.py`), no domain objects (constructed by the service).

Every command carries the acting `Principal`: the service uses it both for the `actor_id` on the
resulting domain event / audit row, and for `_enforce_own_organization`, which is what closes the
write-side IDOR a client-supplied `organization_id` would otherwise open (ADR-0021's own note
that the repository-layer scope fix alone does not cover writes).

Amounts arrive as `str`, not `float`. FastAPI would happily coerce `12.10` to a binary float
before this module ever sees it, and `Decimal("12.10")` built from that float is not 12.10. The
schema layer accepts a number or a string and hands a decimal *string* across this boundary; the
service is the only place that constructs a `Decimal`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from raad.core.tenancy.principal import Principal

# ---- FinancialCategory ---------------------------------------------------------------------


@dataclass(frozen=True)
class CreateFinancialCategoryCommand:
    organization_id: str
    name: str
    kind: str
    parent_category_id: str | None
    description: str | None
    actor: Principal


@dataclass(frozen=True)
class UpdateFinancialCategoryCommand:
    category_id: str
    name: str
    description: str | None
    actor: Principal


@dataclass(frozen=True)
class ArchiveFinancialCategoryCommand:
    category_id: str
    actor: Principal


# ---- FeePlan -------------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateFeePlanCommand:
    organization_id: str
    name: str
    amount: str
    currency: str
    default_discount_amount: str
    description: str | None
    actor: Principal


@dataclass(frozen=True)
class UpdateFeePlanCommand:
    fee_plan_id: str
    name: str
    amount: str
    currency: str
    default_discount_amount: str
    description: str | None
    actor: Principal


@dataclass(frozen=True)
class ArchiveFeePlanCommand:
    fee_plan_id: str
    actor: Principal


# ---- StudentInvoice ------------------------------------------------------------------------


@dataclass(frozen=True)
class IssueStudentInvoiceCommand:
    """Issues one student's invoice for one period.

    `fee_plan_id` is optional: a school may bill an ad-hoc amount without a standing fee plan.
    When supplied, the plan's amount and default discount are used unless explicitly overridden,
    so the common case is a two-field call.
    """

    organization_id: str
    student_id: str
    period: str
    due_date: date
    fee_plan_id: str | None
    amount: str | None
    currency: str | None
    discount_amount: str | None
    notes: str | None
    actor: Principal


@dataclass(frozen=True)
class GenerateStudentInvoicesCommand:
    """Bulk issue for a whole set of students in one period — the monthly billing run.

    Idempotent by construction: a student who already has an invoice for the period is skipped,
    not double-charged, so re-running a partially-failed batch is safe.
    """

    organization_id: str
    period: str
    due_date: date
    fee_plan_id: str
    student_ids: list[str]
    actor: Principal


@dataclass(frozen=True)
class CancelStudentInvoiceCommand:
    invoice_id: str
    reason: str | None
    actor: Principal


# ---- StudentPayment ------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordStudentPaymentCommand:
    invoice_id: str
    amount: str
    currency: str
    method: str
    received_on: date
    reference: str | None
    notes: str | None
    actor: Principal


@dataclass(frozen=True)
class VoidStudentPaymentCommand:
    payment_id: str
    reason: str | None
    actor: Principal


# ---- Income / Expense ----------------------------------------------------------------------


@dataclass(frozen=True)
class RecordIncomeCommand:
    organization_id: str
    category_id: str | None
    amount: str
    currency: str
    occurred_on: date
    description: str | None
    reference: str | None
    actor: Principal


@dataclass(frozen=True)
class VoidIncomeCommand:
    income_id: str
    reason: str | None
    actor: Principal


@dataclass(frozen=True)
class RecordExpenseCommand:
    organization_id: str
    category_id: str | None
    amount: str
    currency: str
    occurred_on: date
    description: str | None
    reference: str | None
    vehicle_id: str | None
    actor: Principal


@dataclass(frozen=True)
class VoidExpenseCommand:
    expense_id: str
    reason: str | None
    actor: Principal
