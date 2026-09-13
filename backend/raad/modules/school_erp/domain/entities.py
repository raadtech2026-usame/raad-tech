"""School ERP aggregates (ADR-0038 §2, ADR-0040 §2). Framework-free — no SQLAlchemy/Pydantic/
FastAPI, no I/O. Behaviour methods mutate state, enforce invariants, and buffer the resulting
`DomainEvent`s, matching every other module's exact shape (`Clock` passed in, never called
internally).

Six aggregates, exactly the set ADR-0038 §2 names for the Organization -> Student money flow:
`FinancialCategory`, `FeePlan`, `StudentInvoice`, `StudentPayment`, `Income`, `Expense`. Two more
were added by ADR-0042 (2026-09-11): `ParentBillingProfile` and `ParentInvoice` (owning
`ParentInvoiceLine` children) — the real Parent-facing billing/invoice aggregates that supersede
ADR-0041 §1's `StudentInvoice`-grouping read model. `StudentInvoice`/`StudentPayment`/`FeePlan`
are unmodified and remain the historical record of the workflow that produced them; see ADR-0042
decision 2.

**Nothing here imports `raad.modules.billing`.** The two invoice aggregates coexist deliberately
(ADR-0038 §2) and the separation is a security boundary, not a modelling preference.

**Money is `Decimal` throughout** (`value_objects.Money`). Student finance sums thousands of
small payments; binary floating point accumulates visible error over that, which is why this
module does not reuse `billing`'s float-backed `Money`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from raad.core.errors.exceptions import DomainError, RuleViolationError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.school_erp.domain import events as erp_events
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

_MAX_NAME = 160
_MAX_DESCRIPTION = 500
_ZERO = Decimal("0.00")
_MIN_DUE_DAY = 1
_MAX_DUE_DAY = 28  # every month has a 28th — Part 5's "Due Day" needs no month-length handling.


class _AggregateRoot:
    """Shared "raise and buffer domain events" mechanics (LLD §8.1), duplicated per module
    deliberately — `.claude/rules/backend.md` #1 forbids one module reaching into another's
    internals, and no approved doc calls for a shared-kernel package (identical to every other
    module's own `_AggregateRoot` copy)."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


def _validate_name(name: str, *, field: str = "name") -> None:
    if not name or not name.strip():
        raise DomainError(f"{field} must not be empty")
    if len(name) > _MAX_NAME:
        raise DomainError(f"{field} must be at most {_MAX_NAME} characters")


def _validate_description(description: str | None) -> None:
    if description is not None and len(description) > _MAX_DESCRIPTION:
        raise DomainError(f"description must be at most {_MAX_DESCRIPTION} characters")


def _validate_due_day(due_day: int) -> None:
    if not (_MIN_DUE_DAY <= due_day <= _MAX_DUE_DAY):
        raise DomainError(
            f"due_day must be between {_MIN_DUE_DAY} and {_MAX_DUE_DAY}: {due_day}"
        )


# ============================================================================================
# FinancialCategory
# ============================================================================================


class FinancialCategory(_AggregateRoot):
    """`erp_financial_categories` — the classification tree income and expenses are filed under.

    One table for both sides of the ledger, discriminated by `kind`, rather than two tables: a
    category is structurally identical either way, and `kind` is what prevents an expense being
    filed under an income heading.

    `parent_category_id` is a self-reference giving one level of nesting for real use
    ("Utilities" -> "Electricity"). It is validated as belonging to the same organization and the
    same `kind` at the application layer, where the sibling row is actually reachable — a domain
    object cannot see its own siblings.
    """

    def __init__(
        self,
        *,
        id: FinancialCategoryId,
        organization_id: OrganizationId,
        name: str,
        kind: CategoryKind,
        parent_category_id: FinancialCategoryId | None,
        description: str | None,
        status: CategoryStatus,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _validate_name(name)
        _validate_description(description)
        self.id = id
        self.organization_id = organization_id
        self.name = name
        self.kind = kind
        self.parent_category_id = parent_category_id
        self.description = description
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FinancialCategory) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def create(
        cls,
        *,
        id: FinancialCategoryId,
        organization_id: OrganizationId,
        name: str,
        kind: CategoryKind,
        parent_category_id: FinancialCategoryId | None = None,
        description: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "FinancialCategory":
        now = clock.now()
        category = cls(
            id=id,
            organization_id=organization_id,
            name=name,
            kind=kind,
            parent_category_id=parent_category_id,
            description=description,
            status=CategoryStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        category._record(
            erp_events.financial_category_created(
                category_id=str(id),
                organization_id=str(organization_id),
                name=name,
                kind=kind.value,
                parent_category_id=str(parent_category_id) if parent_category_id else None,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return category

    def rename(
        self,
        *,
        name: str,
        description: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        _validate_name(name)
        _validate_description(description)
        self.name = name
        self.description = description
        self.updated_at = clock.now()
        self._record(
            erp_events.financial_category_renamed(
                category_id=str(self.id),
                organization_id=str(self.organization_id),
                name=name,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def archive(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Idempotent. A category is archived rather than deleted — historical income and expense
        rows keep pointing at it, and a hard delete would orphan them."""
        if self.status == CategoryStatus.INACTIVE:
            return
        self.status = CategoryStatus.INACTIVE
        self.updated_at = clock.now()
        self._record(
            erp_events.financial_category_archived(
                category_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


# ============================================================================================
# FeePlan
# ============================================================================================


class FeePlan(_AggregateRoot):
    """`erp_fee_plans` — a named recurring charge an organization bills students against
    ("Standard monthly transport", "Half-term shuttle").

    Distinct from `billing.Plan` in every way that matters: this one is **tenant-owned**
    (`organization_id`), is priced by the school, and is billed to a student. `billing.Plan` is
    platform-level, priced by RAAD, and billed to an organization. ADR-0038 §2 requires they stay
    apart.

    `default_discount_amount` is a flat amount rather than a percentage: every requirement here
    names discounts in currency terms, and a stored percentage would need re-deriving an exact
    amount at issue time, which is where rounding disputes come from.
    """

    def __init__(
        self,
        *,
        id: FeePlanId,
        organization_id: OrganizationId,
        name: str,
        amount: Money,
        default_discount_amount: Decimal,
        description: str | None,
        status: FeePlanStatus,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _validate_name(name)
        _validate_description(description)
        if default_discount_amount < _ZERO:
            raise DomainError("default_discount_amount must not be negative")
        if default_discount_amount > amount.amount:
            raise DomainError("default_discount_amount must not exceed the fee amount")
        self.id = id
        self.organization_id = organization_id
        self.name = name
        self.amount = amount
        self.default_discount_amount = default_discount_amount.quantize(Decimal("0.01"))
        self.description = description
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FeePlan) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def create(
        cls,
        *,
        id: FeePlanId,
        organization_id: OrganizationId,
        name: str,
        amount: Money,
        default_discount_amount: Decimal = _ZERO,
        description: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "FeePlan":
        now = clock.now()
        fee_plan = cls(
            id=id,
            organization_id=organization_id,
            name=name,
            amount=amount,
            default_discount_amount=default_discount_amount,
            description=description,
            status=FeePlanStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        fee_plan._record(
            erp_events.fee_plan_created(
                fee_plan_id=str(id),
                organization_id=str(organization_id),
                name=name,
                amount=amount.amount,
                currency=amount.currency,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return fee_plan

    def update_details(
        self,
        *,
        name: str,
        amount: Money,
        default_discount_amount: Decimal,
        description: str | None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Changing a fee plan never retro-changes an already-issued invoice — `StudentInvoice`
        captures its own amount at issue time (see that aggregate). This is the same discipline
        `billing.Plan` follows for subscription invoices."""
        _validate_name(name)
        _validate_description(description)
        if default_discount_amount < _ZERO:
            raise DomainError("default_discount_amount must not be negative")
        if default_discount_amount > amount.amount:
            raise DomainError("default_discount_amount must not exceed the fee amount")
        self.name = name
        self.amount = amount
        self.default_discount_amount = default_discount_amount.quantize(Decimal("0.01"))
        self.description = description
        self.updated_at = clock.now()
        self._record(
            erp_events.fee_plan_updated(
                fee_plan_id=str(self.id),
                organization_id=str(self.organization_id),
                name=name,
                amount=amount.amount,
                currency=amount.currency,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def archive(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == FeePlanStatus.INACTIVE:
            return
        self.status = FeePlanStatus.INACTIVE
        self.updated_at = clock.now()
        self._record(
            erp_events.fee_plan_archived(
                fee_plan_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


# ============================================================================================
# StudentInvoice
# ============================================================================================


class StudentInvoice(_AggregateRoot):
    """`erp_student_invoices` — one period's transport charge to one student.

    **The transportation context is captured on the invoice, not resolved live** (ADR-0040 §3).
    `route_id`, `vehicle_id` and `driver_id` are copied in at issue time so a bill remains a
    historical record of the transport it was actually for: if a student changes bus in March,
    February's invoice must still name February's bus. It also makes per-vehicle revenue a single
    indexed `GROUP BY` on this module's own table, which is what the Vehicle Financial Overview
    needs on every page load, and it is the only option available anyway —
    `.claude/rules/backend.md` #3 forbids the cross-module join a live lookup would need.

    **Partial payment is a stored state, not a derived one.** `amount_paid` is maintained by
    `apply_payment()`, so "who still owes" is a column comparison rather than a correlated sum
    over the payments table.

    **`net_amount` is the authoritative figure**: `amount - discount_amount`. Every balance and
    every total in this module derives from it, never from `amount` alone.
    """

    def __init__(
        self,
        *,
        id: StudentInvoiceId,
        organization_id: OrganizationId,
        student_id: StudentId,
        fee_plan_id: FeePlanId | None,
        period: BillingPeriod,
        amount: Money,
        discount_amount: Decimal,
        amount_paid: Decimal,
        due_date: date,
        status: StudentInvoiceStatus,
        route_id: RouteId | None,
        vehicle_id: VehicleId | None,
        driver_id: DriverId | None,
        notes: str | None,
        issued_at: datetime | None,
        paid_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _validate_description(notes)
        if discount_amount < _ZERO:
            raise DomainError("discount_amount must not be negative")
        if discount_amount > amount.amount:
            raise DomainError("discount_amount must not exceed the invoice amount")
        if amount_paid < _ZERO:
            raise DomainError("amount_paid must not be negative")
        self.id = id
        self.organization_id = organization_id
        self.student_id = student_id
        self.fee_plan_id = fee_plan_id
        self.period = period
        self.amount = amount
        self.discount_amount = discount_amount.quantize(Decimal("0.01"))
        self.amount_paid = amount_paid.quantize(Decimal("0.01"))
        self.due_date = due_date
        self.status = status
        self.route_id = route_id
        self.vehicle_id = vehicle_id
        self.driver_id = driver_id
        self.notes = notes
        self.issued_at = issued_at
        self.paid_at = paid_at
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, StudentInvoice) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def net_amount(self) -> Decimal:
        """What the family actually owes for the period, after discount."""
        return (self.amount.amount - self.discount_amount).quantize(Decimal("0.01"))

    @property
    def balance_due(self) -> Decimal:
        """Never negative: an overpayment shows as a zero balance, not as a negative one, so a
        per-vehicle outstanding total can be summed without one overpaid student masking another
        student's genuine debt."""
        balance = self.net_amount - self.amount_paid
        return balance if balance > _ZERO else _ZERO

    @property
    def is_settled(self) -> bool:
        return self.amount_paid >= self.net_amount

    @classmethod
    def issue(
        cls,
        *,
        id: StudentInvoiceId,
        organization_id: OrganizationId,
        student_id: StudentId,
        fee_plan_id: FeePlanId | None,
        period: BillingPeriod,
        amount: Money,
        due_date: date,
        discount_amount: Decimal = _ZERO,
        route_id: RouteId | None = None,
        vehicle_id: VehicleId | None = None,
        driver_id: DriverId | None = None,
        notes: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "StudentInvoice":
        """Issued directly, never drafted first. `DRAFT` exists in the enum for a future
        bulk-generation flow that stages a run before committing it; nothing issues a draft today,
        and inventing a two-step flow no requirement asks for would be speculative."""
        now = clock.now()
        invoice = cls(
            id=id,
            organization_id=organization_id,
            student_id=student_id,
            fee_plan_id=fee_plan_id,
            period=period,
            amount=amount,
            discount_amount=discount_amount,
            amount_paid=_ZERO,
            due_date=due_date,
            status=StudentInvoiceStatus.ISSUED,
            route_id=route_id,
            vehicle_id=vehicle_id,
            driver_id=driver_id,
            notes=notes,
            issued_at=now,
            paid_at=None,
            created_at=now,
            updated_at=now,
        )
        invoice._record(
            erp_events.student_invoice_issued(
                invoice_id=str(id),
                organization_id=str(organization_id),
                student_id=str(student_id),
                period=str(period),
                amount=amount.amount,
                discount_amount=invoice.discount_amount,
                currency=amount.currency,
                vehicle_id=str(vehicle_id) if vehicle_id else None,
                route_id=str(route_id) if route_id else None,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return invoice

    def apply_payment(
        self, *, amount: Money, clock: Clock, actor_id: str | None = None
    ) -> None:
        """Records money received against this invoice and advances the status.

        Called only by `SchoolErpApplicationService.record_student_payment`, which creates the
        `StudentPayment` row in the same transaction — the two are one business fact and must
        never diverge.
        """
        if self.status == StudentInvoiceStatus.CANCELLED:
            raise RuleViolationError("Cannot pay a cancelled invoice")
        if amount.currency != self.amount.currency:
            raise DomainError(
                f"Payment currency {amount.currency} does not match invoice currency "
                f"{self.amount.currency}"
            )
        if amount.amount <= _ZERO:
            raise DomainError("Payment amount must be greater than zero")

        self.amount_paid = (self.amount_paid + amount.amount).quantize(Decimal("0.01"))
        now = clock.now()
        self.updated_at = now

        if self.is_settled:
            self.status = StudentInvoiceStatus.PAID
            self.paid_at = now
            self._record(
                erp_events.student_invoice_paid(
                    invoice_id=str(self.id),
                    organization_id=str(self.organization_id),
                    amount_paid=self.amount_paid,
                    currency=self.amount.currency,
                    occurred_at=now,
                    actor_id=actor_id,
                )
            )
        else:
            self.status = StudentInvoiceStatus.PARTIALLY_PAID
            self._record(
                erp_events.student_invoice_partially_paid(
                    invoice_id=str(self.id),
                    organization_id=str(self.organization_id),
                    amount_paid=self.amount_paid,
                    balance_due=self.balance_due,
                    currency=self.amount.currency,
                    occurred_at=now,
                    actor_id=actor_id,
                )
            )

    def reverse_payment(
        self, *, amount: Money, clock: Clock, actor_id: str | None = None
    ) -> None:
        """Undoes an applied payment when its `StudentPayment` is voided. Recomputes the status
        from the resulting balance rather than assuming the previous one, so voiding the second
        of two payments correctly lands back on `PARTIALLY_PAID`, not on `ISSUED`."""
        if amount.currency != self.amount.currency:
            raise DomainError(
                f"Reversal currency {amount.currency} does not match invoice currency "
                f"{self.amount.currency}"
            )
        remaining = self.amount_paid - amount.amount
        self.amount_paid = (remaining if remaining > _ZERO else _ZERO).quantize(Decimal("0.01"))
        now = clock.now()
        self.updated_at = now
        self.paid_at = None
        if self.amount_paid <= _ZERO:
            self.status = StudentInvoiceStatus.ISSUED
        elif self.is_settled:
            self.status = StudentInvoiceStatus.PAID
            self.paid_at = now
        else:
            self.status = StudentInvoiceStatus.PARTIALLY_PAID

    def mark_overdue(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Idempotent, and never applied to a settled or cancelled invoice."""
        if self.status in (
            StudentInvoiceStatus.PAID,
            StudentInvoiceStatus.CANCELLED,
            StudentInvoiceStatus.OVERDUE,
        ):
            return
        self.status = StudentInvoiceStatus.OVERDUE
        self.updated_at = clock.now()
        self._record(
            erp_events.student_invoice_marked_overdue(
                invoice_id=str(self.id),
                organization_id=str(self.organization_id),
                balance_due=self.balance_due,
                currency=self.amount.currency,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def cancel(
        self, *, reason: str | None = None, clock: Clock, actor_id: str | None = None
    ) -> None:
        """Waiving a fee is a cancellation with a reason — the `transport_fees.waived` value the
        ADR-0040 §2 migration maps into this state."""
        if self.status == StudentInvoiceStatus.CANCELLED:
            return
        if self.amount_paid > _ZERO:
            raise RuleViolationError(
                "Cannot cancel an invoice that has received payment — void its payments first"
            )
        self.status = StudentInvoiceStatus.CANCELLED
        self.updated_at = clock.now()
        self._record(
            erp_events.student_invoice_cancelled(
                invoice_id=str(self.id),
                organization_id=str(self.organization_id),
                reason=reason,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


# ============================================================================================
# StudentPayment
# ============================================================================================


class StudentPayment(_AggregateRoot):
    """`erp_student_payments` — money received from a family against one `StudentInvoice`.

    A separate aggregate rather than a column on the invoice because a single invoice legitimately
    receives several payments (that is what "partial payments" means), and because each carries
    its own method, reference and receipt date.

    Voided rather than deleted: financial rows are never hard-deleted
    (`.claude/rules/database.md` #5).
    """

    def __init__(
        self,
        *,
        id: StudentPaymentId,
        organization_id: OrganizationId,
        invoice_id: StudentInvoiceId,
        student_id: StudentId,
        amount: Money,
        method: StudentPaymentMethod,
        reference: str | None,
        received_on: date,
        notes: str | None,
        is_voided: bool,
        voided_reason: str | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _validate_description(notes)
        if amount.amount <= _ZERO:
            raise DomainError("Payment amount must be greater than zero")
        self.id = id
        self.organization_id = organization_id
        self.invoice_id = invoice_id
        self.student_id = student_id
        self.amount = amount
        self.method = method
        self.reference = reference
        self.received_on = received_on
        self.notes = notes
        self.is_voided = is_voided
        self.voided_reason = voided_reason
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, StudentPayment) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def record(
        cls,
        *,
        id: StudentPaymentId,
        organization_id: OrganizationId,
        invoice_id: StudentInvoiceId,
        student_id: StudentId,
        amount: Money,
        method: StudentPaymentMethod,
        received_on: date,
        reference: str | None = None,
        notes: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "StudentPayment":
        now = clock.now()
        payment = cls(
            id=id,
            organization_id=organization_id,
            invoice_id=invoice_id,
            student_id=student_id,
            amount=amount,
            method=method,
            reference=reference,
            received_on=received_on,
            notes=notes,
            is_voided=False,
            voided_reason=None,
            created_at=now,
            updated_at=now,
        )
        payment._record(
            erp_events.student_payment_recorded(
                payment_id=str(id),
                organization_id=str(organization_id),
                invoice_id=str(invoice_id),
                student_id=str(student_id),
                amount=amount.amount,
                currency=amount.currency,
                method=method.value,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return payment

    def void(
        self, *, reason: str | None = None, clock: Clock, actor_id: str | None = None
    ) -> None:
        if self.is_voided:
            return
        self.is_voided = True
        self.voided_reason = reason
        self.updated_at = clock.now()
        self._record(
            erp_events.student_payment_voided(
                payment_id=str(self.id),
                organization_id=str(self.organization_id),
                invoice_id=str(self.invoice_id),
                reason=reason,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


# ============================================================================================
# Income / Expense
# ============================================================================================


class Income(_AggregateRoot):
    """`erp_income` — organization income that is *not* a student invoice payment.

    Student fees reach the ledger through `StudentInvoice`/`StudentPayment`, which carry the
    student and transport context this aggregate has no place for. Recording a student fee here
    as well would double-count it, so the application layer keeps the two paths separate and the
    Profit & Loss report sums student payments and this table as two distinct revenue lines.
    """

    def __init__(
        self,
        *,
        id: IncomeId,
        organization_id: OrganizationId,
        category_id: FinancialCategoryId | None,
        amount: Money,
        occurred_on: date,
        description: str | None,
        reference: str | None,
        attachment_url: str | None,
        is_voided: bool,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _validate_description(description)
        if amount.amount <= _ZERO:
            raise DomainError("Income amount must be greater than zero")
        self.id = id
        self.organization_id = organization_id
        self.category_id = category_id
        self.amount = amount
        self.occurred_on = occurred_on
        self.description = description
        self.reference = reference
        self.attachment_url = attachment_url
        self.is_voided = is_voided
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Income) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def record(
        cls,
        *,
        id: IncomeId,
        organization_id: OrganizationId,
        category_id: FinancialCategoryId | None,
        amount: Money,
        occurred_on: date,
        description: str | None = None,
        reference: str | None = None,
        attachment_url: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Income":
        now = clock.now()
        income = cls(
            id=id,
            organization_id=organization_id,
            category_id=category_id,
            amount=amount,
            occurred_on=occurred_on,
            description=description,
            reference=reference,
            attachment_url=attachment_url,
            is_voided=False,
            created_at=now,
            updated_at=now,
        )
        income._record(
            erp_events.income_recorded(
                income_id=str(id),
                organization_id=str(organization_id),
                category_id=str(category_id) if category_id else None,
                amount=amount.amount,
                currency=amount.currency,
                occurred_on=occurred_on.isoformat(),
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return income

    def void(
        self, *, reason: str | None = None, clock: Clock, actor_id: str | None = None
    ) -> None:
        if self.is_voided:
            return
        self.is_voided = True
        self.updated_at = clock.now()
        self._record(
            erp_events.income_voided(
                income_id=str(self.id),
                organization_id=str(self.organization_id),
                reason=reason,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


class Expense(_AggregateRoot):
    """`erp_expenses` — organization expenditure.

    `vehicle_id` is optional and is what makes per-bus cost analysis possible (fuel, maintenance,
    repairs attributed to one vehicle). It is an opaque cross-module reference like every other,
    never FK-constrained.

    `attachment_url` is present and nullable but **nothing populates it yet** — there is no upload
    endpoint and no blob store in this repository (ADR-0040 Consequences). The column exists so
    adding one later is additive rather than a schema change on a financial table.
    """

    def __init__(
        self,
        *,
        id: ExpenseId,
        organization_id: OrganizationId,
        category_id: FinancialCategoryId | None,
        amount: Money,
        occurred_on: date,
        description: str | None,
        reference: str | None,
        vehicle_id: VehicleId | None,
        attachment_url: str | None,
        is_voided: bool,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _validate_description(description)
        if amount.amount <= _ZERO:
            raise DomainError("Expense amount must be greater than zero")
        self.id = id
        self.organization_id = organization_id
        self.category_id = category_id
        self.amount = amount
        self.occurred_on = occurred_on
        self.description = description
        self.reference = reference
        self.vehicle_id = vehicle_id
        self.attachment_url = attachment_url
        self.is_voided = is_voided
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Expense) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def record(
        cls,
        *,
        id: ExpenseId,
        organization_id: OrganizationId,
        category_id: FinancialCategoryId | None,
        amount: Money,
        occurred_on: date,
        description: str | None = None,
        reference: str | None = None,
        vehicle_id: VehicleId | None = None,
        attachment_url: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Expense":
        now = clock.now()
        expense = cls(
            id=id,
            organization_id=organization_id,
            category_id=category_id,
            amount=amount,
            occurred_on=occurred_on,
            description=description,
            reference=reference,
            vehicle_id=vehicle_id,
            attachment_url=attachment_url,
            is_voided=False,
            created_at=now,
            updated_at=now,
        )
        expense._record(
            erp_events.expense_recorded(
                expense_id=str(id),
                organization_id=str(organization_id),
                category_id=str(category_id) if category_id else None,
                amount=amount.amount,
                currency=amount.currency,
                occurred_on=occurred_on.isoformat(),
                vehicle_id=str(vehicle_id) if vehicle_id else None,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return expense

    def void(
        self, *, reason: str | None = None, clock: Clock, actor_id: str | None = None
    ) -> None:
        if self.is_voided:
            return
        self.is_voided = True
        self.updated_at = clock.now()
        self._record(
            erp_events.expense_voided(
                expense_id=str(self.id),
                organization_id=str(self.organization_id),
                reason=reason,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


# ============================================================================================
# ParentBillingProfile / ParentInvoice (ADR-0042, 2026-09-11 — supersedes ADR-0041 §1)
# ============================================================================================
#
# The real financial aggregates the 2026-09-11 directive requires: "Parent Invoice must be a
# real financial document/entity... not merely a grouping of Student invoices." `StudentInvoice`/
# `StudentPayment`/`FeePlan` above are unmodified and remain the historical record of the
# workflow that produced them (ADR-0042 decision 2) — nothing here reads or writes them.


def _split_amount_evenly(total: Decimal, count: int) -> list[Decimal]:
    """Equal split of `total` across `count` children, in whole cents, any remainder cent
    assigned to the first lines — so `sum(result) == total` exactly, never drifting from the
    frozen invoice amount by a rounding cent (ADR-0042 decision 1's disclosed allocation rule:
    every child in a family nominally shares one transportation charge equally)."""
    if count < 1:
        raise DomainError("Cannot split a Parent Invoice amount across zero children")
    cents_total = int((total * 100).to_integral_value())
    base, remainder = divmod(cents_total, count)
    shares: list[Decimal] = []
    for index in range(count):
        share_cents = base + (1 if index < remainder else 0)
        shares.append((Decimal(share_cents) / 100).quantize(Decimal("0.01")))
    return shares


@dataclass(frozen=True)
class BilledChild:
    """One child's billing input for `ParentInvoice.generate`. `line_id` is minted by the
    application layer's `IdGenerator` before this factory is called — the domain layer never
    generates ids itself, the same convention every other factory in this module follows for
    its own `id` parameter."""

    line_id: str
    student_id: str
    vehicle_id: str | None = None
    route_id: str | None = None


class ParentInvoiceLine:
    """Child entity of `ParentInvoice` (`erp_parent_invoice_lines`) — one billed child's own
    share of the family's frozen total, plus the transport context (`vehicle_id`/`route_id`)
    captured at generation time, the identical "a bill is a historical record" reasoning
    ADR-0040 §3 already establishes for `StudentInvoice`. Identity + fields only, no
    `_AggregateRoot` of its own — `ParentInvoice` is the one that records `ParentInvoice*`
    events, mirroring `Stop`'s identical relationship to `Route`.
    """

    def __init__(
        self,
        *,
        id: ParentInvoiceLineId,
        student_id: StudentId,
        amount: Money,
        vehicle_id: VehicleId | None = None,
        route_id: RouteId | None = None,
    ) -> None:
        if amount.amount < _ZERO:
            raise DomainError("Parent invoice line amount must not be negative")
        self.id = id
        self.student_id = student_id
        self.amount = amount
        self.vehicle_id = vehicle_id
        self.route_id = route_id

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ParentInvoiceLine) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class ParentInvoice(_AggregateRoot):
    """`erp_parent_invoices` — the real monthly bill to one Parent (ADR-0042, superseding
    ADR-0041 §1's read-model grouping of `StudentInvoice`). Owns `ParentInvoiceLine` children,
    one per billed child, the same parent/child-entity shape `Route`/`Stop` already establish.

    **`amount` is frozen at generation time from the `ParentBillingProfile`'s fee at that
    moment** — never re-read from the profile afterward. Changing a family's monthly fee
    (`ParentBillingProfile.update_fee`) therefore changes only future invoices, never rewrites a
    historical one — the directive's own worked example: "September: $80. October onward: $100.
    September invoice remains $80."

    **Payment status lives directly here, not on a separate payment aggregate** (ADR-0042
    decision 4): `unpaid`/`partial`/`paid`, set by `set_payment_status`, plus `cancelled` for a
    voided invoice. `amount_paid`/`balance_due`/`status` are this module's sole source of truth
    for what a family owes — there is no `ParentPayment` table to keep in sync.
    """

    def __init__(
        self,
        *,
        id: ParentInvoiceId,
        organization_id: OrganizationId,
        parent_id: ParentId,
        period: BillingPeriod,
        amount: Money,
        amount_paid: Decimal,
        status: ParentInvoiceStatus,
        invoice_date: date,
        due_date: date,
        notes: str | None,
        created_at: datetime,
        updated_at: datetime,
        lines: list[ParentInvoiceLine] | None = None,
    ) -> None:
        super().__init__()
        _validate_description(notes)
        if amount.amount <= _ZERO:
            raise DomainError("Parent invoice amount must be greater than zero")
        if amount_paid < _ZERO:
            raise DomainError("amount_paid must not be negative")
        self.id = id
        self.organization_id = organization_id
        self.parent_id = parent_id
        self.period = period
        self.amount = amount
        self.amount_paid = amount_paid.quantize(Decimal("0.01"))
        self.status = status
        self.invoice_date = invoice_date
        self.due_date = due_date
        self.notes = notes
        self.created_at = created_at
        self.updated_at = updated_at
        self._lines: list[ParentInvoiceLine] = list(lines) if lines else []

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ParentInvoice) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def lines(self) -> tuple[ParentInvoiceLine, ...]:
        return tuple(self._lines)

    @property
    def balance_due(self) -> Decimal:
        """Never negative — an overpayment shows as a zero balance, the identical reasoning
        `StudentInvoice.balance_due` already documents for the same reason (a per-vehicle
        receivables total must be summable without one overpaid family masking another's real
        debt)."""
        balance = self.amount.amount - self.amount_paid
        return balance if balance > _ZERO else _ZERO

    @property
    def is_settled(self) -> bool:
        return self.amount_paid >= self.amount.amount

    @classmethod
    def generate(
        cls,
        *,
        id: ParentInvoiceId,
        organization_id: OrganizationId,
        parent_id: ParentId,
        period: BillingPeriod,
        amount: Money,
        due_date: date,
        children: list[BilledChild],
        clock: Clock,
        actor_id: str | None = None,
    ) -> "ParentInvoice":
        """The monthly billing run's own factory — always issued directly, never drafted first,
        the same "no `DRAFT` state exists to be invented" reasoning `StudentInvoice.issue`
        already gives for an identical enum shape question."""
        if not children:
            raise DomainError("Cannot generate a Parent Invoice with no billed children")
        now = clock.now()
        shares = _split_amount_evenly(amount.amount, len(children))
        lines = [
            ParentInvoiceLine(
                id=ParentInvoiceLineId(child.line_id),
                student_id=StudentId(child.student_id),
                amount=Money(amount=share, currency=amount.currency),
                vehicle_id=VehicleId(child.vehicle_id) if child.vehicle_id else None,
                route_id=RouteId(child.route_id) if child.route_id else None,
            )
            for child, share in zip(children, shares)
        ]
        invoice = cls(
            id=id,
            organization_id=organization_id,
            parent_id=parent_id,
            period=period,
            amount=amount,
            amount_paid=_ZERO,
            status=ParentInvoiceStatus.UNPAID,
            invoice_date=now.date(),
            due_date=due_date,
            notes=None,
            created_at=now,
            updated_at=now,
            lines=lines,
        )
        invoice._record(
            erp_events.parent_invoice_generated(
                invoice_id=str(id),
                organization_id=str(organization_id),
                parent_id=str(parent_id),
                period=str(period),
                amount=amount.amount,
                currency=amount.currency,
                child_count=len(children),
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return invoice

    def set_payment_status(
        self,
        *,
        status: ParentInvoiceStatus,
        amount_paid: Decimal | None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """The entire user-facing payment workflow (the directive's Part 9): Unpaid/Partial/
        Paid, set directly on the invoice. `Paid` resolves `amount_paid` to the full amount
        regardless of what (if anything) was supplied; `Unpaid` forces it to zero; `Partial`
        requires an amount strictly between zero and the total — a caller supplying the full
        amount or zero under `Partial` gets a clear `DomainError` naming the status they
        actually meant, rather than being silently reinterpreted. Idempotent same-state no-op,
        mirroring every other status-change method in this codebase.
        """
        if self.status == ParentInvoiceStatus.CANCELLED:
            raise RuleViolationError(
                "Cannot change the payment status of a cancelled Parent Invoice"
            )
        if status is ParentInvoiceStatus.CANCELLED:
            raise DomainError(
                "Use cancel() to cancel a Parent Invoice, not set_payment_status"
            )

        if status is ParentInvoiceStatus.PAID:
            resolved = self.amount.amount
        elif status is ParentInvoiceStatus.UNPAID:
            resolved = _ZERO
        else:
            if amount_paid is None:
                raise DomainError("amount_paid is required when status is 'partial'")
            resolved = amount_paid.quantize(Decimal("0.01"))
            if resolved <= _ZERO:
                raise DomainError(
                    "Partial payment amount must be greater than zero — use 'unpaid' instead"
                )
            if resolved >= self.amount.amount:
                raise DomainError(
                    "Partial payment amount must be less than the invoice total — "
                    "use 'paid' instead"
                )

        if status == self.status and resolved == self.amount_paid:
            return

        self.amount_paid = resolved
        self.status = status
        self.updated_at = clock.now()
        self._record(
            erp_events.parent_invoice_payment_status_updated(
                invoice_id=str(self.id),
                organization_id=str(self.organization_id),
                status=status.value,
                amount_paid=self.amount_paid,
                balance_due=self.balance_due,
                currency=self.amount.currency,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def cancel(
        self, *, reason: str | None = None, clock: Clock, actor_id: str | None = None
    ) -> None:
        """Mirrors `StudentInvoice.cancel` exactly: a paid-against invoice cannot be cancelled
        outright — its payment status must be reset to `unpaid` first, which is itself only
        possible while nothing has genuinely been collected against it in this simplified
        (no-separate-payment-ledger) model, so this guard is what actually prevents an
        organization from making collected money vanish from Receivables."""
        if self.status == ParentInvoiceStatus.CANCELLED:
            return
        if self.amount_paid > _ZERO:
            raise RuleViolationError(
                "Cannot cancel a Parent Invoice that has received payment — set it back to "
                "unpaid first"
            )
        self.status = ParentInvoiceStatus.CANCELLED
        self.updated_at = clock.now()
        self._record(
            erp_events.parent_invoice_cancelled(
                invoice_id=str(self.id),
                organization_id=str(self.organization_id),
                reason=reason,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


class ParentBillingProfile(_AggregateRoot):
    """`erp_parent_billing_profiles` — the actual recurring transportation charge for one
    Parent (the directive's Part 5), one per `(organization_id, parent_id)`. This is the source
    `generate_parent_invoices` reads each period; it is never itself an invoice.

    **No `FeePlan` reference.** The directive's Part 22 requires Fee Plans to remain optional and
    never gate Parent registration — this aggregate has no foreign key to one, by construction,
    so there is nothing to make mandatory.
    """

    def __init__(
        self,
        *,
        id: ParentBillingProfileId,
        organization_id: OrganizationId,
        parent_id: ParentId,
        monthly_fee: Money,
        billing_start_period: BillingPeriod,
        due_day: int,
        status: ParentBillingProfileStatus,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _validate_due_day(due_day)
        self.id = id
        self.organization_id = organization_id
        self.parent_id = parent_id
        self.monthly_fee = monthly_fee
        self.billing_start_period = billing_start_period
        self.due_day = due_day
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ParentBillingProfile) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def open(
        cls,
        *,
        id: ParentBillingProfileId,
        organization_id: OrganizationId,
        parent_id: ParentId,
        monthly_fee: Money,
        billing_start_period: BillingPeriod,
        due_day: int,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "ParentBillingProfile":
        now = clock.now()
        profile = cls(
            id=id,
            organization_id=organization_id,
            parent_id=parent_id,
            monthly_fee=monthly_fee,
            billing_start_period=billing_start_period,
            due_day=due_day,
            status=ParentBillingProfileStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        profile._record(
            erp_events.parent_billing_profile_created(
                billing_profile_id=str(id),
                organization_id=str(organization_id),
                parent_id=str(parent_id),
                monthly_fee=monthly_fee.amount,
                currency=monthly_fee.currency,
                billing_start_period=str(billing_start_period),
                due_day=due_day,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return profile

    def update_fee(
        self,
        *,
        monthly_fee: Money,
        due_day: int,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Changes what *future* invoices charge. Never rewrites an already-generated
        `ParentInvoice`, which froze its own amount at generation time (`ParentInvoice.generate`)
        — this is the mechanism behind the directive's own worked example in Part 17/40."""
        _validate_due_day(due_day)
        if monthly_fee == self.monthly_fee and due_day == self.due_day:
            return
        self.monthly_fee = monthly_fee
        self.due_day = due_day
        self.updated_at = clock.now()
        self._record(
            erp_events.parent_billing_profile_updated(
                billing_profile_id=str(self.id),
                organization_id=str(self.organization_id),
                monthly_fee=monthly_fee.amount,
                currency=monthly_fee.currency,
                due_day=due_day,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def activate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == ParentBillingProfileStatus.ACTIVE:
            return
        self.status = ParentBillingProfileStatus.ACTIVE
        self.updated_at = clock.now()
        self._record(
            erp_events.parent_billing_profile_status_changed(
                billing_profile_id=str(self.id),
                organization_id=str(self.organization_id),
                status=self.status.value,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def deactivate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Stops future monthly generation from picking this family up, without deleting the
        profile's own history of what it used to charge — the withdrawn-child/fee-waiver case."""
        if self.status == ParentBillingProfileStatus.INACTIVE:
            return
        self.status = ParentBillingProfileStatus.INACTIVE
        self.updated_at = clock.now()
        self._record(
            erp_events.parent_billing_profile_status_changed(
                billing_profile_id=str(self.id),
                organization_id=str(self.organization_id),
                status=self.status.value,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )
