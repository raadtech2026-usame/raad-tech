"""School ERP aggregates (ADR-0038 §2, ADR-0040 §2). Framework-free — no SQLAlchemy/Pydantic/
FastAPI, no I/O. Behaviour methods mutate state, enforce invariants, and buffer the resulting
`DomainEvent`s, matching every other module's exact shape (`Clock` passed in, never called
internally).

Six aggregates, exactly the set ADR-0038 §2 names for the Organization -> Student money flow:
`FinancialCategory`, `FeePlan`, `StudentInvoice`, `StudentPayment`, `Income`, `Expense`.

**Nothing here imports `raad.modules.billing`.** The two invoice aggregates coexist deliberately
(ADR-0038 §2) and the separation is a security boundary, not a modelling preference.

**Money is `Decimal` throughout** (`value_objects.Money`). Student finance sums thousands of
small payments; binary floating point accumulates visible error over that, which is why this
module does not reuse `billing`'s float-backed `Money`.
"""

from __future__ import annotations

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
