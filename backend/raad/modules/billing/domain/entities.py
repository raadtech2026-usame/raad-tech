"""Billing entities (Backend LLD §5.1/§5.2; Database Design §8.1-§8.5). Framework-free — no
SQLAlchemy/Pydantic/FastAPI, no I/O. Behavior methods mutate state, enforce invariants, and
buffer the resulting `DomainEvent`s, matching `transport_ops.domain.entities`'s exact shape
(`Clock` passed in, never called internally).

**Phase 15 scope: all five documented aggregates** (`Plan`, `Subscription`, `Invoice`,
`Payment`, `TransportFee`) — see `value_objects.py`'s module docstring for the full scope note
and the cross-module-reference/undocumented-enum reasoning shared by all five.

**No LLD aggregate contract skeleton exists for any of these five** (unlike `Trip`/
`DeviceAssignment`, which LLD §5.2 gives worked examples for) — every behavior method below is
built by structural analogy to the closest already-completed precedent in this codebase,
flagged per-method where the precedent is genuinely novel rather than a straightforward mirror.

**Real conflict between two approved documents, resolved and flagged, not silently picked:**
Phase-2 §20.2's payment-workflow sequence diagram narrates "Create Invoice (PENDING)" and, on
failure, "Mark Invoice FAILED" — but Database Design §8.3's `invoices.status` enum has no
`PENDING` or `FAILED` member (`draft,issued,paid,void` only), while §8.4's `payments.status`
enum has both (`pending,processing,paid,failed,expired,refunded`). Read together: the §20.2
narrative is describing the **Payment's** state at those two points, loosely attributed to
"Invoice" in prose. This file's `Invoice.issue()` starts at `ISSUED` (the nearest documented
status meaning "exists, payable" — not `DRAFT`, which implies not-yet-finalized/sent, inconsistent
with an invoice immediately charged against per the same sequence). `Invoice` never reaches a
"failed" status; `Payment.mark_failed()` is where a declined/timeout/cancelled charge is actually
recorded, leaving the invoice `ISSUED` (unpaid, awaiting a further attempt).

**"Retry (new attempt)" (Phase-2 §20.3: `Failed --> Pending: retry (new attempt)`) is modeled as
a brand-new `Payment` row, not a mutation of the failed one.** `payments.idempotency_key` is
globally unique (`ux_payments__idem`, §8.4) and API Contracts §12 documents idempotency as
"a repeat with the **same** key returns the original result" — a retry therefore necessarily
carries a **different** idempotency key, which is a new `Payment.initiate(...)` call (a new row
referencing the same invoice), not a status mutation on the existing one. No `Payment.retry()`
method exists here for that reason — inventing one would either violate the documented
idempotency semantics (reusing the same key) or silently invent a second, undocumented key
regeneration mechanism.

**`SubscriptionStatus.TRIAL` used as the "just opened, not yet paid" starting state — flagged,
not a trial-period business rule.** No document describes free-trial duration, trial-only
features, or trial auto-expiry — none of that is implemented or assumed. `TRIAL` is used purely
as the documented enum's own least-committal non-`ACTIVE` value, because Database Design §8.2
gives no "pending"/"unconfirmed" status a newly-created, not-yet-paid subscription could occupy
instead, and Database Design §8.3's `invoices.subscription_id` is a required (`NOT NULL`) FK —
meaning a `Subscription` row must exist *before* its first `Invoice` can be created at all
(Phase-2 §20.2's own sequence order), so "doesn't exist until paid" is not an available option.

**No "one active subscription per subscriber" invariant is documented** — unlike `Trip`
(one active per vehicle), `StudentAssignment` (one active per student), or `DeviceAssignment`
(one active per device/vehicle), Database Design §8.2 defines no generated-column/partial-unique
constraint for `subscriptions`. None is enforced here; inventing one would be a genuinely new
business rule no document states.

**`invoices.number`'s format is undocumented** (§8.3 gives only "`number UX`" — unique, no
format). `Invoice.issue()` sets it to the invoice's own id string — avoids inventing a
sequential/formatted numbering scheme (e.g. "INV-2026-0001") no document specifies, while still
satisfying the documented uniqueness constraint trivially (ids are already globally unique).

**`transport_fees.period`'s type is undocumented** (§8.5 gives only the bare column name
`period`, unlike every sibling table's fully-typed columns). Modeled as a plain label string
(e.g. `"2026-07"`) rather than a `period_start`/`period_end` pair — `subscriptions`/`invoices`
both spell out an explicit start/end pair *when that's what they mean*; `transport_fees` giving
only one field is read as a single informal label, not an under-specified pair.
"""

