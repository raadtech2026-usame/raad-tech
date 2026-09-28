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

from raad.core.errors.exceptions import ConflictError, DomainError, RuleViolationError
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
    IncomeType,
    Money,
    OrganizationId,
    ParentBillingProfileId,
    ParentBillingProfileStatus,
    ParentId,
    ParentInvoiceId,
    ParentInvoiceLineId,
    ParentInvoiceStatus,
    ParentPaymentAllocationId,
    ParentPaymentId,
    RouteId,
    StudentBillingProfileId,
    StudentId,
    StudentInvoiceId,
    StudentInvoiceStatus,
    StudentPaymentId,
    StudentPaymentMethod,
    VehicleId,
)

_MAX_NAME = 160
_MAX_DESCRIPTION = 500
_MAX_VOID_REASON = 255  # `voided_reason VARCHAR(255)` on every voidable financial table.
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


def _require_void_reason(reason: str | None) -> str:
    """A void removes money from every total, so the record must say why. The UI used to send a
    fixed "Voided by school" string that explained nothing; the reason is now required here, in
    the domain, so no caller can skip it."""
    cleaned = (reason or "").strip()
    if not cleaned:
        raise DomainError("A reason is required to void a financial entry")
    if len(cleaned) > _MAX_VOID_REASON:
        raise DomainError(f"reason must be at most {_MAX_VOID_REASON} characters")
    return cleaned


