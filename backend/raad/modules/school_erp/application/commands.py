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
    #: ADR-0047 §6: `daily_vehicle` (requires `vehicle_id`) or `other`.
    income_type: str = "other"
    vehicle_id: str | None = None


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


# ---- ParentBillingProfile / ParentInvoice (ADR-0042, 2026-09-11) ---------------------------


@dataclass(frozen=True)
class CreateOrUpdateParentBillingProfileCommand:
    """One family's actual recurring transportation charge (the directive's Part 5). Creates a
    new `ParentBillingProfile` if the parent has none yet, otherwise edits the existing one in
    place (`ParentBillingProfile.update_fee`) — never a second row per parent
    (`ux_erp_parent_billing_profiles__org_parent`). Editing never rewrites an already-generated
    `ParentInvoice`, which froze its own amount at generation time."""

    organization_id: str
    parent_id: str
    monthly_fee: str
    currency: str
    billing_start_period: str
    due_day: int
    actor: Principal


@dataclass(frozen=True)
class SetParentBillingProfileStatusCommand:
    billing_profile_id: str
    is_active: bool
    actor: Principal


@dataclass(frozen=True)
class GenerateParentInvoicesCommand:
    """The monthly billing run (the directive's Part 18) — every `active` `ParentBillingProfile`
    whose `billing_start_period` has arrived is picked up automatically; there is no
    `student_ids`/`fee_plan_id` to supply, unlike the legacy `GenerateStudentInvoicesCommand`,
    because the billing profile already names its own parent and fee. Idempotent: a parent who
    already has a non-cancelled invoice for the period is skipped, not double-charged."""

    organization_id: str
    period: str
    actor: Principal


@dataclass(frozen=True)
class CancelParentInvoiceCommand:
    invoice_id: str
    reason: str | None
    actor: Principal


# ---- ParentPayment (ADR-0047 — amends ADR-0042 §4) -----------------------------------------


@dataclass(frozen=True)
class PaymentAllocationRequest:
    """How much of a payment pays for one student on the invoice. The student's invoice line is
    looked up on the invoice itself — the caller never names a line or a vehicle."""

    student_id: str
    amount: str


@dataclass(frozen=True)
class RecordParentPaymentCommand:
    """Money received against one Parent Invoice. `allocations=None` splits it pro-rata to each
    student's remaining balance (ADR-0047 §3); a payment for one student names only that
    student. `idempotency_key` makes a resubmitted form return the first payment instead of
    recording a second one."""

    invoice_id: str
    amount: str
    currency: str
    method: str
    received_on: date
    reference: str | None
    notes: str | None
    allocations: tuple[PaymentAllocationRequest, ...] | None
    idempotency_key: str | None
    actor: Principal


@dataclass(frozen=True)
class VoidParentPaymentCommand:
    payment_id: str
    reason: str | None
    actor: Principal
