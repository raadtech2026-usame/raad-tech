"""Billing application service (Backend LLD §4.1/§4.3). One `BillingApplicationService` class
covering all five aggregates — this phase's own task scope names it singular
("BillingApplicationService"), unlike `transport_ops`'s established one-service-per-aggregate
split; followed literally rather than the sibling module's convention, since it's an explicit
instruction for this specific phase, not a silent choice.

**`payment_provider: PaymentProviderPort | None = None` — a deliberate, flagged deviation from
`tracking.application.services.TrackingApplicationService`'s "whole service stays unbound in DI
until its port exists" precedent.** Tracking's `LatestPositionPort` is load-bearing for nearly
every use-case that module has; `PaymentProviderPort` is load-bearing for exactly one method
here (`initiate_payment`'s actual charge step) out of roughly a dozen. Making the *entire*
service unreachable via DI would also make `list_plans`/`list_subscriptions`/`list_invoices` —
none of which touch a payment provider at all — unreachable for no reason tied to what they
actually need. Instead: the service is always constructible; `initiate_payment` persists the
`Payment` (a real, complete, testable action needing no provider) and only raises
`NotImplementedError` at the one specific point that would otherwise need to reach a live EVC
Plus endpoint — which this phase's own instructions explicitly forbid integrating with. This is
the same "fail loudly, don't fake" doctrine `core/di/bootstrap.py`'s own module docstring
already states, applied at method-granularity instead of service-granularity because the
granularity better matches where the real dependency actually sits.

**Cross-aggregate orchestration (`open_organization_subscription`, `handle_payment_callback`)**
lives here, not in the domain layer, for the identical reason `transport_ops`'s own
cross-aggregate flows do (`StudentAssignmentApplicationService.assign_student_to_route` loading
`Student`+`Route`): I/O (repository reads) is required, which is an application-layer concern by
this codebase's own established domain-purity rule (LLD §5.3).

**ADR-0016 (RAAD business model realignment): organization-only billing.** `renew_parent_
subscription` is replaced by `open_organization_subscription`, and `get_active_subscription_
for_subscriber` by `get_active_subscription_for_organization` — `Subscription` no longer has a
`subscriber_type`/`subscriber_id` at all (see `domain/entities.py`'s own updated docstring).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from raad.core.errors.exceptions import AuthorizationError, DomainError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import OffsetPage
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.billing.application.commands import (
    ActivatePlanCommand,
    CancelSubscriptionCommand,
    CreatePlanCommand,
    CreateTransportFeeCommand,
    DisablePlanCommand,
    ExpireSubscriptionCommand,
    InitiatePaymentCommand,
    IssueInvoiceCommand,
    MarkPaymentExpiredCommand,
    MarkTransportFeeOverdueCommand,
    MarkTransportFeePaidCommand,
    OpenOrganizationSubscriptionCommand,
    PaymentCallbackCommand,
    SuspendSubscriptionCommand,
    VoidInvoiceCommand,
    WaiveTransportFeeCommand,
)
from raad.modules.billing.application.ports import (
    BillingUnitOfWork,
    PaymentChargeRequest,
    PaymentProviderPort,
    WebhookEvent,
)
from raad.modules.billing.application.queries import (
    BillingStatsDTO,
    GetInvoiceByIdQuery,
    GetPaymentByIdQuery,
    GetPlanByIdQuery,
    GetSubscriptionByIdQuery,
    GetTransportFeeByIdQuery,
    InvoiceDTO,
    ListInvoicesQuery,
    ListPaymentsQuery,
    ListPlansQuery,
    ListSubscriptionsQuery,
    ListTransportFeesQuery,
    PaymentDTO,
    PlanDTO,
    SubscriptionDTO,
    TransportFeeDTO,
    invoice_to_dto,
    payment_to_dto,
    plan_to_dto,
    subscription_to_dto,
    transport_fee_to_dto,
)
from raad.modules.billing.application.validators import (
    ensure_invoice_exists,
    ensure_plan_exists,
    ensure_subscription_exists,
)
from raad.modules.billing.domain.entities import (
    Invoice,
    Payment,
    Plan,
    Subscription,
    TransportFee,
)
from raad.modules.billing.domain.value_objects import (
    BillingCycle,
    BillingScope,
    InvoiceId,
    Money,
    OrganizationId,
    PaymentId,
    PaymentStatus,
    PlanId,
    StudentId,
    SubscriptionId,
    SubscriptionStatus,
    TransportFeeId,
)

# Phase-2 §20.2 documents the renewal *workflow*, never a calendar-accurate period-length
# formula for `billing_cycle` - no `dateutil`-style calendar-month arithmetic is an approved
# dependency (`.claude/rules/workflow.md` #1/#2), so this uses fixed day-counts as a documented
# approximation, flagged rather than silently presented as calendar-exact.
_BILLING_CYCLE_DAYS = {
    BillingCycle.MONTHLY: 30,
    BillingCycle.QUARTERLY: 90,
    BillingCycle.ANNUAL: 365,
}


def _advance_period(start: datetime, cycle: BillingCycle) -> datetime:
    return start + timedelta(days=_BILLING_CYCLE_DAYS[cycle])


def _to_naive(value: datetime) -> datetime:
    """Normalizes to a naive `datetime` regardless of the caller's own tz-awareness — a real
    DB-loaded aggregate's timestamp fields are always naive (`infra/mappers.py`'s own
    `_to_naive_utc` already strips this on the way in), but a freshly-constructed in-memory
    aggregate (this method's own `self._clock.now()`, or any aggregate never round-tripped
    through a mapper — e.g. in-memory test fakes) may still be tz-aware; comparing the two
    without normalizing both sides raises `TypeError: can't compare offset-naive and
    offset-aware datetimes`. Used by `sweep_expired_subscriptions`/
    `reconcile_expired_payments`, the two scheduled-job methods that compare a freshly-computed
    `now`/`cutoff` against a loaded aggregate's own timestamp field."""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _enforce_own_organization(*, actor: Principal, organization_id: str) -> None:
    """ADR-0021: mirrors `iam.application.services._enforce_creation_scope`/`transport_ops.
    application.services._enforce_own_organization`'s identical shape/reasoning. Both
    `OpenOrganizationSubscriptionCommand`/`IssueInvoiceCommand` carry a client-supplied
    `organization_id` with no cross-aggregate reference to transitively validate it against (the
    loaded `Plan`/`Subscription` don't carry an owning organization to compare against —
    `Plan` has none at all, and nothing here checks the loaded `Subscription.organization_id`
    against `command.organization_id` on `issue_invoice` either) — a real write-side IDOR the
    repository-layer scope fix alone cannot close, the same reasoning that already applies to
    `transport_ops.EnrollStudentCommand`/`CreateRouteCommand`. Neither command has an approved
    HTTP route yet (`api/routers.py`'s module docstring) so this isn't reachable through
    `require_permission` today, but the check is added now anyway rather than left for whoever
    wires the route later to remember — the same "use-case exists, no approved endpoint yet, but
    still built correctly" posture this module already applies to `handle_payment_callback`.
    `initiate_payment` needs no equivalent check: it has no client-supplied `organization_id` at
    all — `Payment.organization_id` is always taken from the already-scoped `Invoice` it loads
    (`ensure_invoice_exists`), so a tenant-scoped caller can never even reference another
    organization's invoice to begin with."""
    if actor.role is not Role.ORG_ADMIN:
        return
    if organization_id != actor.org_id:
        raise AuthorizationError(
            "org_admin may only open a subscription or issue an invoice within their own "
            "organization."
        )


class BillingApplicationService:
    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        payment_provider: PaymentProviderPort | None = None,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        self._payment_provider = payment_provider

    # --- Plan --------------------------------------------------------------------------

    async def create_plan(
        self, command: CreatePlanCommand, *, uow: BillingUnitOfWork
    ) -> PlanDTO:
        async with uow:
            plan = Plan.create(
                id=PlanId(self._id_generator.new_id()),
                name=command.name,
                billing_scope=BillingScope(command.billing_scope),
                price=Money(command.amount, command.currency),
                billing_cycle=BillingCycle(command.billing_cycle),
                vehicle_limit=command.vehicle_limit,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.plans.add(plan)
            uow.record_events(plan.pull_domain_events())
            await uow.commit()
            return plan_to_dto(plan)

    async def activate_plan(
        self, command: ActivatePlanCommand, *, uow: BillingUnitOfWork
    ) -> PlanDTO:
        async with uow:
            plan = await self._get_plan_or_raise(uow, command.plan_id)
            plan.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(plan.pull_domain_events())
            await uow.commit()
            return plan_to_dto(plan)

    async def disable_plan(
        self, command: DisablePlanCommand, *, uow: BillingUnitOfWork
    ) -> PlanDTO:
        async with uow:
            plan = await self._get_plan_or_raise(uow, command.plan_id)
            plan.disable(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(plan.pull_domain_events())
            await uow.commit()
            return plan_to_dto(plan)

    async def get_plan_by_id(
        self, query: GetPlanByIdQuery, *, uow: BillingUnitOfWork
    ) -> PlanDTO:
        async with uow:
            plan = await self._get_plan_or_raise(uow, query.plan_id)
            return plan_to_dto(plan)

    async def list_plans(
        self, query: ListPlansQuery, *, uow: BillingUnitOfWork
    ) -> OffsetPage[PlanDTO]:
        """Backs `GET /billing/plans` (API Contracts §4.7/§7/§8) - pagination/filtering/sorting
        added under the Pagination/Filtering/Sorting phase, on top of the Backend Stabilization
        phase's original `list_all`-backed addition (still used by `list_plans`'s own sibling
        use-cases that need every plan unfiltered, e.g. `open_organization_subscription`'s
        `ensure_plan_exists` precondition). Mirrors `organization.application.services.
        OrganizationApplicationService.list_organizations`'s identical shape."""
        async with uow:
            page = await uow.plans.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[plan_to_dto(plan) for plan in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    @staticmethod
    async def _get_plan_or_raise(uow: BillingUnitOfWork, plan_id: str) -> Plan:
        plan = await uow.plans.get(PlanId(plan_id))
        if plan is None:
            raise NotFoundError(f"Plan {plan_id} not found.")
        return plan

    # --- Subscription --------------------------------------------------------------------

    async def open_organization_subscription(
        self, command: OpenOrganizationSubscriptionCommand, *, uow: BillingUnitOfWork
    ) -> InvoiceDTO:
        """ADR-0016: replaces the former `renew_parent_subscription` — RAAD bills Organizations
        only. Orchestrated per Phase-2 §20.2's documented sequence up through invoice creation
        (the charge step is a separate call, `initiate_payment`, matching the two documented,
        distinct API routes). Finds an existing non-terminal subscription for this organization
        first (`get_active_by_organization`) rather than always opening a new one — see that
        repository method's own docstring for the flagged "active" reading."""
        _enforce_own_organization(
            actor=command.actor, organization_id=command.organization_id
        )
        async with uow:
            plan = await ensure_plan_exists(uow, PlanId(command.plan_id))

            organization_id = OrganizationId(command.organization_id)
            subscription = await uow.subscriptions.get_active_by_organization(
                organization_id
            )
            if subscription is None:
                subscription = Subscription.open(
                    id=SubscriptionId(self._id_generator.new_id()),
                    organization_id=organization_id,
                    plan_id=plan.id,
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                )
                uow.subscriptions.add(subscription)

            period_start = subscription.current_period_end or self._clock.now()
            period_end = _advance_period(period_start, plan.billing_cycle)

            invoice = Invoice.issue(
                id=InvoiceId(self._id_generator.new_id()),
                organization_id=organization_id,
                subscription_id=subscription.id,
                amount=plan.price,
                period_start=period_start.date(),
                period_end=period_end.date(),
                due_at=None,  # no documented due-window - see entities.py's Invoice docstring
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.invoices.add(invoice)

            uow.record_events(subscription.pull_domain_events())
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
            return invoice_to_dto(invoice)

    async def expire_subscription(
        self, command: ExpireSubscriptionCommand, *, uow: BillingUnitOfWork
    ) -> SubscriptionDTO:
        async with uow:
            subscription = await ensure_subscription_exists(
                uow, SubscriptionId(command.subscription_id)
            )
            subscription.expire(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()
            return subscription_to_dto(subscription)

    async def sweep_expired_subscriptions(
        self, *, actor_id: str = "system", uow: BillingUnitOfWork
    ) -> int:
        """The subscription-status-sweep scheduled job's own entry point (Backend LLD §11.2's
        "Scheduler" row: "subscription-status sweeps"; no approved HTTP route). Expires every
        non-terminal subscription (`trial`/`active`/`suspended`) whose `current_period_end` has
        passed — `Subscription.expire()` already exists and is idempotent (Phase 15); this only
        adds the bulk-scan orchestration no single-subscription command could do. Returns the
        number of subscriptions expired. `actor_id="system"` (a plain string, not a synthesized
        `Principal`) since this method takes no `Command`/`actor: Principal` the way every
        HTTP-reachable use-case does — see `modules/notifications/events/subscribers.py`'s own
        `SYSTEM_PRINCIPAL` docstring for the identical gap this sidesteps by not requiring a
        `Principal` at all for a method with no HTTP-facing counterpart."""
        async with uow:
            now = self._clock.now().replace(tzinfo=None)
            subscriptions = await uow.subscriptions.list_all()
            expired_count = 0
            for subscription in subscriptions:
                if subscription.status not in (
                    SubscriptionStatus.TRIAL,
                    SubscriptionStatus.ACTIVE,
                    SubscriptionStatus.SUSPENDED,
                ):
                    continue
                if subscription.current_period_end is None or _to_naive(
                    subscription.current_period_end
                ) >= now:
                    continue
                subscription.expire(clock=self._clock, actor_id=actor_id)
                uow.record_events(subscription.pull_domain_events())
                expired_count += 1
            if expired_count:
                await uow.commit()
            return expired_count

    async def suspend_subscription(
        self, command: SuspendSubscriptionCommand, *, uow: BillingUnitOfWork
    ) -> SubscriptionDTO:
        async with uow:
            subscription = await ensure_subscription_exists(
                uow, SubscriptionId(command.subscription_id)
            )
            subscription.suspend(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()
            return subscription_to_dto(subscription)

    async def cancel_subscription(
        self, command: CancelSubscriptionCommand, *, uow: BillingUnitOfWork
    ) -> SubscriptionDTO:
        async with uow:
            subscription = await ensure_subscription_exists(
                uow, SubscriptionId(command.subscription_id)
            )
            subscription.cancel(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()
            return subscription_to_dto(subscription)

    async def get_subscription_by_id(
        self, query: GetSubscriptionByIdQuery, *, uow: BillingUnitOfWork
    ) -> SubscriptionDTO:
        async with uow:
            subscription = await ensure_subscription_exists(
                uow, SubscriptionId(query.subscription_id)
            )
            return subscription_to_dto(subscription)

    async def list_subscriptions(
        self, query: ListSubscriptionsQuery, *, uow: BillingUnitOfWork
    ) -> OffsetPage[SubscriptionDTO]:
        """Backs `GET /billing/subscriptions` (API Contracts §4.7/§7/§8) - pagination/
        filtering/sorting added under the Pagination/Filtering/Sorting phase."""
        async with uow:
            page = await uow.subscriptions.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[subscription_to_dto(s) for s in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    async def get_billing_stats(
        self,
        *,
        expiring_window_start: datetime,
        expiring_window_end: datetime,
        revenue_window_start: datetime,
        revenue_window_end: datetime,
        uow: BillingUnitOfWork,
    ) -> BillingStatsDTO:
        """ADR-0020: "Subscription/Billing Status" + "Expiring Organizations" + "Revenue" KPIs,
        backing `platform_audit.PlatformStatsApplicationService`. All four boundaries are
        resolved by the caller once, for the whole composed response — matching every other
        new stats method this ADR adds (`OrganizationApplicationService.get_organization_stats`'s
        own docstring gives the full "policy resolved by caller" reasoning)."""
        async with uow:
            subscription_by_status = await uow.subscriptions.count_by_status()
            expiring_soon = await uow.subscriptions.count_expiring_between(
                start=expiring_window_start, end=expiring_window_end
            )
            revenue = await uow.invoices.sum_paid_amount_between(
                start=revenue_window_start, end=revenue_window_end
            )
            return BillingStatsDTO(
                subscription_by_status=subscription_by_status,
                expiring_soon=expiring_soon,
                revenue=revenue,
            )

    async def get_active_subscription_for_organization(
        self, organization_id: str, *, uow: BillingUnitOfWork
    ) -> SubscriptionDTO | None:
        """Application-layer read path over `SubscriptionRepository.get_active_by_organization`
        (`domain/repositories.py`'s own flagged "not EXPIRED/CANCELLED" reading). Backs CR-1
        enforcement (`interfaces/http/policy_guards.resolve_cr1_decision`), which needs the
        organization's current `subscription_state` — the *only* subscriber CR-1 evaluates now
        (ADR-0016 amends ADR-0006: no more per-parent subscription branch)."""
        async with uow:
            subscription = await uow.subscriptions.get_active_by_organization(
                OrganizationId(organization_id)
            )
            return subscription_to_dto(subscription) if subscription is not None else None

    # --- Invoice ---------------------------------------------------------------------------

    async def issue_invoice(
        self, command: IssueInvoiceCommand, *, uow: BillingUnitOfWork
    ) -> InvoiceDTO:
        """Standalone issuance, independent of `open_organization_subscription`'s own inline
        issuance — kept for completeness of the documented `Invoice` model/lifecycle
        (this phase's own Business Rules scope) even though `open_organization_subscription` is
        the only reachable-at-this-layer path that actually produces one in practice."""
        _enforce_own_organization(
            actor=command.actor, organization_id=command.organization_id
        )
        async with uow:
            subscription = await ensure_subscription_exists(
                uow, SubscriptionId(command.subscription_id)
            )
            invoice = Invoice.issue(
                id=InvoiceId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                subscription_id=subscription.id,
                amount=Money(command.amount, command.currency),
                period_start=command.period_start,
                period_end=command.period_end,
                due_at=command.due_at,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.invoices.add(invoice)
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
            return invoice_to_dto(invoice)

    async def void_invoice(
        self, command: VoidInvoiceCommand, *, uow: BillingUnitOfWork
    ) -> InvoiceDTO:
        async with uow:
            invoice = await ensure_invoice_exists(uow, InvoiceId(command.invoice_id))
            invoice.void(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
            return invoice_to_dto(invoice)

    async def get_invoice_by_id(
        self, query: GetInvoiceByIdQuery, *, uow: BillingUnitOfWork
    ) -> InvoiceDTO:
        async with uow:
            invoice = await ensure_invoice_exists(uow, InvoiceId(query.invoice_id))
            return invoice_to_dto(invoice)

    async def list_invoices(
        self, query: ListInvoicesQuery, *, uow: BillingUnitOfWork
    ) -> OffsetPage[InvoiceDTO]:
        """Backs `GET /billing/invoices` (API Contracts §4.7/§7/§8) - pagination/filtering/
        sorting added under the Pagination/Filtering/Sorting phase."""
        async with uow:
            page = await uow.invoices.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[invoice_to_dto(invoice) for invoice in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    # --- Payment ---------------------------------------------------------------------------

    async def initiate_payment(
        self, command: InitiatePaymentCommand, *, uow: BillingUnitOfWork
    ) -> PaymentDTO:
        """`POST /billing/payments` (API Contracts §4.7). Idempotency (API Contracts §12: "a
        repeat with the same key returns the original result") is a find-or-return-existing
        check, not a `ConflictError` guard — see `validators.py`'s module docstring for why no
        `ensure_*_available` function exists for this. The charge step
        (`self._payment_provider.charge(...)`) is attempted only after the `Payment` row is
        durably persisted as `PENDING` — see this class's own module docstring for why a
        missing provider raises `NotImplementedError` at exactly this point rather than making
        the whole service unreachable.

        **ADR-0022**: the charge result now has three outcomes, not one. `"succeeded"` (a card
        charge is frequently synchronously final) marks the payment `PAID` immediately, running
        the same invoice/subscription-renewal orchestration `handle_payment_callback` runs for
        a `"paid"` webhook — both paths converge on the identical `_apply_paid_side_effects`
        helper so the two can never drift. `"pending"` marks `PROCESSING`, awaiting the
        provider's webhook (mobile-money's own documented shape). `"failed"` marks `FAILED`
        with `PaymentChargeResult.failure_reason` recorded immediately, rather than only ever
        learning about a failure from a callback that a synchronously-rejected charge will
        never receive."""
        async with uow:
            existing = await uow.payments.get_by_idempotency_key(
                command.idempotency_key
            )
            if existing is not None:
                return payment_to_dto(existing)

            invoice = await ensure_invoice_exists(uow, InvoiceId(command.invoice_id))

            payment = Payment.initiate(
                id=PaymentId(self._id_generator.new_id()),
                organization_id=invoice.organization_id,
                invoice_id=invoice.id,
                provider=command.method,
                msisdn_masked=_mask_msisdn(command.msisdn),
                amount=Money(command.amount, command.currency),
                idempotency_key=command.idempotency_key,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.payments.add(payment)
            uow.record_events(payment.pull_domain_events())
            await uow.commit()

        if self._payment_provider is None:
            raise NotImplementedError(
                "No PaymentProviderPort is bound - RAAD_PAYMENT__PROVIDER is not configured "
                "with valid credentials this deployment. The Payment row above was persisted "
                "as PENDING; charging it requires a bound adapter (see infra/adapters.py)."
            )

        result = await self._payment_provider.charge(
            PaymentChargeRequest(
                amount=payment.amount,
                reference=str(payment.id),
                msisdn=command.msisdn,
                payment_method_token=command.payment_method_token,
            )
        )

        async with uow:
            payment = await self._get_payment_or_raise(uow, str(payment.id))
            if result.status == "succeeded":
                await self._apply_paid_side_effects(
                    uow,
                    payment=payment,
                    provider_ref=result.provider_ref,
                    actor_id=command.actor.user_id,
                )
            elif result.status == "failed":
                payment.mark_failed(
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                    reason=result.failure_reason,
                )
                uow.record_events(payment.pull_domain_events())
            else:
                payment.mark_processing(clock=self._clock, actor_id=command.actor.user_id)
                payment.provider_ref = result.provider_ref
                uow.record_events(payment.pull_domain_events())
            await uow.commit()
            return payment_to_dto(payment)

    async def _apply_paid_side_effects(
        self, uow: BillingUnitOfWork, *, payment: Payment, provider_ref: str, actor_id: str | None
    ) -> None:
        """Shared by `initiate_payment`'s synchronous-success path and
        `handle_payment_callback`'s asynchronous-webhook path (ADR-0022) — both mean the exact
        same thing (a payment is now paid) and must run the exact same orchestration (Phase-2
        §20.2: "Mark Invoice PAID, extend Subscription"), so there is exactly one place this
        logic lives, not two that could drift. Caller is responsible for the idempotency guard
        (`Payment.mark_paid` is itself a same-state no-op, but the caller decides whether to
        even reach this method) and for committing."""
        payment.mark_paid(provider_ref=provider_ref, clock=self._clock, actor_id=actor_id)
        invoice = await ensure_invoice_exists(uow, payment.invoice_id)
        invoice.mark_paid(clock=self._clock, actor_id=actor_id)
        subscription = await ensure_subscription_exists(uow, invoice.subscription_id)
        plan = await ensure_plan_exists(uow, subscription.plan_id)
        period_start = subscription.current_period_end or self._clock.now()
        period_end = _advance_period(period_start, plan.billing_cycle)
        subscription.renew(
            period_start=period_start, period_end=period_end, clock=self._clock, actor_id=actor_id
        )
        uow.record_events(payment.pull_domain_events())
        uow.record_events(invoice.pull_domain_events())
        uow.record_events(subscription.pull_domain_events())

    async def handle_payment_callback(
        self, command: PaymentCallbackCommand, *, uow: BillingUnitOfWork
    ) -> PaymentDTO:
        """`POST /billing/payments/callback` (API Contracts §4.7/§12). On success: marks the
        `Payment` paid, then orchestrates the two further documented side effects (Phase-2
        §20.2: "Mark Invoice PAID, extend Subscription") in the same transaction. On failure:
        marks only the `Payment` failed — see `entities.py`'s module docstring for the resolved
        Invoice-vs-Payment "FAILED" conflict; the invoice is deliberately left untouched.

        **ADR-0022: idempotent against a replayed webhook delivery**, belt-and-suspenders with
        `Payment.mark_paid`/`mark_failed`'s own same-state guards — short-circuits here, before
        touching `Invoice`/`Subscription` at all, if the payment is already in a terminal state,
        so a provider's retry of an already-processed callback does no work and never re-advances
        a subscription's billing period a second time."""
        async with uow:
            payment = await self._get_payment_or_raise(uow, command.payment_id)

            if payment.status in (PaymentStatus.PAID, PaymentStatus.FAILED):
                return payment_to_dto(payment)

            if command.status == "paid":
                if command.provider_ref is None:
                    raise DomainError(
                        "PaymentCallbackCommand.provider_ref is required when status='paid'."
                    )
                await self._apply_paid_side_effects(
                    uow,
                    payment=payment,
                    provider_ref=command.provider_ref,
                    actor_id=command.actor.user_id,
                )
            elif command.status == "failed":
                payment.mark_failed(
                    clock=self._clock,
                    actor_id=command.actor.user_id,
                    reason=command.failure_reason,
                )
                uow.record_events(payment.pull_domain_events())
            else:
                raise DomainError(
                    f"Unsupported PaymentCallbackCommand.status: {command.status!r} "
                    "(expected 'paid' or 'failed')."
                )

            await uow.commit()
            return payment_to_dto(payment)

    async def handle_webhook_event(
        self, event: WebhookEvent, *, provider: str, uow: BillingUnitOfWork, actor: Principal
    ) -> PaymentDTO:
        """`POST /billing/payments/callback` (ADR-0022) — the actual entry point the route
        calls, keeping `routers.py` to its own "call exactly one `BillingApplicationService`
        method" convention. Resolves the webhook's own `WebhookEvent.provider_ref` (all a
        provider's payload ever names) back to this system's internal `Payment.id` via
        `get_by_provider_ref` (`ux_payments__provider_provider_ref`'s own defense-in-depth
        backstop), then delegates to `handle_payment_callback` — this method owns only the
        provider_ref -> payment_id resolution, not the callback orchestration itself."""
        async with uow:
            payment = await uow.payments.get_by_provider_ref(provider, event.provider_ref)
            if payment is None:
                raise NotFoundError(
                    f"No payment found for provider={provider!r} provider_ref="
                    f"{event.provider_ref!r}."
                )
            payment_id = str(payment.id)

        return await self.handle_payment_callback(
            PaymentCallbackCommand(
                payment_id=payment_id,
                status=event.status,
                provider_ref=event.provider_ref,
                actor=actor,
                failure_reason=event.failure_reason,
            ),
            uow=uow,
        )

    async def mark_payment_expired(
        self, command: MarkPaymentExpiredCommand, *, uow: BillingUnitOfWork
    ) -> PaymentDTO:
        """No approved HTTP route - see `commands.py`'s `MarkPaymentExpiredCommand`
        docstring."""
        async with uow:
            payment = await self._get_payment_or_raise(uow, command.payment_id)
            payment.mark_expired(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(payment.pull_domain_events())
            await uow.commit()
            return payment_to_dto(payment)

    async def reconcile_expired_payments(
        self, *, timeout_minutes: int, actor_id: str = "system", uow: BillingUnitOfWork
    ) -> int:
        """The payment-reconciliation scheduled job's own entry point (Backend LLD §11.2's
        "Scheduler" row: "payment reconciliation"; Phase-2 §20.3: `Pending --> Expired: no
        action within window`). Expires every `pending`/`processing` payment older than
        `timeout_minutes` — `Payment.mark_expired()` already exists (Phase 15); this adds only
        the bulk-scan orchestration. Returns the number of payments expired. Same
        `actor_id="system"` plain-string posture as `sweep_expired_subscriptions` above."""
        async with uow:
            now = self._clock.now().replace(tzinfo=None)
            cutoff = now - timedelta(minutes=timeout_minutes)
            payments = await uow.payments.list_all()
            expired_count = 0
            for payment in payments:
                if payment.status not in (PaymentStatus.PENDING, PaymentStatus.PROCESSING):
                    continue
                if _to_naive(payment.created_at) >= cutoff:
                    continue
                payment.mark_expired(clock=self._clock, actor_id=actor_id)
                uow.record_events(payment.pull_domain_events())
                expired_count += 1
            if expired_count:
                await uow.commit()
            return expired_count

    async def get_payment_by_id(
        self, query: GetPaymentByIdQuery, *, uow: BillingUnitOfWork
    ) -> PaymentDTO:
        async with uow:
            payment = await self._get_payment_or_raise(uow, query.payment_id)
            return payment_to_dto(payment)

    async def list_payments(
        self, query: ListPaymentsQuery, *, uow: BillingUnitOfWork
    ) -> OffsetPage[PaymentDTO]:
        """Backs `GET /billing/payments` (ADR-0022 - "payment history," previously no list
        route existed at all). Same paginated/filtered/sorted shape `list_invoices` already
        establishes."""
        async with uow:
            page = await uow.payments.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[payment_to_dto(payment) for payment in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    @staticmethod
    async def _get_payment_or_raise(uow: BillingUnitOfWork, payment_id: str) -> Payment:
        payment = await uow.payments.get(PaymentId(payment_id))
        if payment is None:
            raise NotFoundError(f"Payment {payment_id} not found.")
        return payment

    # --- TransportFee ------------------------------------------------------------------------

    async def create_transport_fee(
        self, command: CreateTransportFeeCommand, *, uow: BillingUnitOfWork
    ) -> TransportFeeDTO:
        async with uow:
            fee = TransportFee.create(
                id=TransportFeeId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                student_id=StudentId(command.student_id),
                period=command.period,
                amount=Money(command.amount, command.currency),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.transport_fees.add(fee)
            uow.record_events(fee.pull_domain_events())
            await uow.commit()
            return transport_fee_to_dto(fee)

    async def mark_transport_fee_paid(
        self, command: MarkTransportFeePaidCommand, *, uow: BillingUnitOfWork
    ) -> TransportFeeDTO:
        async with uow:
            fee = await self._get_transport_fee_or_raise(
                uow, command.transport_fee_id
            )
            fee.mark_paid(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(fee.pull_domain_events())
            await uow.commit()
            return transport_fee_to_dto(fee)

    async def mark_transport_fee_overdue(
        self, command: MarkTransportFeeOverdueCommand, *, uow: BillingUnitOfWork
    ) -> TransportFeeDTO:
        async with uow:
            fee = await self._get_transport_fee_or_raise(
                uow, command.transport_fee_id
            )
            fee.mark_overdue(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(fee.pull_domain_events())
            await uow.commit()
            return transport_fee_to_dto(fee)

    async def waive_transport_fee(
        self, command: WaiveTransportFeeCommand, *, uow: BillingUnitOfWork
    ) -> TransportFeeDTO:
        async with uow:
            fee = await self._get_transport_fee_or_raise(
                uow, command.transport_fee_id
            )
            fee.waive(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(fee.pull_domain_events())
            await uow.commit()
            return transport_fee_to_dto(fee)

    async def get_transport_fee_by_id(
        self, query: GetTransportFeeByIdQuery, *, uow: BillingUnitOfWork
    ) -> TransportFeeDTO:
        async with uow:
            fee = await self._get_transport_fee_or_raise(uow, query.transport_fee_id)
            return transport_fee_to_dto(fee)

    async def list_transport_fees(
        self, query: ListTransportFeesQuery, *, uow: BillingUnitOfWork
    ) -> list[TransportFeeDTO]:
        async with uow:
            fees = await uow.transport_fees.list_all()
            return [transport_fee_to_dto(fee) for fee in fees]

    @staticmethod
    async def _get_transport_fee_or_raise(
        uow: BillingUnitOfWork, transport_fee_id: str
    ) -> TransportFee:
        fee = await uow.transport_fees.get(TransportFeeId(transport_fee_id))
        if fee is None:
            raise NotFoundError(f"TransportFee {transport_fee_id} not found.")
        return fee


def _mask_msisdn(msisdn: str | None) -> str | None:
    """API Contracts §4.7's own payment-request example shows a masked msisdn in the
    *response* context (`"+2526••••••"`) — no exact masking algorithm is documented (how many
    leading digits stay visible). Mirrors the example's own visible-prefix shape: keep the
    first 4 characters, mask the rest, flagged as an inferred-from-example algorithm, not a
    specified one. `None` (ADR-0022: a card payment carries no msisdn at all) passes through
    unchanged rather than being coerced into a fabricated masked value."""
    if msisdn is None:
        return None
    visible = msisdn[:4]
    return visible + "•" * max(len(msisdn) - 4, 0)