def _validate_currency(currency: str) -> str:
    """The rule `Money` applies, for an aggregate that holds a currency without an amount."""
    if not isinstance(currency, str) or len(currency.strip()) != 3 or not currency.strip().isalpha():
        raise DomainError(f"Currency must be a 3-letter ISO 4217 code: {currency!r}")
    return currency.strip().upper()


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

    def void(self, *, reason: str | None, clock: Clock, actor_id: str | None = None) -> None:
        if self.is_voided:
            return
        cleaned = _require_void_reason(reason)
        self.is_voided = True
        self.voided_reason = cleaned
        self.updated_at = clock.now()
        self._record(
            erp_events.student_payment_voided(
                payment_id=str(self.id),
                organization_id=str(self.organization_id),
                invoice_id=str(self.invoice_id),
                reason=cleaned,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


# ============================================================================================
# Income / Expense
# ============================================================================================


class Income(_AggregateRoot):
    """`erp_income` — organization income that is *not* a student payment.

    Student income is derived from `ParentPayment` allocations (ADR-0047) and is never an
    `Income` row, so it cannot be entered twice. What lives here is `income_type`:
    `DAILY_VEHICLE` (one bus's collection on one day — `vehicle_id` required) or `OTHER`
    (advertising, rental, donations, grants — `vehicle_id` optional). Profit & Loss reports the
    three sources as separate lines.
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
        voided_reason: str | None = None,
        income_type: IncomeType = IncomeType.OTHER,
        vehicle_id: VehicleId | None = None,
    ) -> None:
        super().__init__()
        _validate_description(description)
        if amount.amount <= _ZERO:
            raise DomainError("Income amount must be greater than zero")
        if income_type is IncomeType.DAILY_VEHICLE and vehicle_id is None:
            raise DomainError("Daily vehicle income must name the vehicle that collected it")
        self.income_type = income_type
        self.vehicle_id = vehicle_id
        self.id = id
        self.organization_id = organization_id
        self.category_id = category_id
        self.amount = amount
        self.occurred_on = occurred_on
        self.description = description
        self.reference = reference
        self.attachment_url = attachment_url
        self.is_voided = is_voided
        # Nullable: entries voided before reasons were stored have none.
        self.voided_reason = voided_reason
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
        income_type: IncomeType = IncomeType.OTHER,
        vehicle_id: VehicleId | None = None,
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
            income_type=income_type,
            vehicle_id=vehicle_id,
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
                income_type=income_type.value,
                vehicle_id=str(vehicle_id) if vehicle_id else None,
            )
        )
        return income

    def void(self, *, reason: str | None, clock: Clock, actor_id: str | None = None) -> None:
        if self.is_voided:
            return
        cleaned = _require_void_reason(reason)
        self.is_voided = True
        self.voided_reason = cleaned
        self.updated_at = clock.now()
        self._record(
            erp_events.income_voided(
                income_id=str(self.id),
                organization_id=str(self.organization_id),
                reason=cleaned,
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
        voided_reason: str | None = None,
    ) -> None:
        super().__init__()
        _validate_description(description)
        if amount.amount <= _ZERO:
            raise DomainError("Expense amount must be greater than zero")
        self.voided_reason = voided_reason
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

    def void(self, *, reason: str | None, clock: Clock, actor_id: str | None = None) -> None:
        if self.is_voided:
            return
        cleaned = _require_void_reason(reason)
        self.is_voided = True
        self.voided_reason = cleaned
        self.updated_at = clock.now()
        self._record(
            erp_events.expense_voided(
                expense_id=str(self.id),
                organization_id=str(self.organization_id),
                reason=cleaned,
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


@dataclass(frozen=True)
class BilledChild:
    """One child's billing input for `ParentInvoice.generate`. `line_id` is minted by the
    application layer's `IdGenerator` before this factory is called — the domain layer never
    generates ids itself, the same convention every other factory in this module follows for
    its own `id` parameter.

    `amount` is this student's own monthly fee, read from their `StudentBillingProfile` at
    generation time (ADR-0048). It becomes the line's frozen charge: changing the student's fee
    later never reaches back into an invoice already generated."""

    line_id: str
    student_id: str
    amount: Decimal
    vehicle_id: str | None = None
    route_id: str | None = None


class ParentInvoiceLine:
    """Child entity of `ParentInvoice` (`erp_parent_invoice_lines`) — one billed child's own
    share of the family's frozen total, what has been paid against that share, and the transport
    context (`vehicle_id`/`route_id`) captured at generation time (ADR-0040 §3, "a bill is a
    historical record").

    **This line is the student's own financial record** (ADR-0047 §2). `amount` is what the
    student was charged for the period, `amount_paid` what has been allocated to them from real
    `ParentPayment`s, `balance_due` what the student still owes. Identity + fields only — only
    `ParentInvoice` changes these figures, so line and invoice can never disagree.
    """

    def __init__(
        self,
        *,
        id: ParentInvoiceLineId,
        student_id: StudentId,
        amount: Money,
        vehicle_id: VehicleId | None = None,
        route_id: RouteId | None = None,
        amount_paid: Decimal = _ZERO,
    ) -> None:
        if amount.amount < _ZERO:
            raise DomainError("Parent invoice line amount must not be negative")
        if amount_paid < _ZERO:
            raise DomainError("Parent invoice line amount_paid must not be negative")
        self.id = id
        self.student_id = student_id
        self.amount = amount
        self.vehicle_id = vehicle_id
        self.route_id = route_id
        self.amount_paid = amount_paid.quantize(Decimal("0.01"))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ParentInvoiceLine) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def balance_due(self) -> Decimal:
        balance = self.amount.amount - self.amount_paid
        return balance if balance > _ZERO else _ZERO


@dataclass(frozen=True)
class LineAllocation:
    """How much of one payment goes to one invoice line. `line_id` is the invoice line's id;
    the student and vehicle are read from that line, never supplied by the caller."""

    line_id: str
    amount: Decimal


def _cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value())


def allocate_pro_rata(
    total: Decimal, balances: list[tuple[str, Decimal]]
) -> list[LineAllocation]:
    """ADR-0047 §3's default split: `total` in proportion to each line's remaining balance.

    Shares are rounded **down** to the cent, then the leftover cents go one at a time, in line
    order, to lines that still have room — so the result sums exactly to `total` and no line is
    ever allocated more than it owes. Lines with nothing left to pay get nothing. A `total`
    above the combined balance is refused: overpayment is never absorbed silently.
    """
    open_lines = [(line_id, balance) for line_id, balance in balances if balance > _ZERO]
    outstanding = sum((balance for _, balance in open_lines), _ZERO)
    if total <= _ZERO:
        raise DomainError("Payment amount must be greater than zero")
    if total > outstanding:
        raise DomainError(
            f"Payment of {total:.2f} exceeds the {outstanding:.2f} still owed on this invoice"
        )
    total_cents = _cents(total)
    outstanding_cents = _cents(outstanding)
    capacities = [_cents(balance) for _, balance in open_lines]
    shares = [total_cents * capacity // outstanding_cents for capacity in capacities]
    leftover = total_cents - sum(shares)
    index = 0
    while leftover > 0:
        position = index % len(open_lines)
        if shares[position] < capacities[position]:
            shares[position] += 1
            leftover -= 1
        index += 1
    return [
        LineAllocation(line_id=line_id, amount=(Decimal(cents) / 100).quantize(Decimal("0.01")))
        for (line_id, _), cents in zip(open_lines, shares)
        if cents > 0
    ]


class ParentInvoice(_AggregateRoot):
    """`erp_parent_invoices` — the real monthly bill to one Parent (ADR-0042, superseding
    ADR-0041 §1's read-model grouping of `StudentInvoice`). Owns `ParentInvoiceLine` children,
    one per billed child, the same parent/child-entity shape `Route`/`Stop` already establish.

    **Every line is frozen at generation time from its student's own fee** (ADR-0048), and
    `amount` is their sum — never re-read afterward. Changing a student's fee
    (`StudentBillingProfile.change_fee`) therefore changes only future invoices and never
    rewrites a historical one.

    **Payment comes only from recorded `ParentPayment`s** (ADR-0047, amending ADR-0042 §4).
    `apply_payment`/`reverse_payment` move the lines' and the invoice's `amount_paid` together,
    and the status is derived from them — there is no way to set a paid amount directly, so the
    invoice can never disagree with its own payments.
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

    def line_for(self, line_id: str) -> ParentInvoiceLine | None:
        return next((line for line in self._lines if str(line.id) == line_id), None)

    def ensure_accepts_payment(self, currency: str) -> None:
        """The invoice-level guards, checked before any allocation is even computed: a cancelled
        invoice cannot be paid (409 RULE_VIOLATION); a fully paid one cannot be paid again (409
        CONFLICT — the P0.1 duplicate-payment guard); the currency must match (400)."""
        if self.status == ParentInvoiceStatus.CANCELLED:
            raise RuleViolationError("Cannot record a payment on a cancelled Parent Invoice")
        if self.is_settled:
            raise ConflictError("This Parent Invoice is already fully paid")
        if currency.upper() != self.amount.currency:
            raise DomainError(
                f"Payment currency {currency.upper()} does not match invoice currency "
                f"{self.amount.currency}"
            )

    def default_allocation(self, total: Decimal) -> list[LineAllocation]:
        """ADR-0047 §3: pro-rata to each line's remaining balance."""
        return allocate_pro_rata(
            total, [(str(line.id), line.balance_due) for line in self._lines]
        )

    @classmethod
    def generate(
        cls,
        *,
        id: ParentInvoiceId,
        organization_id: OrganizationId,
        parent_id: ParentId,
        period: BillingPeriod,
        currency: str,
        due_date: date,
        children: list[BilledChild],
        clock: Clock,
        actor_id: str | None = None,
    ) -> "ParentInvoice":
        """The monthly billing run's own factory — always issued directly, never drafted first,
        the same "no `DRAFT` state exists to be invented" reasoning `StudentInvoice.issue`
        already gives for an identical enum shape question.

        **Per-student pricing (ADR-0048).** Each line carries its own student's fee and the
        invoice total is their sum — there is no family figure to split. A student appears at
        most once, and every line must charge something: a student who rides free is not
        billed at all, rather than billed zero.
        """
        if not children:
            raise DomainError("Cannot generate a Parent Invoice with no billed children")
        student_ids = [child.student_id for child in children]
        if len(set(student_ids)) != len(student_ids):
            raise DomainError("A student can appear only once on a Parent Invoice")
        lines = []
        for child in children:
            line_amount = Money(amount=child.amount, currency=currency)
            if line_amount.amount <= _ZERO:
                raise DomainError(
                    f"Student {child.student_id} has no positive fee to bill for {period}"
                )
            lines.append(
                ParentInvoiceLine(
                    id=ParentInvoiceLineId(child.line_id),
                    student_id=StudentId(child.student_id),
                    amount=line_amount,
                    vehicle_id=VehicleId(child.vehicle_id) if child.vehicle_id else None,
                    route_id=RouteId(child.route_id) if child.route_id else None,
                )
            )
        amount = Money(
            amount=sum((line.amount.amount for line in lines), _ZERO), currency=currency
        )
        now = clock.now()
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

    def apply_payment(
        self,
        *,
        payment_id: str,
        allocations: list[LineAllocation],
        currency: str,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Applies one recorded payment's allocations to this invoice's lines.

        Every guard runs before anything changes, so a refused payment leaves the invoice
        exactly as it was: a cancelled invoice cannot be paid; a fully paid one cannot be paid
        again (the P0.1 duplicate-payment guard, applied to school finance); the currency must
        match; each allocation must be positive, name a line of this invoice at most once, and
        stay within that line's remaining balance — overpayment is refused, never absorbed.
        """
        self.ensure_accepts_payment(currency)
        if not allocations:
            raise DomainError("A payment must be allocated to at least one student")
        seen: set[str] = set()
        for allocation in allocations:
            line = self.line_for(allocation.line_id)
            if line is None:
                raise DomainError(
                    f"Invoice line {allocation.line_id!r} does not belong to this invoice"
                )
            if allocation.line_id in seen:
                raise DomainError("Each student may appear only once in a payment's allocation")
            seen.add(allocation.line_id)
            if allocation.amount <= _ZERO:
                raise DomainError("Every allocated amount must be greater than zero")
            if allocation.amount > line.balance_due:
                raise DomainError(
                    f"Allocation of {allocation.amount:.2f} exceeds the {line.balance_due:.2f} "
                    "still owed for that student on this invoice"
                )

        for allocation in allocations:
            line = self.line_for(allocation.line_id)
            assert line is not None  # validated above
            line.amount_paid = (line.amount_paid + allocation.amount).quantize(Decimal("0.01"))
        total = sum((a.amount for a in allocations), _ZERO)
        self._recompute_from_lines()
        self.updated_at = clock.now()
        self._record(
            erp_events.parent_invoice_payment_applied(
                invoice_id=str(self.id),
                organization_id=str(self.organization_id),
                payment_id=payment_id,
                amount=total,
                status=self.status.value,
                amount_paid=self.amount_paid,
                balance_due=self.balance_due,
                currency=self.amount.currency,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def reverse_payment(
        self,
        *,
        payment_id: str,
        allocations: list[LineAllocation],
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Undoes a voided payment's allocations. The status is re-derived from what remains, so
        voiding one of two payments lands on `partial`, not `unpaid`."""
        for allocation in allocations:
            if self.line_for(allocation.line_id) is None:
                raise DomainError(
                    f"Invoice line {allocation.line_id!r} does not belong to this invoice"
                )
        for allocation in allocations:
            line = self.line_for(allocation.line_id)
            assert line is not None  # validated above
            remaining = line.amount_paid - allocation.amount
            line.amount_paid = (remaining if remaining > _ZERO else _ZERO).quantize(
                Decimal("0.01")
            )
        total = sum((a.amount for a in allocations), _ZERO)
        self._recompute_from_lines()
        self.updated_at = clock.now()
        self._record(
            erp_events.parent_invoice_payment_reversed(
                invoice_id=str(self.id),
                organization_id=str(self.organization_id),
                payment_id=payment_id,
                amount=total,
                status=self.status.value,
                amount_paid=self.amount_paid,
                balance_due=self.balance_due,
                currency=self.amount.currency,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def _recompute_from_lines(self) -> None:
        self.amount_paid = sum((line.amount_paid for line in self._lines), _ZERO).quantize(
            Decimal("0.01")
        )
        if self.status == ParentInvoiceStatus.CANCELLED:
            return
        if self.amount_paid <= _ZERO:
            self.status = ParentInvoiceStatus.UNPAID
        elif self.amount_paid >= self.amount.amount:
            self.status = ParentInvoiceStatus.PAID
        else:
            self.status = ParentInvoiceStatus.PARTIAL

    def cancel(
        self, *, reason: str | None = None, clock: Clock, actor_id: str | None = None
    ) -> None:
        """An invoice that has received payment cannot be cancelled — its payments must be
        voided first (each with a reason), which is what stops collected money quietly vanishing
        from Receivables and from the students' own histories."""
        if self.status == ParentInvoiceStatus.CANCELLED:
            return
        if self.amount_paid > _ZERO:
            raise RuleViolationError(
                "Cannot cancel a Parent Invoice that has received payment — void its payments "
                "first"
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


# ============================================================================================
# ParentPayment (ADR-0047 — amends ADR-0042 §4)
# ============================================================================================


class ParentPaymentAllocation:
    """Child entity of `ParentPayment` (`erp_parent_payment_allocations`) — the part of one
    payment that paid for one student's invoice line. `student_id` and `vehicle_id` are copied
    from the line when the payment is recorded, so a student's payment history and a bus's
    student income are both plain reads, and a later bus change cannot move historical money
    (ADR-0047 §5)."""

    def __init__(
        self,
        *,
        id: ParentPaymentAllocationId,
        line_id: ParentInvoiceLineId,
        student_id: StudentId,
        amount: Money,
        vehicle_id: VehicleId | None = None,
    ) -> None:
        if amount.amount <= _ZERO:
            raise DomainError("Allocated amount must be greater than zero")
        self.id = id
        self.line_id = line_id
        self.student_id = student_id
        self.amount = amount
        self.vehicle_id = vehicle_id

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ParentPaymentAllocation) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


@dataclass(frozen=True)
class PaymentAllocationInput:
    """What `ParentPayment.record` needs per allocated line — ids minted by the application
    layer, student/vehicle already read off the invoice line."""

    allocation_id: str
    line_id: str
    student_id: str
    vehicle_id: str | None
    amount: Decimal


class ParentPayment(_AggregateRoot):
    """`erp_parent_payments` — money received from a family against one `ParentInvoice`
    (ADR-0047 §1). Carries method, reference and receipt date, and is split across the
    invoice's lines by its allocations, which always sum to the payment amount.

    A payment for one specific student is a payment with that student's line as its only
    allocation — there is no second payment type. Voided, never deleted
    (`.claude/rules/database.md` #5); voiding requires a reason (P0.4).
    """

    def __init__(
        self,
        *,
        id: ParentPaymentId,
        organization_id: OrganizationId,
        parent_id: ParentId,
        invoice_id: ParentInvoiceId,
        amount: Money,
        method: StudentPaymentMethod,
        reference: str | None,
        received_on: date,
        notes: str | None,
        is_voided: bool,
        voided_reason: str | None,
        idempotency_key: str | None,
        created_at: datetime,
        updated_at: datetime,
        allocations: list[ParentPaymentAllocation],
    ) -> None:
        super().__init__()
        _validate_description(notes)
        if amount.amount <= _ZERO:
            raise DomainError("Payment amount must be greater than zero")
        if not allocations:
            raise DomainError("A payment must be allocated to at least one student")
        allocated = sum((a.amount.amount for a in allocations), _ZERO)
        if allocated != amount.amount:
            raise DomainError(
                f"Allocations total {allocated:.2f} but the payment is {amount.amount:.2f}"
            )
        if any(a.amount.currency != amount.currency for a in allocations):
            raise DomainError("Every allocation must be in the payment's currency")
        if reference is not None and len(reference) > 120:
            raise DomainError("reference must be at most 120 characters")
        self.id = id
        self.organization_id = organization_id
        self.parent_id = parent_id
        self.invoice_id = invoice_id
        self.amount = amount
        self.method = method
        self.reference = reference
        self.received_on = received_on
        self.notes = notes
        self.is_voided = is_voided
        self.voided_reason = voided_reason
        self.idempotency_key = idempotency_key
        self.created_at = created_at
        self.updated_at = updated_at
        self._allocations = list(allocations)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ParentPayment) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def allocations(self) -> tuple[ParentPaymentAllocation, ...]:
        return tuple(self._allocations)

    def as_line_allocations(self) -> list[LineAllocation]:
        return [
            LineAllocation(line_id=str(a.line_id), amount=a.amount.amount)
            for a in self._allocations
        ]

    @classmethod
    def record(
        cls,
        *,
        id: ParentPaymentId,
        organization_id: OrganizationId,
        parent_id: ParentId,
        invoice_id: ParentInvoiceId,
        amount: Money,
        method: StudentPaymentMethod,
        received_on: date,
        allocations: list[PaymentAllocationInput],
        reference: str | None = None,
        notes: str | None = None,
        idempotency_key: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "ParentPayment":
        now = clock.now()
        payment = cls(
            id=id,
            organization_id=organization_id,
            parent_id=parent_id,
            invoice_id=invoice_id,
            amount=amount,
            method=method,
            reference=reference,
            received_on=received_on,
            notes=notes,
            is_voided=False,
            voided_reason=None,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
            allocations=[
                ParentPaymentAllocation(
                    id=ParentPaymentAllocationId(item.allocation_id),
                    line_id=ParentInvoiceLineId(item.line_id),
                    student_id=StudentId(item.student_id),
                    amount=Money(amount=item.amount, currency=amount.currency),
                    vehicle_id=VehicleId(item.vehicle_id) if item.vehicle_id else None,
                )
                for item in allocations
            ],
        )
        payment._record(
            erp_events.parent_payment_recorded(
                payment_id=str(id),
                organization_id=str(organization_id),
                parent_id=str(parent_id),
                invoice_id=str(invoice_id),
                amount=amount.amount,
                currency=amount.currency,
                method=method.value,
                received_on=received_on.isoformat(),
                allocations=[
                    {
                        "student_id": str(a.student_id),
                        "line_id": str(a.line_id),
                        "amount": f"{a.amount.amount:.2f}",
                    }
                    for a in payment.allocations
                ],
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return payment

    def void(self, *, reason: str | None, clock: Clock, actor_id: str | None = None) -> bool:
        """Returns whether this call actually voided the payment. Idempotent: voiding an
        already-voided payment returns `False`, so the caller reverses the invoice only once."""
        if self.is_voided:
            return False
        cleaned = _require_void_reason(reason)
        self.is_voided = True
        self.voided_reason = cleaned
        self.updated_at = clock.now()
        self._record(
            erp_events.parent_payment_voided(
                payment_id=str(self.id),
                organization_id=str(self.organization_id),
                invoice_id=str(self.invoice_id),
                reason=cleaned,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )
        return True


class ParentBillingProfile(_AggregateRoot):
    """`erp_parent_billing_profiles` — one Parent's **billing account** (ADR-0042, narrowed by
    ADR-0048), one per `(organization_id, parent_id)`: whether the family is billed at all
    (`status`), from which period, on which due day and in which currency. It is never itself
    an invoice.

    **It no longer carries a fee.** ADR-0042 stored one family figure here and split it equally
    across the children; ADR-0048 moved the fee to each student (`StudentBillingProfile`), so a
    family's total is always the sum of its children's own fees. The retired
    `erp_parent_billing_profiles.monthly_fee` column keeps its old values as history and is
    neither read nor written.

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
        currency: str,
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
        self.currency = _validate_currency(currency)
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
        currency: str,
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
            currency=currency,
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
                currency=profile.currency,
                billing_start_period=str(billing_start_period),
                due_day=due_day,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return profile

    def update_terms(
        self,
        *,
        currency: str,
        billing_start_period: BillingPeriod,
        due_day: int,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Changes the terms *future* invoices are generated on. Never rewrites an
        already-generated `ParentInvoice`, which froze its own lines at generation time."""
        _validate_due_day(due_day)
        currency = _validate_currency(currency)
        if (
            currency == self.currency
            and billing_start_period == self.billing_start_period
            and due_day == self.due_day
        ):
            return
        self.currency = currency
        self.billing_start_period = billing_start_period
        self.due_day = due_day
        self.updated_at = clock.now()
        self._record(
            erp_events.parent_billing_profile_updated(
                billing_profile_id=str(self.id),
                organization_id=str(self.organization_id),
                currency=currency,
                billing_start_period=str(billing_start_period),
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


# ============================================================================================
# StudentBillingProfile (ADR-0048)
# ============================================================================================


class StudentBillingProfile(_AggregateRoot):
    """`erp_student_billing_profiles` — one student's own recurring monthly transportation fee,
    one per `(organization_id, student_id)` (ADR-0048).

    A Parent Invoice line's amount comes from here: the monthly run bills each of a family's
    active children at their own fee, and the family total is the sum. The fee is
    configuration, not money owed — nothing here is a receivable until an invoice freezes it.

    **Zero is a real answer.** A fee of 0.00 records "this student rides free" (a scholarship,
    a staff child) and bills no line. That is different from a student nobody has priced yet,
    which the monthly run reports as needing attention.
    """

    def __init__(
        self,
        *,
        id: StudentBillingProfileId,
        organization_id: OrganizationId,
        student_id: StudentId,
        monthly_fee: Money,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.student_id = student_id
        self.monthly_fee = monthly_fee
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, StudentBillingProfile) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def is_billable(self) -> bool:
        return self.monthly_fee.amount > _ZERO

    @classmethod
    def open(
        cls,
        *,
        id: StudentBillingProfileId,
        organization_id: OrganizationId,
        student_id: StudentId,
        monthly_fee: Money,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "StudentBillingProfile":
        now = clock.now()
        profile = cls(
            id=id,
            organization_id=organization_id,
            student_id=student_id,
            monthly_fee=monthly_fee,
            created_at=now,
            updated_at=now,
        )
        profile._record_fee_set(previous=None, now=now, actor_id=actor_id)
        return profile

    def change_fee(
        self, *, monthly_fee: Money, clock: Clock, actor_id: str | None = None
    ) -> None:
        """Changes what *future* invoices charge this student. An invoice already generated
        keeps its own frozen line amount — the historical record never moves."""
        if monthly_fee == self.monthly_fee:
            return
        previous = self.monthly_fee
        self.monthly_fee = monthly_fee
        self.updated_at = clock.now()
        self._record_fee_set(previous=previous, now=self.updated_at, actor_id=actor_id)

    def _record_fee_set(
        self, *, previous: Money | None, now: datetime, actor_id: str | None
    ) -> None:
        self._record(
            erp_events.student_billing_fee_set(
                billing_profile_id=str(self.id),
                organization_id=str(self.organization_id),
                student_id=str(self.student_id),
                monthly_fee=self.monthly_fee.amount,
                previous_monthly_fee=previous.amount if previous is not None else None,
                currency=self.monthly_fee.currency,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