from __future__ import annotations

from datetime import date, datetime

from raad.core.errors.exceptions import DomainError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.billing.domain import events as billing_events
from raad.modules.billing.domain.value_objects import (
    BillingCycle,
    BillingScope,
    InvoiceId,
    InvoiceStatus,
    Money,
    OrganizationId,
    PaymentId,
    PaymentStatus,
    PlanId,
    PlanStatus,
    StudentId,
    SubscriberId,
    SubscriberType,
    SubscriptionId,
    SubscriptionStatus,
    TransportFeeId,
    TransportFeeStatus,
)

_PLAN_NAME_MAX_LENGTH = 160  # Database Design §8.1 gives no explicit length (compact
# notation) - mirrors transport_ops.Route.name's identical VARCHAR(160) precedent for an
# analogous short human-readable label with no documented length of its own.
_PROVIDER_MAX_LENGTH = 40  # Database Design §8.4: payments.provider VARCHAR(40)
_PROVIDER_REF_MAX_LENGTH = 120  # §8.4: payments.provider_ref VARCHAR(120)
_MSISDN_MASKED_MAX_LENGTH = 32  # §8.4: payments.msisdn_masked VARCHAR(32)
_IDEMPOTENCY_KEY_MAX_LENGTH = 64  # §8.4: payments.idempotency_key CHAR(64)


def _validate_plan_name(name: str) -> None:
    if not name:
        raise DomainError("Plan name must not be empty")
    if len(name) > _PLAN_NAME_MAX_LENGTH:
        raise DomainError(
            f"Plan name must be at most {_PLAN_NAME_MAX_LENGTH} characters: {len(name)}"
        )


def _validate_idempotency_key(idempotency_key: str) -> None:
    if not idempotency_key:
        raise DomainError("Payment idempotency_key must not be empty")
    if len(idempotency_key) > _IDEMPOTENCY_KEY_MAX_LENGTH:
        raise DomainError(
            f"Payment idempotency_key must be at most {_IDEMPOTENCY_KEY_MAX_LENGTH} "
            f"characters: {len(idempotency_key)}"
        )


class _AggregateRoot:
    """Shared "raise and buffer domain events" mechanics (LLD §8.1), duplicated per module
    deliberately — `.claude/rules/backend.md` #1 forbids one module reaching into another's
    internals, and no approved doc calls for a shared-kernel package (identical to every other
    module's own `_AggregateRoot` copy, e.g. `transport_ops.domain.entities._AggregateRoot`)."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


class Plan(_AggregateRoot):
    """`plans` (Database Design §8.1): a purchasable subscription plan. Not tenant-owned —
    unlike every `transport_ops` aggregate, §8.1 gives `plans` no `organization_id` column at
    all (plans are platform-level, offered to any organization/parent), so this aggregate
    carries none, the same "don't model a column no approved document defines" discipline every
    other aggregate in this codebase already follows for its own absent fields.
    """

    def __init__(
        self,
        *,
        id: PlanId,
        name: str,
        billing_scope: BillingScope,
        price: Money,
        billing_cycle: BillingCycle,
        vehicle_limit: int | None,
        status: PlanStatus,
    ) -> None:
        super().__init__()
        _validate_plan_name(name)
        self.id = id
        self.name = name
        self.billing_scope = billing_scope
        self.price = price
        self.billing_cycle = billing_cycle
        self.vehicle_limit = vehicle_limit
        self.status = status

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Plan) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def create(
        cls,
        *,
        id: PlanId,
        name: str,
        billing_scope: BillingScope,
        price: Money,
        billing_cycle: BillingCycle,
        vehicle_limit: int | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Plan":
        """No approved document names a creation event or a specific starting status for
        `Plan` — starts `ACTIVE`, the same "no pending/draft status documented, so start at the
        one non-terminal documented value" reasoning `Route.create`/`Driver.register` already
        establish for their own undocumented-richer-lifecycle situations."""
        plan = cls(
            id=id,
            name=name,
            billing_scope=billing_scope,
            price=price,
            billing_cycle=billing_cycle,
            vehicle_limit=vehicle_limit,
            status=PlanStatus.ACTIVE,
        )
        plan._record(
            billing_events.plan_created(
                plan_id=str(id),
                name=name,
                billing_scope=billing_scope.value,
                amount=price.amount,
                currency=price.currency,
                billing_cycle=billing_cycle.value,
                vehicle_limit=vehicle_limit,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return plan

    def activate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == PlanStatus.ACTIVE:
            return
        self.status = PlanStatus.ACTIVE
        self._record(
            billing_events.plan_activated(
                plan_id=str(self.id), occurred_at=clock.now(), actor_id=actor_id
            )
        )

    def disable(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == PlanStatus.INACTIVE:
            return
        self.status = PlanStatus.INACTIVE
        self._record(
            billing_events.plan_disabled(
                plan_id=str(self.id), occurred_at=clock.now(), actor_id=actor_id
            )
        )


class Subscription(_AggregateRoot):
    """`subscriptions` (Database Design §8.2): governs which billing model (CR-1's
    `billing_model` input, evaluated by `core.policies.SubscriptionAccessPolicy` — never
    reimplemented here, only the `subscription_state` fact this aggregate produces) a
    subscriber is on. Tenant-owned (`organization_id`, even for a `PARENT` subscriber — §8.2
    lists it as `no, ix`, i.e. required regardless of `subscriber_type`).
    """

    def __init__(
        self,
        *,
        id: SubscriptionId,
        organization_id: OrganizationId,
        subscriber_type: SubscriberType,
        subscriber_id: SubscriberId,
        plan_id: PlanId,
        status: SubscriptionStatus,
        current_period_start: datetime | None,
        current_period_end: datetime | None,
        auto_renew: bool,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.subscriber_type = subscriber_type
        self.subscriber_id = subscriber_id
        self.plan_id = plan_id
        self.status = status
        self.current_period_start = current_period_start
        self.current_period_end = current_period_end
        self.auto_renew = auto_renew

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Subscription) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def open(
        cls,
        *,
        id: SubscriptionId,
        organization_id: OrganizationId,
        subscriber_type: SubscriberType,
        subscriber_id: SubscriberId,
        plan_id: PlanId,
        auto_renew: bool = True,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Subscription":
        """Starts `TRIAL` — see module docstring for why (not a free-trial business rule, the
        documented enum's own least-committal non-`ACTIVE` starting value)."""
        subscription = cls(
            id=id,
            organization_id=organization_id,
            subscriber_type=subscriber_type,
            subscriber_id=subscriber_id,
            plan_id=plan_id,
            status=SubscriptionStatus.TRIAL,
            current_period_start=None,
            current_period_end=None,
            auto_renew=auto_renew,
        )
        subscription._record(
            billing_events.subscription_opened(
                subscription_id=str(id),
                organization_id=str(organization_id),
                subscriber_type=subscriber_type.value,
                subscriber_id=str(subscriber_id),
                plan_id=str(plan_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return subscription

    def renew(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """`SubscriptionRenewed` (Backend LLD §5.4 verbatim) — called after a successful
        payment (Phase-2 §20.2: "Mark Invoice PAID, extend Subscription"). Transitions to
        `ACTIVE` and sets the new period regardless of the prior status — no document
        restricts renewal by prior state, the same "no invented restriction graph" precedent
        `Trip.change_driver` already establishes for its own undocumented restriction question.
        """
        self.status = SubscriptionStatus.ACTIVE
        self.current_period_start = period_start
        self.current_period_end = period_end
        self._record(
            billing_events.subscription_renewed(
                subscription_id=str(self.id),
                organization_id=str(self.organization_id),
                period_start=period_start.isoformat(),
                period_end=period_end.isoformat(),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def expire(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`SubscriptionExpired` (Backend LLD §5.4 verbatim) — one of the two documented CR-1
        re-evaluation events. Idempotent same-state no-op."""
        if self.status == SubscriptionStatus.EXPIRED:
            return
        self.status = SubscriptionStatus.EXPIRED
        self._record(
            billing_events.subscription_expired(
                subscription_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def suspend(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`SUSPENDED` is a documented `SubscriptionStatus` value (Database Design §8.2) but no
        document describes what triggers it — implemented for completeness of the documented
        enum's own state space (mirroring `expire`'s shape), flagged as reachable at this layer
        only; no caller wires it this phase."""
        if self.status == SubscriptionStatus.SUSPENDED:
            return
        self.status = SubscriptionStatus.SUSPENDED
        self._record(
            billing_events.subscription_suspended(
                subscription_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def cancel(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Same posture as `suspend` — a documented status value with no documented trigger."""
        if self.status == SubscriptionStatus.CANCELLED:
            return
        self.status = SubscriptionStatus.CANCELLED
        self._record(
            billing_events.subscription_cancelled(
                subscription_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class Invoice(_AggregateRoot):
    """`invoices` (Database Design §8.3). See module docstring for the resolved Phase-2
    §20.2-vs-Database-Design-§8.3 conflict (`ISSUED`, not `DRAFT`, at creation; no "failed"
    status) and the undocumented `number` format (set to the invoice's own id)."""

    def __init__(
        self,
        *,
        id: InvoiceId,
        organization_id: OrganizationId,
        subscription_id: SubscriptionId,
        number: str,
        amount: Money,
        period_start: date,
        period_end: date,
        status: InvoiceStatus,
        issued_at: datetime | None,
        due_at: datetime | None,
        paid_at: datetime | None,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.subscription_id = subscription_id
        self.number = number
        self.amount = amount
        self.period_start = period_start
        self.period_end = period_end
        self.status = status
        self.issued_at = issued_at
        self.due_at = due_at
        self.paid_at = paid_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Invoice) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def issue(
        cls,
        *,
        id: InvoiceId,
        organization_id: OrganizationId,
        subscription_id: SubscriptionId,
        amount: Money,
        period_start: date,
        period_end: date,
        due_at: datetime | None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Invoice":
        now = clock.now()
        invoice = cls(
            id=id,
            organization_id=organization_id,
            subscription_id=subscription_id,
            number=str(id),
            amount=amount,
            period_start=period_start,
            period_end=period_end,
            status=InvoiceStatus.ISSUED,
            issued_at=now,
            due_at=due_at,
            paid_at=None,
        )
        invoice._record(
            billing_events.invoice_issued(
                invoice_id=str(id),
                organization_id=str(organization_id),
                subscription_id=str(subscription_id),
                amount=amount.amount,
                currency=amount.currency,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return invoice

    def mark_paid(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Called after a successful `Payment` (Phase-2 §20.2: "Mark Invoice PAID"). Idempotent
        same-state no-op."""
        if self.status == InvoiceStatus.PAID:
            return
        self.status = InvoiceStatus.PAID
        self.paid_at = clock.now()
        self._record(
            billing_events.invoice_paid(
                invoice_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=self.paid_at,
                actor_id=actor_id,
            )
        )

    def void(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`VOID` is documented (§8.3) but no trigger is described — implemented for
        completeness, same posture as `Subscription.suspend`/`cancel`."""
        if self.status == InvoiceStatus.VOID:
            return
        self.status = InvoiceStatus.VOID
        self._record(
            billing_events.invoice_voided(
                invoice_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class Payment(_AggregateRoot):
    """`payments` (Database Design §8.4). **No `+ standard audit cols` line in §8.3's table** —
    unlike `Plan`/`Subscription`/`Invoice`/`TransportFee`, this table lists exactly its own
    columns (including its own `created_at`/`confirmed_at` pair), the identical situation
    `student_parents`/`device_assignments` already establish elsewhere in this codebase for a
    table whose own timestamp columns already serve the audit purpose (`infra/models.py`'s own
    docstring explains the resulting `UlidPrimaryKeyMixin`-only ORM treatment).
    """

    def __init__(
        self,
        *,
        id: PaymentId,
        organization_id: OrganizationId,
        invoice_id: InvoiceId,
        provider: str,
        provider_ref: str | None,
        msisdn_masked: str | None,
        amount: Money,
        status: PaymentStatus,
        idempotency_key: str,
        created_at: datetime,
        confirmed_at: datetime | None,
    ) -> None:
        super().__init__()
        if not provider:
            raise DomainError("Payment provider must not be empty")
        if len(provider) > _PROVIDER_MAX_LENGTH:
            raise DomainError(
                f"Payment provider must be at most {_PROVIDER_MAX_LENGTH} characters: "
                f"{len(provider)}"
            )
        if provider_ref is not None and len(provider_ref) > _PROVIDER_REF_MAX_LENGTH:
            raise DomainError(
                f"Payment provider_ref must be at most {_PROVIDER_REF_MAX_LENGTH} "
                f"characters: {len(provider_ref)}"
            )
        if msisdn_masked is not None and len(msisdn_masked) > _MSISDN_MASKED_MAX_LENGTH:
            raise DomainError(
                f"Payment msisdn_masked must be at most {_MSISDN_MASKED_MAX_LENGTH} "
                f"characters: {len(msisdn_masked)}"
            )
        _validate_idempotency_key(idempotency_key)
        self.id = id
        self.organization_id = organization_id
        self.invoice_id = invoice_id
        self.provider = provider
        self.provider_ref = provider_ref
        self.msisdn_masked = msisdn_masked
        self.amount = amount
        self.status = status
        self.idempotency_key = idempotency_key
        self.created_at = created_at
        self.confirmed_at = confirmed_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Payment) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def initiate(
        cls,
        *,
        id: PaymentId,
        organization_id: OrganizationId,
        invoice_id: InvoiceId,
        provider: str,
        msisdn_masked: str | None,
        amount: Money,
        idempotency_key: str,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Payment":
        """Starts `PENDING` (Phase-2 §20.3: `[*] --> Pending`). `PaymentInitiated` has no
        approved document naming it — this phase's own choice, flagged, matching the
        established "flagged, not silently assumed" convention every prior phase's own unnamed
        creation events already carry."""
        payment = cls(
            id=id,
            organization_id=organization_id,
            invoice_id=invoice_id,
            provider=provider,
            provider_ref=None,
            msisdn_masked=msisdn_masked,
            amount=amount,
            status=PaymentStatus.PENDING,
            idempotency_key=idempotency_key,
            created_at=clock.now(),
            confirmed_at=None,
        )
        payment._record(
            billing_events.payment_initiated(
                payment_id=str(id),
                organization_id=str(organization_id),
                invoice_id=str(invoice_id),
                provider=provider,
                amount=amount.amount,
                currency=amount.currency,
                occurred_at=payment.created_at,
                actor_id=actor_id,
            )
        )
        return payment

    def mark_processing(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Phase-2 §20.3: `Pending --> Processing: charge sent to provider`. Illegal-transition
        checking is not implemented (unlike `Trip`'s `RuleViolationError` machine) — no
        document describes Payment transitions as a *guarded* state machine the way Phase-2
        §6.2 explicitly draws one for `Trip`; this mirrors every other undocumented-transition-
        graph aggregate's "freely settable" precedent instead."""
        if self.status == PaymentStatus.PROCESSING:
            return
        self.status = PaymentStatus.PROCESSING
        self._record(
            billing_events.payment_processing(
                payment_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def mark_paid(
        self,
        *,
        provider_ref: str,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """`PaymentConfirmed` — API Contracts §13.2 names the wire event `payment.confirmed`
        (dot-notation; this file uses this codebase's own enforced PascalCase convention,
        `.claude/rules/naming.md`, the same translation every prior phase's event catalogue
        entries already apply)."""
        if len(provider_ref) > _PROVIDER_REF_MAX_LENGTH:
            raise DomainError(
                f"Payment provider_ref must be at most {_PROVIDER_REF_MAX_LENGTH} "
                f"characters: {len(provider_ref)}"
            )
        self.status = PaymentStatus.PAID
        self.provider_ref = provider_ref
        self.confirmed_at = clock.now()
        self._record(
            billing_events.payment_confirmed(
                payment_id=str(self.id),
                organization_id=str(self.organization_id),
                invoice_id=str(self.invoice_id),
                provider_ref=provider_ref,
                occurred_at=self.confirmed_at,
                actor_id=actor_id,
            )
        )

    def mark_failed(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`PaymentFailed` (API Contracts §13.2's `payment.failed`, PascalCase). Phase-2 §20.5
        (D4): a failed payment "never disables live GPS during active trips or safety
        notifications" — this aggregate has no reachable path to tracking/notifications at all,
        so that invariant is upheld by omission (this method touches only `Payment`'s own
        status), not by any check here."""
        self.status = PaymentStatus.FAILED
        self._record(
            billing_events.payment_failed(
                payment_id=str(self.id),
                organization_id=str(self.organization_id),
                invoice_id=str(self.invoice_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def mark_expired(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """Phase-2 §20.3: `Pending --> Expired: no action within window`. The "window" itself
        is Scheduler/reconciliation-job behavior with no documented cadence (LLD §11.2 names
        the job, not its timing) — out of this phase's scope per the task's own "Scheduler
        behavior that lacks documented execution details" exclusion; this method exists for the
        documented state transition, but nothing calls it automatically this phase."""
        if self.status == PaymentStatus.EXPIRED:
            return
        self.status = PaymentStatus.EXPIRED
        self._record(
            billing_events.payment_expired(
                payment_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class TransportFee(_AggregateRoot):
    """`transport_fees` (Database Design §8.5): "separate from subscription" — informational to
    parents, never gates safety or platform access by itself (§8.5's own closing line). No
    documented API surface at all this phase (confirmed by a dedicated documentation audit
    before this phase) — domain/application/infra complete, no HTTP route, the same "use-case
    exists, no approved endpoint yet" posture `Route.remove_stop`/`Trip.interrupt` establish.
    """

    def __init__(
        self,
        *,
        id: TransportFeeId,
        organization_id: OrganizationId,
        student_id: StudentId,
        period: str,
        amount: Money,
        status: TransportFeeStatus,
    ) -> None:
        super().__init__()
        if not period:
            raise DomainError("TransportFee period must not be empty")
        self.id = id
        self.organization_id = organization_id
        self.student_id = student_id
        self.period = period
        self.amount = amount
        self.status = status

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TransportFee) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def create(
        cls,
        *,
        id: TransportFeeId,
        organization_id: OrganizationId,
        student_id: StudentId,
        period: str,
        amount: Money,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "TransportFee":
        fee = cls(
            id=id,
            organization_id=organization_id,
            student_id=student_id,
            period=period,
            amount=amount,
            status=TransportFeeStatus.DUE,
        )
        fee._record(
            billing_events.transport_fee_created(
                transport_fee_id=str(id),
                organization_id=str(organization_id),
                student_id=str(student_id),
                period=period,
                amount=amount.amount,
                currency=amount.currency,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return fee

    def mark_paid(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == TransportFeeStatus.PAID:
            return
        self.status = TransportFeeStatus.PAID
        self._record(
            billing_events.transport_fee_paid(
                transport_fee_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def mark_overdue(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == TransportFeeStatus.OVERDUE:
            return
        self.status = TransportFeeStatus.OVERDUE
        self._record(
            billing_events.transport_fee_overdue(
                transport_fee_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def waive(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == TransportFeeStatus.WAIVED:
            return
        self.status = TransportFeeStatus.WAIVED
        self._record(
            billing_events.transport_fee_waived(
                transport_fee_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
