"""Application-layer tests for `billing`'s `BillingApplicationService` (Phase 15). Stdlib
`unittest` — no `pytest` (not an approved dependency), mirroring
`test_transport_ops_trip_application.py`'s exact structure. Uses in-memory fakes for all five
repositories bundled onto one fake `BillingUnitOfWork`, plus a fake `PaymentProviderPort` — no
SQLAlchemy, no FastAPI, no real database.

Covers: Plan CRUD-lite, `open_organization_subscription`'s open-or-reuse orchestration, Subscription
status transitions, Invoice issuance/void, Payment idempotency (find-or-return), the documented
"no provider bound -> NotImplementedError at the charge step, Payment already persisted as
PENDING" behavior, the successful-charge path with a bound fake provider,
`handle_payment_callback`'s paid/failed cascades (paid: Invoice.mark_paid + Subscription.renew in
the same transaction; failed: only Payment mutated, Invoice left untouched — the resolved
Invoice-vs-Payment "FAILED" conflict).
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from raad.core.errors.exceptions import (
    AuthorizationError,
    ConflictError,
    DomainError,
    NotFoundError,
    RuleViolationError,
)
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.billing.application.commands import (
    ActivatePlanCommand,
    ActivateSubscriptionCommand,
    CancelSubscriptionCommand,
    ChangeSubscriptionPlanCommand,
    CreatePlanCommand,
    DeletePlanCommand,
    DisablePlanCommand,
    ExpireSubscriptionCommand,
    InitiatePaymentCommand,
    IssueInvoiceCommand,
    MarkPaymentExpiredCommand,
    PaymentCallbackCommand,
    OpenOrganizationSubscriptionCommand,
    RecordManualSubscriptionPaymentCommand,
    SuspendSubscriptionCommand,
    VoidInvoiceCommand,
)
from raad.modules.billing.application.ports import (
    BillingUnitOfWork,
    PaymentChargeRequest,
    PaymentChargeResult,
    PaymentProviderPort,
    WebhookEvent,
)
from raad.modules.billing.application.queries import (
    GetInvoiceByIdQuery,
    GetPaymentByIdQuery,
    GetPlanByIdQuery,
    GetSubscriptionByIdQuery,
    ListInvoicesQuery,
    ListPaymentsQuery,
    ListPlansQuery,
    ListSubscriptionsQuery,
)
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.billing.domain.entities import (
    Invoice,
    Payment,
    Plan,
    Subscription,
)
from raad.modules.billing.domain.repositories import (
    InvoiceRepository,
    PaymentRepository,
    PlanRepository,
    SubscriptionRepository,
)
from raad.modules.billing.domain.value_objects import (
    InvoiceId,
    InvoiceStatus,
    Money,
    OrganizationId,
    PaymentId,
    PlanId,
    SubscriptionId,
    SubscriptionStatus,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3OT"
NON_EXISTENT_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc))


class SequentialIdGenerator(IdGenerator):
    """26-char, valid-Crockford-Base32 ULID-shaped ids, unique per call — mirrors
    `test_transport_ops_trip_application.py`'s identical helper exactly."""

    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"  # 20 chars

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


def _field_text(item: object, field_name: str) -> str:
    value = getattr(item, field_name)
    value = getattr(value, "value", value)
    return "" if value is None else str(value)


def _matches_filter(item: object, condition: FilterCondition) -> bool:
    text = _field_text(item, condition.field)
    if condition.op == "eq":
        return text == condition.value
    if condition.op == "in":
        return text in {part.strip() for part in condition.value.split(",")}
    if condition.op == "gte":
        return text >= condition.value
    if condition.op == "lte":
        return text <= condition.value
    if condition.op == "gt":
        return text > condition.value
    if condition.op == "lt":
        return text < condition.value
    return True


def _paginate_in_memory(
    items: list,
    page_request: OffsetPageRequest,
    *,
    sort: list[SortSpec],
    filters: list[FilterCondition],
    search: str | None,
    search_field: str = "name",
) -> OffsetPage:
    """Shared in-memory equivalent of `SqlAlchemyRepositoryBase.list_page` (`core/db/
    repository.py`), for fake repositories that can't run real SQL — duplicated from
    `test_organization_application.py`'s identical helper, mirroring this codebase's own
    established "duplicated per module's own test file" precedent (e.g. domain-event
    buffering)."""
    for condition in filters:
        items = [item for item in items if _matches_filter(item, condition)]
    if search:
        items = [
            item
            for item in items
            if search.lower() in _field_text(item, search_field).lower()
        ]
    for spec in reversed(sort):
        items = sorted(
            items, key=lambda item: _field_text(item, spec.field), reverse=spec.descending
        )
    if not sort:
        items = sorted(items, key=lambda item: str(item.id))
    total = len(items)
    start = page_request.offset
    end = start + page_request.page_size
    return OffsetPage(
        data=items[start:end], total=total, page=page_request.page, page_size=page_request.page_size
    )


def make_actor(org_id: str = VALID_ORG_ULID) -> Principal:
    return Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=org_id)


def make_founder_actor() -> Principal:
    return Principal(user_id="founder-1", role=Role.FOUNDER, org_id=None)


class InMemoryPlanRepository(PlanRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Plan] = {}

    async def get(self, plan_id: PlanId) -> Plan | None:
        return self.by_id.get(str(plan_id))

    def add(self, plan: Plan) -> None:
        self.by_id[str(plan.id)] = plan

    async def list_all(self) -> list[Plan]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Plan]:
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )

    async def delete(self, plan: Plan) -> None:
        self.by_id.pop(str(plan.id), None)


class InMemorySubscriptionRepository(SubscriptionRepository):
    def __init__(self, *, plans: "InMemoryPlanRepository | None" = None) -> None:
        self.by_id: dict[str, Subscription] = {}
        # Only needed for `count_active_by_billing_cycle`'s JOIN-equivalent lookup — optional so
        # every pre-existing call site that doesn't care about billing-cycle stats is unaffected.
        self._plans = plans

    async def get(self, subscription_id: SubscriptionId) -> Subscription | None:
        return self.by_id.get(str(subscription_id))

    def add(self, subscription: Subscription) -> None:
        self.by_id[str(subscription.id)] = subscription

    async def list_all(self) -> list[Subscription]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Subscription]:
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )

    async def get_active_by_organization(
        self, organization_id: OrganizationId
    ) -> Subscription | None:
        return next(
            (
                s
                for s in self.by_id.values()
                if str(s.organization_id) == str(organization_id)
                # ADR-0039: mirrors the real repository's widened IN-list exactly, so a
                # past_due/grace_period organization is found here too and this fake cannot
                # quietly disagree with production about whether a duplicate would be opened.
                and s.status.value
                in ("trial", "active", "suspended", "past_due", "grace_period")
            ),
            None,
        )

    async def get_current_by_organization(
        self, organization_id: OrganizationId
    ) -> Subscription | None:
        """ADR-0039 — every status, newest first, hiding nothing (see the domain interface's
        own docstring for why enforcement must not use `get_active_by_organization`)."""
        matches = [
            s
            for s in self.by_id.values()
            if str(s.organization_id) == str(organization_id)
        ]
        matches.sort(key=lambda s: s.created_at, reverse=True)
        return matches[0] if matches else None

    async def list_lifecycle_candidates(self) -> list[Subscription]:
        return [
            s
            for s in self.by_id.values()
            if s.status.value in ("trial", "active", "past_due", "grace_period")
        ]

    async def count_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for sub in self.by_id.values():
            counts[sub.status.value] = counts.get(sub.status.value, 0) + 1
        return counts

    async def count_expiring_between(self, *, start, end) -> int:
        return sum(
            1
            for sub in self.by_id.values()
            if sub.status.value in ("trial", "active", "suspended")
            and sub.current_period_end is not None
            and start <= sub.current_period_end < end
        )

    async def exists_for_plan(self, plan_id) -> bool:
        return any(str(sub.plan_id) == str(plan_id) for sub in self.by_id.values())

    async def count_active_by_billing_cycle(self) -> dict[str, int]:
        assert self._plans is not None, "InMemorySubscriptionRepository needs plans= for this"
        counts: dict[str, int] = {}
        for sub in self.by_id.values():
            if sub.status.value not in ("trial", "active", "past_due", "grace_period"):
                continue
            plan = self._plans.by_id.get(str(sub.plan_id))
            if plan is None:
                continue
            cycle = plan.billing_cycle.value
            counts[cycle] = counts.get(cycle, 0) + 1
        return counts


class InMemoryInvoiceRepository(InvoiceRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Invoice] = {}

    async def get(self, invoice_id: InvoiceId) -> Invoice | None:
        return self.by_id.get(str(invoice_id))

    def add(self, invoice: Invoice) -> None:
        self.by_id[str(invoice.id)] = invoice

    async def list_all(self) -> list[Invoice]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Invoice]:
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
            search_field="number",
        )

    async def has_unpaid_for_subscription(
        self, subscription_id: SubscriptionId
    ) -> bool:
        """ADR-0039. `void` counts as settled, exactly like the real repository — an invoice
        RAAD itself withdrew must not hold a tenant past-due."""
        return any(
            str(i.subscription_id) == str(subscription_id)
            and i.status.value not in ("paid", "void")
            for i in self.by_id.values()
        )

    async def exists_for_period(
        self, subscription_id: SubscriptionId, *, period_start, period_end
    ) -> bool:
        return any(
            str(i.subscription_id) == str(subscription_id)
            and i.period_start == period_start
            and i.period_end == period_end
            for i in self.by_id.values()
        )

    async def latest_paid_period_end(self, subscription_id: SubscriptionId):
        ends = [
            i.period_end
            for i in self.by_id.values()
            if str(i.subscription_id) == str(subscription_id) and i.status.value == "paid"
        ]
        return max(ends) if ends else None

    async def sum_paid_amount_between(self, *, start, end) -> float:
        return sum(
            invoice.amount.amount
            for invoice in self.by_id.values()
            if invoice.status.value == "paid"
            and invoice.paid_at is not None
            and start <= invoice.paid_at < end
        )

    async def sum_issued_amount_between(self, *, start, end) -> float:
        return sum(
            invoice.amount.amount
            for invoice in self.by_id.values()
            if invoice.status.value != "void"
            and invoice.issued_at is not None
            and start <= invoice.issued_at < end
        )

    async def sum_outstanding_amount(self, *, as_of) -> float:
        return sum(
            invoice.amount.amount
            for invoice in self.by_id.values()
            if invoice.status.value == "issued"
            and invoice.issued_at is not None
            and invoice.issued_at <= as_of
        )


class InMemoryPaymentRepository(PaymentRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Payment] = {}

    async def get(self, payment_id: PaymentId) -> Payment | None:
        return self.by_id.get(str(payment_id))

    def add(self, payment: Payment) -> None:
        self.by_id[str(payment.id)] = payment

    async def list_all(self) -> list[Payment]:
        return list(self.by_id.values())

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        return next(
            (p for p in self.by_id.values() if p.idempotency_key == idempotency_key), None
        )

    async def get_by_provider_ref(self, provider: str, provider_ref: str) -> Payment | None:
        return next(
            (
                p
                for p in self.by_id.values()
                if p.provider == provider and p.provider_ref == provider_ref
            ),
            None,
        )

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Payment]:
        return _paginate_in_memory(
            list(self.by_id.values()), page_request, sort=sort, filters=filters, search=search
        )



class FakeBillingUnitOfWork(BillingUnitOfWork):
    def __init__(
        self,
        plans: InMemoryPlanRepository,
        subscriptions: InMemorySubscriptionRepository,
        invoices: InMemoryInvoiceRepository,
        payments: InMemoryPaymentRepository,
    ) -> None:
        self.plans = plans
        self.subscriptions = subscriptions
        self.invoices = invoices
        self.payments = payments
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakePaymentProvider(PaymentProviderPort):
    def __init__(
        self,
        provider_ref: str = "EVC-REF-999",
        *,
        result_status: str = "pending",
        failure_reason: str | None = None,
    ) -> None:
        self.provider_ref = provider_ref
        self.result_status = result_status
        self.failure_reason = failure_reason
        self.charge_calls: list[PaymentChargeRequest] = []

    async def charge(self, request: PaymentChargeRequest) -> PaymentChargeResult:
        self.charge_calls.append(request)
        return PaymentChargeResult(
            provider_ref=self.provider_ref,
            status=self.result_status,  # type: ignore[arg-type]
            failure_reason=self.failure_reason,
        )

    def verify_webhook_signature(self, *, payload: bytes, signature_header: str) -> bool:
        return True

    def parse_webhook_event(self, *, payload: bytes) -> WebhookEvent:
        raise NotImplementedError("FakePaymentProvider does not model webhook parsing.")


def make_uow() -> FakeBillingUnitOfWork:
    plans = InMemoryPlanRepository()
    return FakeBillingUnitOfWork(
        plans,
        InMemorySubscriptionRepository(plans=plans),
        InMemoryInvoiceRepository(),
        InMemoryPaymentRepository(),
    )


class _FakePlanHistoryPort:
    """Stands in for `PlanHistoryPort` — records every `plan_id` in `referenced_plan_ids` as
    "ever referenced", independent of what `SubscriptionRepository.exists_for_plan` reports for
    that plan's *current* subscriptions."""

    def __init__(self, referenced_plan_ids: set[str] | None = None) -> None:
        self.referenced_plan_ids = referenced_plan_ids or set()
        self.calls: list[str] = []

    async def plan_ever_referenced(self, plan_id: str) -> bool:
        self.calls.append(plan_id)
        return plan_id in self.referenced_plan_ids


def make_service(
    provider: PaymentProviderPort | None = None,
    plan_history: "_FakePlanHistoryPort | None" = None,
) -> BillingApplicationService:
    return BillingApplicationService(
        clock=CLOCK,
        id_generator=SequentialIdGenerator(),
        payment_provider=provider,
        plan_history=plan_history,
    )


class PlanApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_plan_persists_and_returns_dto(self) -> None:
        service = make_service()
        uow = make_uow()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Standard",
                billing_scope="organization",
                amount=50.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=10,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(plan.name, "Standard")
        self.assertEqual(plan.status, "active")
        self.assertEqual(uow.commit_count, 1)
        self.assertEqual(len(uow.plans.by_id), 1)

    async def test_get_plan_by_id_not_found_raises(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.get_plan_by_id(GetPlanByIdQuery(plan_id=NON_EXISTENT_ID), uow=uow)

    async def test_activate_then_disable_plan(self) -> None:
        service = make_service()
        uow = make_uow()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Standard",
                billing_scope="organization",
                amount=50.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        disabled = await service.disable_plan(
            DisablePlanCommand(plan_id=plan.id, actor=make_actor()), uow=uow
        )
        self.assertEqual(disabled.status, "inactive")
        activated = await service.activate_plan(
            ActivatePlanCommand(plan_id=plan.id, actor=make_actor()), uow=uow
        )
        self.assertEqual(activated.status, "active")

    async def test_list_plans_returns_all(self) -> None:
        service = make_service()
        uow = make_uow()
        await service.create_plan(
            CreatePlanCommand(
                name="Standard",
                billing_scope="organization",
                amount=50.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        page = await service.list_plans(
            ListPlansQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(len(page.data), 1)
        self.assertEqual(page.total, 1)

    async def test_delete_plan_succeeds_when_never_referenced(self) -> None:
        """Organization Management phase — the codebase's first and only aggregate-root hard
        delete, deliberately scoped to a plan nothing has ever subscribed to."""
        service = make_service()
        uow = make_uow()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Unused",
                billing_scope="organization",
                amount=50.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(len(uow.plans.by_id), 1)

        await service.delete_plan(DeletePlanCommand(plan_id=plan.id, actor=make_actor()), uow=uow)

        self.assertEqual(len(uow.plans.by_id), 0)
        with self.assertRaises(NotFoundError):
            await service.get_plan_by_id(GetPlanByIdQuery(plan_id=plan.id), uow=uow)

    async def test_delete_plan_refuses_when_referenced_by_any_subscription(self) -> None:
        """Even a long-cancelled subscription's own historical reference blocks deletion — see
        `PlanRepository.delete`'s own docstring for why this is deliberately not status-filtered."""
        service = make_service()
        uow = make_uow()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="In Use",
                billing_scope="organization",
                amount=50.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID, plan_id=plan.id, actor=make_actor()
            ),
            uow=uow,
        )

        with self.assertRaises(ConflictError):
            await service.delete_plan(
                DeletePlanCommand(plan_id=plan.id, actor=make_actor()), uow=uow
            )
        self.assertEqual(len(uow.plans.by_id), 1, "a refused delete must not remove the plan")

    async def test_delete_plan_refuses_when_only_historically_referenced(self) -> None:
        """Found live (Organization Management phase, via this phase's own dev-data
        verification): `change_plan` moves a subscription's *current* `plan_id` off a plan, so
        `exists_for_plan` alone no longer sees it — even though a real invoice may already have
        been issued at that plan's price. `PlanHistoryPort` is the second, independent check that
        closes this gap by consulting the permanent audit trail instead of the mutable
        `Subscription.plan_id` column."""
        service_no_history = make_service()
        uow = make_uow()
        old_plan = await service_no_history.create_plan(
            CreatePlanCommand(
                name="Old", billing_scope="organization", amount=100.00, currency="USD",
                billing_cycle="monthly", vehicle_limit=None, actor=make_actor(),
            ),
            uow=uow,
        )
        new_plan = await service_no_history.create_plan(
            CreatePlanCommand(
                name="New", billing_scope="organization", amount=30.00, currency="USD",
                billing_cycle="monthly", vehicle_limit=None, actor=make_actor(),
            ),
            uow=uow,
        )
        invoice = await service_no_history.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID, plan_id=old_plan.id, actor=make_actor()
            ),
            uow=uow,
        )
        await service_no_history.change_subscription_plan(
            ChangeSubscriptionPlanCommand(
                subscription_id=invoice.subscription_id, new_plan_id=new_plan.id, actor=make_actor()
            ),
            uow=uow,
        )

        # `exists_for_plan` alone (no `PlanHistoryPort` wired) now sees the old plan as unused —
        # the exact gap this test exists to close.
        self.assertFalse(await uow.subscriptions.exists_for_plan(PlanId(old_plan.id)))

        history = _FakePlanHistoryPort(referenced_plan_ids={old_plan.id})
        service_with_history = make_service(plan_history=history)
        with self.assertRaises(ConflictError):
            await service_with_history.delete_plan(
                DeletePlanCommand(plan_id=old_plan.id, actor=make_actor()), uow=uow
            )
        self.assertEqual(len(uow.plans.by_id), 2, "a refused delete must not remove the plan")

    async def test_delete_plan_succeeds_when_neither_check_finds_a_reference(self) -> None:
        """`PlanHistoryPort` is consulted, and truthfully reports no history — deletion still
        succeeds when the plan really has never been used, wired or not."""
        service = make_service(plan_history=_FakePlanHistoryPort())
        uow = make_uow()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Unused", billing_scope="organization", amount=50.00, currency="USD",
                billing_cycle="monthly", vehicle_limit=None, actor=make_actor(),
            ),
            uow=uow,
        )

        await service.delete_plan(DeletePlanCommand(plan_id=plan.id, actor=make_actor()), uow=uow)

        self.assertEqual(len(uow.plans.by_id), 0)

    async def test_delete_plan_skips_the_history_check_when_already_referenced(self) -> None:
        """The cheaper, already-existing `exists_for_plan` check short-circuits — `PlanHistoryPort`
        is never even called when the first check already refuses."""
        history = _FakePlanHistoryPort()
        service = make_service(plan_history=history)
        uow = make_uow()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="In Use", billing_scope="organization", amount=50.00, currency="USD",
                billing_cycle="monthly", vehicle_limit=None, actor=make_actor(),
            ),
            uow=uow,
        )
        await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID, plan_id=plan.id, actor=make_actor()
            ),
            uow=uow,
        )

        with self.assertRaises(ConflictError):
            await service.delete_plan(DeletePlanCommand(plan_id=plan.id, actor=make_actor()), uow=uow)
        self.assertEqual(history.calls, [])

    async def test_delete_missing_plan_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.delete_plan(
                DeletePlanCommand(plan_id=NON_EXISTENT_ID, actor=make_actor()), uow=uow
            )


class ChangeSubscriptionPlanApplicationTests(unittest.IsolatedAsyncioTestCase):
    """Organization Management phase — see `Subscription.change_plan`'s own docstring for the
    "current period/invoice unaffected, applies at next issuance" design this verifies."""

    async def _make_plan(self, service, uow, *, name: str, amount: float) -> str:
        plan = await service.create_plan(
            CreatePlanCommand(
                name=name,
                billing_scope="organization",
                amount=amount,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        return plan.id

    async def test_change_plan_updates_plan_id_without_touching_period_or_invoice(self) -> None:
        service = make_service()
        uow = make_uow()
        old_plan_id = await self._make_plan(service, uow, name="Old", amount=100.0)
        new_plan_id = await self._make_plan(service, uow, name="New", amount=150.0)

        invoice = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID, plan_id=old_plan_id, actor=make_actor()
            ),
            uow=uow,
        )
        original_invoice = await service.get_invoice_by_id(
            GetInvoiceByIdQuery(invoice_id=invoice.id), uow=uow
        )

        changed = await service.change_subscription_plan(
            ChangeSubscriptionPlanCommand(
                subscription_id=invoice.subscription_id,
                new_plan_id=new_plan_id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(changed.plan_id, new_plan_id)

        # The already-issued invoice is completely untouched — still the old plan's amount.
        reloaded_invoice = await service.get_invoice_by_id(
            GetInvoiceByIdQuery(invoice_id=invoice.id), uow=uow
        )
        self.assertEqual(reloaded_invoice.amount, original_invoice.amount)
        self.assertEqual(reloaded_invoice.amount, 100.0)

    async def test_change_plan_refuses_on_terminal_subscription(self) -> None:
        service = make_service()
        uow = make_uow()
        old_plan_id = await self._make_plan(service, uow, name="Old", amount=100.0)
        new_plan_id = await self._make_plan(service, uow, name="New", amount=150.0)
        invoice = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID, plan_id=old_plan_id, actor=make_actor()
            ),
            uow=uow,
        )
        subscription_id = invoice.subscription_id
        await service.cancel_subscription(
            CancelSubscriptionCommand(subscription_id=subscription_id, actor=make_actor()),
            uow=uow,
        )

        with self.assertRaises(DomainError):
            await service.change_subscription_plan(
                ChangeSubscriptionPlanCommand(
                    subscription_id=subscription_id,
                    new_plan_id=new_plan_id,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_change_plan_refuses_an_inactive_new_plan(self) -> None:
        service = make_service()
        uow = make_uow()
        old_plan_id = await self._make_plan(service, uow, name="Old", amount=100.0)
        new_plan_id = await self._make_plan(service, uow, name="New", amount=150.0)
        await service.disable_plan(
            DisablePlanCommand(plan_id=new_plan_id, actor=make_actor()), uow=uow
        )
        invoice = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID, plan_id=old_plan_id, actor=make_actor()
            ),
            uow=uow,
        )

        with self.assertRaises(DomainError):
            await service.change_subscription_plan(
                ChangeSubscriptionPlanCommand(
                    subscription_id=invoice.subscription_id,
                    new_plan_id=new_plan_id,
                    actor=make_actor(),
                ),
                uow=uow,
            )


class SubscriptionApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def _make_plan(self, service: BillingApplicationService, uow) -> str:
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Parent Plan",
                billing_scope="organization",
                amount=10.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        return plan.id

    async def test_open_organization_subscription_opens_new_subscription_and_issues_invoice(
        self,
    ) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)

        invoice = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan_id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(invoice.status, "issued")
        self.assertEqual(len(uow.subscriptions.by_id), 1)
        self.assertEqual(len(uow.invoices.by_id), 1)

    async def test_open_organization_subscription_reuses_existing_active_subscription(
        self,
    ) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        command = OpenOrganizationSubscriptionCommand(
            organization_id=VALID_ORG_ULID,
            plan_id=plan_id,
            actor=make_actor(),
        )
        await service.open_organization_subscription(command, uow=uow)
        self.assertEqual(len(uow.subscriptions.by_id), 1)

        await service.open_organization_subscription(command, uow=uow)
        self.assertEqual(
            len(uow.subscriptions.by_id), 1, "second renewal must reuse, not duplicate"
        )
        self.assertEqual(len(uow.invoices.by_id), 2, "each renewal issues its own invoice")

    async def test_open_organization_subscription_missing_plan_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.open_organization_subscription(
                OpenOrganizationSubscriptionCommand(
                    organization_id=VALID_ORG_ULID,
                    plan_id=NON_EXISTENT_ID,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_expire_suspend_cancel_subscription(self) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        invoice = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan_id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        subscription_id = invoice.subscription_id

        suspended = await service.suspend_subscription(
            SuspendSubscriptionCommand(subscription_id=subscription_id, actor=make_actor()),
            uow=uow,
        )
        self.assertEqual(suspended.status, "suspended")

        cancelled = await service.cancel_subscription(
            CancelSubscriptionCommand(subscription_id=subscription_id, actor=make_actor()),
            uow=uow,
        )
        self.assertEqual(cancelled.status, "cancelled")

    async def test_get_subscription_by_id_not_found_raises(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.get_subscription_by_id(
                GetSubscriptionByIdQuery(subscription_id=NON_EXISTENT_ID), uow=uow
            )

    async def test_list_subscriptions_returns_all(self) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan_id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        page = await service.list_subscriptions(
            ListSubscriptionsQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(len(page.data), 1)
        self.assertEqual(page.total, 1)

    async def test_open_organization_subscription_for_a_different_organization_raises_authorization_error(
        self,
    ) -> None:
        # ADR-0021's `_enforce_own_organization` (`application/services.py`) - `Subscription`
        # has no cross-aggregate reference to transitively validate `organization_id` against
        # (`Plan` isn't organization-owned at all), so this is the only check closing this
        # write-side IDOR.
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        with self.assertRaises(AuthorizationError):
            await service.open_organization_subscription(
                OpenOrganizationSubscriptionCommand(
                    organization_id=OTHER_ORG_ULID,
                    plan_id=plan_id,
                    actor=make_actor(org_id=VALID_ORG_ULID),
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.subscriptions.by_id), 0)


class ManualPaymentAndActivationApplicationTests(unittest.IsolatedAsyncioTestCase):
    """The Founder-recorded manual-payment workflow (Organization Lifecycle / Subscription
    architecture pass): `record_manual_payment` marks the invoice paid without touching the
    subscription; `activate_subscription` is the deliberate, separate step that actually renews
    it — mirrors, but does not reuse, the existing self-service Stripe auto-activate path."""

    async def _make_plan(self, service: BillingApplicationService, uow) -> str:
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Standard",
                billing_scope="organization",
                amount=100.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        return plan.id

    async def test_record_manual_payment_marks_invoice_paid_without_activating_subscription(
        self,
    ) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        invoice = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID, plan_id=plan_id, actor=make_actor()
            ),
            uow=uow,
        )
        subscription_before = await service.get_subscription_by_id(
            GetSubscriptionByIdQuery(subscription_id=invoice.subscription_id), uow=uow
        )
        self.assertEqual(subscription_before.status, "trial")

        payment = await service.record_manual_payment(
            RecordManualSubscriptionPaymentCommand(
                invoice_id=invoice.id, actor=make_actor(), reference="bank-txn-123"
            ),
            uow=uow,
        )
        self.assertEqual(payment.status, "paid")

        paid_invoice = await service.get_invoice_by_id(
            GetInvoiceByIdQuery(invoice_id=invoice.id), uow=uow
        )
        self.assertEqual(paid_invoice.status, "paid")

        subscription_after = await service.get_subscription_by_id(
            GetSubscriptionByIdQuery(subscription_id=invoice.subscription_id), uow=uow
        )
        self.assertEqual(
            subscription_after.status,
            "trial",
            "recording a manual payment must not, by itself, activate the subscription",
        )

    async def test_activate_subscription_after_manual_payment_renews_it(self) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        invoice = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID, plan_id=plan_id, actor=make_actor()
            ),
            uow=uow,
        )
        await service.record_manual_payment(
            RecordManualSubscriptionPaymentCommand(
                invoice_id=invoice.id, actor=make_actor()
            ),
            uow=uow,
        )

        activated = await service.activate_subscription(
            ActivateSubscriptionCommand(
                subscription_id=invoice.subscription_id, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(activated.status, "active")
        self.assertIsNotNone(activated.current_period_end)

    async def test_activate_subscription_refuses_while_invoice_unpaid(self) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        invoice = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID, plan_id=plan_id, actor=make_actor()
            ),
            uow=uow,
        )
        with self.assertRaises(DomainError):
            await service.activate_subscription(
                ActivateSubscriptionCommand(
                    subscription_id=invoice.subscription_id, actor=make_actor()
                ),
                uow=uow,
            )


class InvoiceApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_issue_invoice_and_void(self) -> None:
        service = make_service()
        uow = make_uow()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Org Plan",
                billing_scope="organization",
                amount=100.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        renewal = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan.id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        invoice = await service.issue_invoice(
            IssueInvoiceCommand(
                organization_id=VALID_ORG_ULID,
                subscription_id=renewal.subscription_id,
                amount=100.00,
                currency="USD",
                period_start=date(2026, 8, 20),
                period_end=date(2026, 9, 19),
                due_at=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(invoice.status, "issued")

        voided = await service.void_invoice(
            VoidInvoiceCommand(invoice_id=invoice.id, actor=make_actor()), uow=uow
        )
        self.assertEqual(voided.status, "void")

    async def test_issue_invoice_for_a_different_organization_raises_authorization_error(
        self,
    ) -> None:
        # ADR-0021's `_enforce_own_organization` - nothing here cross-checks the loaded
        # Subscription's own `organization_id` against `command.organization_id`, so this is
        # the only check closing this write-side IDOR (a caller's own, correctly-scoped
        # subscription could otherwise be billed to a different organization's invoice).
        service = make_service()
        uow = make_uow()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Org Plan",
                billing_scope="organization",
                amount=100.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        renewal = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan.id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(AuthorizationError):
            await service.issue_invoice(
                IssueInvoiceCommand(
                    organization_id=OTHER_ORG_ULID,
                    subscription_id=renewal.subscription_id,
                    amount=100.00,
                    currency="USD",
                    period_start=date(2026, 8, 20),
                    period_end=date(2026, 9, 19),
                    due_at=None,
                    actor=make_actor(org_id=VALID_ORG_ULID),
                ),
                uow=uow,
            )

    async def test_get_invoice_by_id_not_found_raises(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.get_invoice_by_id(
                GetInvoiceByIdQuery(invoice_id=NON_EXISTENT_ID), uow=uow
            )

    async def test_issue_invoice_missing_subscription_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.issue_invoice(
                IssueInvoiceCommand(
                    organization_id=VALID_ORG_ULID,
                    subscription_id=NON_EXISTENT_ID,
                    amount=10.00,
                    currency="USD",
                    period_start=date(2026, 8, 20),
                    period_end=date(2026, 9, 19),
                    due_at=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )


class PaymentIntegrityTests(unittest.IsolatedAsyncioTestCase):
    """Finance P0.1 (payment guards) and P0.3 (a confirmed payment for an invoice that changed
    underneath it). Every refusal must happen before a Payment row exists and before any
    provider is charged."""

    async def _make_invoice(self, uow) -> str:
        return await PaymentApplicationTests._make_invoice(self, uow)  # 25.00 USD

    def _initiate(self, invoice_id: str, *, key: str, amount: float = 25.00, currency="USD"):
        return InitiatePaymentCommand(
            invoice_id=invoice_id,
            method="stripe",
            amount=amount,
            currency=currency,
            idempotency_key=key,
            actor=make_actor(),
            payment_method_token="pm_card_visa",
        )

    async def _pay_manually(self, service, uow, invoice_id: str):
        return await service.record_manual_payment(
            RecordManualSubscriptionPaymentCommand(invoice_id=invoice_id, actor=make_actor()),
            uow=uow,
        )

    async def _void(self, service, uow, invoice_id: str) -> None:
        await service.void_invoice(
            VoidInvoiceCommand(invoice_id=invoice_id, actor=make_actor()), uow=uow
        )

    # ---- P0.1: manual payments ------------------------------------------------------------

    async def test_a_second_manual_payment_on_a_paid_invoice_is_refused(self) -> None:
        service, uow = make_service(), make_uow()
        invoice_id = await self._make_invoice(uow)
        await self._pay_manually(service, uow, invoice_id)

        with self.assertRaises(ConflictError):
            await self._pay_manually(service, uow, invoice_id)
        self.assertEqual(len(uow.payments.by_id), 1)

    async def test_a_manual_payment_on_a_void_invoice_is_refused_and_it_stays_void(self) -> None:
        service, uow = make_service(), make_uow()
        invoice_id = await self._make_invoice(uow)
        await self._void(service, uow, invoice_id)

        with self.assertRaises(RuleViolationError):
            await self._pay_manually(service, uow, invoice_id)
        self.assertEqual(uow.invoices.by_id[invoice_id].status, InvoiceStatus.VOID)
        self.assertEqual(uow.payments.by_id, {})

    # ---- P0.1: provider payments ----------------------------------------------------------

    async def test_charging_a_paid_invoice_is_refused_before_the_provider_is_called(
        self,
    ) -> None:
        provider = FakePaymentProvider(result_status="succeeded")
        service, uow = make_service(provider=provider), make_uow()
        invoice_id = await self._make_invoice(uow)
        await self._pay_manually(service, uow, invoice_id)

        with self.assertRaises(ConflictError):
            await service.initiate_payment(self._initiate(invoice_id, key="k-paid"), uow=uow)
        self.assertEqual(provider.charge_calls, [])
        self.assertEqual(len(uow.payments.by_id), 1)  # only the manual one

    async def test_charging_a_void_invoice_is_refused_before_the_provider_is_called(
        self,
    ) -> None:
        provider = FakePaymentProvider(result_status="succeeded")
        service, uow = make_service(provider=provider), make_uow()
        invoice_id = await self._make_invoice(uow)
        await self._void(service, uow, invoice_id)

        with self.assertRaises(RuleViolationError):
            await service.initiate_payment(self._initiate(invoice_id, key="k-void"), uow=uow)
        self.assertEqual(provider.charge_calls, [])
        self.assertEqual(uow.invoices.by_id[invoice_id].status, InvoiceStatus.VOID)

    async def test_an_amount_or_currency_that_does_not_match_the_invoice_is_refused(
        self,
    ) -> None:
        """Before P0.1 a $1.00 charge settled a $25.00 invoice in full, and revenue then
        reported the full $25.00."""
        provider = FakePaymentProvider(result_status="succeeded")
        service, uow = make_service(provider=provider), make_uow()
        invoice_id = await self._make_invoice(uow)

        for amount, currency in ((1.00, "USD"), (25.01, "USD"), (25.00, "EUR")):
            with self.subTest(amount=amount, currency=currency):
                with self.assertRaises(DomainError):
                    await service.initiate_payment(
                        self._initiate(
                            invoice_id,
                            key=f"k-{amount}-{currency}",
                            amount=amount,
                            currency=currency,
                        ),
                        uow=uow,
                    )
        self.assertEqual(provider.charge_calls, [])
        self.assertEqual(uow.payments.by_id, {})
        self.assertEqual(uow.invoices.by_id[invoice_id].status, InvoiceStatus.ISSUED)

    async def test_a_matching_amount_written_differently_is_accepted(self) -> None:
        provider = FakePaymentProvider(result_status="succeeded")
        service, uow = make_service(provider=provider), make_uow()
        invoice_id = await self._make_invoice(uow)

        payment = await service.initiate_payment(
            self._initiate(invoice_id, key="k-float", amount=25.0, currency="usd"), uow=uow
        )
        self.assertEqual(payment.status, "paid")

    async def test_a_retry_of_a_successful_request_still_returns_the_original_payment(
        self,
    ) -> None:
        """The idempotency lookup runs before the new guards, so a client that retries after a
        success (the invoice is now paid) gets its payment back, not a 409."""
        provider = FakePaymentProvider(result_status="succeeded")
        service, uow = make_service(provider=provider), make_uow()
        invoice_id = await self._make_invoice(uow)
        first = await service.initiate_payment(self._initiate(invoice_id, key="k-retry"), uow=uow)

        again = await service.initiate_payment(self._initiate(invoice_id, key="k-retry"), uow=uow)
        self.assertEqual(again.id, first.id)
        self.assertEqual(len(provider.charge_calls), 1)

    # ---- P0.3: webhook for an invoice that changed while the payment was in flight --------

    async def _processing_payment(self):
        provider = FakePaymentProvider(result_status="pending")
        service, uow = make_service(provider=provider), make_uow()
        invoice_id = await self._make_invoice(uow)
        payment = await service.initiate_payment(
            self._initiate(invoice_id, key="k-webhook"), uow=uow
        )
        self.assertEqual(payment.status, "processing")
        return service, uow, invoice_id, payment

    async def _confirm(self, service, uow, payment):
        return await service.handle_payment_callback(
            PaymentCallbackCommand(
                payment_id=payment.id, status="paid", provider_ref="pi_123", actor=make_actor()
            ),
            uow=uow,
        )

    def _review_events(self, uow) -> list:
        return [e for e in uow.recorded_events if e.event_type == "PaymentRequiresReview"]

    def _period_end(self, uow, invoice_id: str):
        subscription_id = str(uow.invoices.by_id[invoice_id].subscription_id)
        return uow.subscriptions.by_id[subscription_id].current_period_end

    async def test_confirmed_money_for_a_voided_invoice_is_kept_and_flagged_not_applied(
        self,
    ) -> None:
        service, uow, invoice_id, payment = await self._processing_payment()
        await self._void(service, uow, invoice_id)
        period_before = self._period_end(uow, invoice_id)

        result = await self._confirm(service, uow, payment)  # no exception: webhook acknowledged

        self.assertEqual(result.status, "paid")
        self.assertEqual(uow.invoices.by_id[invoice_id].status, InvoiceStatus.VOID)
        self.assertEqual(self._period_end(uow, invoice_id), period_before)
        (review,) = self._review_events(uow)
        self.assertEqual(review.payload["reason"], "invoice_void")
        self.assertEqual(review.payload["invoice_id"], invoice_id)

    async def test_confirmed_money_for_an_invoice_paid_meanwhile_is_flagged_not_reapplied(
        self,
    ) -> None:
        service, uow, invoice_id, payment = await self._processing_payment()
        await self._pay_manually(service, uow, invoice_id)
        period_before = self._period_end(uow, invoice_id)

        result = await self._confirm(service, uow, payment)

        self.assertEqual(result.status, "paid")
        self.assertEqual(uow.invoices.by_id[invoice_id].status, InvoiceStatus.PAID)
        self.assertEqual(self._period_end(uow, invoice_id), period_before)
        (review,) = self._review_events(uow)
        self.assertEqual(review.payload["reason"], "invoice_already_paid")

    async def test_a_replayed_webhook_for_a_flagged_payment_is_not_flagged_twice(self) -> None:
        service, uow, invoice_id, payment = await self._processing_payment()
        await self._void(service, uow, invoice_id)
        await self._confirm(service, uow, payment)
        await self._confirm(service, uow, payment)
        self.assertEqual(len(self._review_events(uow)), 1)


class PaymentApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def _make_invoice(self, uow) -> str:
        service = make_service()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Parent Plan",
                billing_scope="organization",
                amount=25.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        invoice = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan.id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        return invoice.id

    async def test_initiate_payment_without_provider_persists_pending_then_raises(
        self,
    ) -> None:
        service = make_service(provider=None)
        uow = make_uow()
        invoice_id = await self._make_invoice(uow)

        with self.assertRaises(NotImplementedError):
            await service.initiate_payment(
                InitiatePaymentCommand(
                    invoice_id=invoice_id,
                    method="evcplus",
                    msisdn="+2526000000",
                    amount=25.00,
                    currency="USD",
                    idempotency_key="idem-key-a",
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.payments.by_id), 1)
        persisted = next(iter(uow.payments.by_id.values()))
        self.assertEqual(persisted.status.value, "pending")

    async def test_initiate_payment_with_bound_provider_marks_processing(self) -> None:
        provider = FakePaymentProvider()
        service = make_service(provider=provider)
        uow = make_uow()
        invoice_id = await self._make_invoice(uow)

        payment = await service.initiate_payment(
            InitiatePaymentCommand(
                invoice_id=invoice_id,
                method="evcplus",
                msisdn="+2526000000",
                amount=25.00,
                currency="USD",
                idempotency_key="idem-key-b",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(payment.status, "processing")
        self.assertEqual(len(provider.charge_calls), 1)

    async def test_initiate_payment_repeat_idempotency_key_returns_original(self) -> None:
        service = make_service(provider=None)
        uow = make_uow()
        invoice_id = await self._make_invoice(uow)

        command = InitiatePaymentCommand(
            invoice_id=invoice_id,
            method="evcplus",
            msisdn="+2526000000",
            amount=25.00,
            currency="USD",
            idempotency_key="idem-key-c",
            actor=make_actor(),
        )
        with self.assertRaises(NotImplementedError):
            await service.initiate_payment(command, uow=uow)
        self.assertEqual(len(uow.payments.by_id), 1)

        # Repeat with the same idempotency key must short-circuit to the original result
        # (API Contracts §12) — no provider call, no second Payment row.
        repeat_result = await service.initiate_payment(command, uow=uow)
        self.assertEqual(len(uow.payments.by_id), 1)
        self.assertEqual(repeat_result.idempotency_key, "idem-key-c")

    async def test_initiate_payment_missing_invoice_raises_not_found(self) -> None:
        service = make_service(provider=None)
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.initiate_payment(
                InitiatePaymentCommand(
                    invoice_id=NON_EXISTENT_ID,
                    method="evcplus",
                    msisdn="+2526000000",
                    amount=25.00,
                    currency="USD",
                    idempotency_key="idem-key-d",
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_handle_payment_callback_paid_cascades_invoice_and_subscription(
        self,
    ) -> None:
        provider = FakePaymentProvider()
        service = make_service(provider=provider)
        uow = make_uow()
        invoice_id = await self._make_invoice(uow)
        payment = await service.initiate_payment(
            InitiatePaymentCommand(
                invoice_id=invoice_id,
                method="evcplus",
                msisdn="+2526000000",
                amount=25.00,
                currency="USD",
                idempotency_key="idem-key-e",
                actor=make_actor(),
            ),
            uow=uow,
        )

        result = await service.handle_payment_callback(
            PaymentCallbackCommand(
                payment_id=payment.id,
                status="paid",
                provider_ref="EVC-CONFIRM-1",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(result.status, "paid")
        self.assertEqual(result.provider_ref, "EVC-CONFIRM-1")

        stored_invoice = await uow.invoices.get(InvoiceId(invoice_id))
        self.assertEqual(stored_invoice.status.value, "paid")
        stored_subscription = await uow.subscriptions.get(stored_invoice.subscription_id)
        self.assertEqual(stored_subscription.status.value, "active")

    async def test_handle_payment_callback_paid_replay_does_not_double_advance_subscription(
        self,
    ) -> None:
        """ADR-0022's own named regression: a real payment provider retries a webhook delivery
        until it receives a 200, so a duplicate 'paid' callback for an already-PAID payment is
        normal traffic, not an error — and must not call `Subscription.renew` a second time."""
        provider = FakePaymentProvider()
        service = make_service(provider=provider)
        uow = make_uow()
        invoice_id = await self._make_invoice(uow)
        payment = await service.initiate_payment(
            InitiatePaymentCommand(
                invoice_id=invoice_id,
                method="evcplus",
                msisdn="+2526000000",
                amount=25.00,
                currency="USD",
                idempotency_key="idem-key-replay",
                actor=make_actor(),
            ),
            uow=uow,
        )

        callback = PaymentCallbackCommand(
            payment_id=payment.id,
            status="paid",
            provider_ref="EVC-CONFIRM-REPLAY",
            actor=make_actor(),
        )
        await service.handle_payment_callback(callback, uow=uow)

        stored_invoice = await uow.invoices.get(InvoiceId(invoice_id))
        first_period_end = (
            await uow.subscriptions.get(stored_invoice.subscription_id)
        ).current_period_end

        # A second, identical delivery of the exact same webhook event.
        result = await service.handle_payment_callback(callback, uow=uow)

        self.assertEqual(result.status, "paid")
        second_period_end = (
            await uow.subscriptions.get(stored_invoice.subscription_id)
        ).current_period_end
        self.assertEqual(
            second_period_end,
            first_period_end,
            "a replayed webhook must not advance the billing period a second time",
        )

    async def test_handle_payment_callback_failed_leaves_invoice_untouched(self) -> None:
        provider = FakePaymentProvider()
        service = make_service(provider=provider)
        uow = make_uow()
        invoice_id = await self._make_invoice(uow)
        payment = await service.initiate_payment(
            InitiatePaymentCommand(
                invoice_id=invoice_id,
                method="evcplus",
                msisdn="+2526000000",
                amount=25.00,
                currency="USD",
                idempotency_key="idem-key-f",
                actor=make_actor(),
            ),
            uow=uow,
        )

        result = await service.handle_payment_callback(
            PaymentCallbackCommand(
                payment_id=payment.id, status="failed", provider_ref=None, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(result.status, "failed")

        stored_invoice = await uow.invoices.get(InvoiceId(invoice_id))
        self.assertEqual(
            stored_invoice.status.value,
            "issued",
            "a failed payment must not mutate the invoice (entities.py's resolved conflict)",
        )

    async def test_handle_payment_callback_paid_without_provider_ref_raises_domain_error(
        self,
    ) -> None:
        provider = FakePaymentProvider()
        service = make_service(provider=provider)
        uow = make_uow()
        invoice_id = await self._make_invoice(uow)
        payment = await service.initiate_payment(
            InitiatePaymentCommand(
                invoice_id=invoice_id,
                method="evcplus",
                msisdn="+2526000000",
                amount=25.00,
                currency="USD",
                idempotency_key="idem-key-g",
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(DomainError):
            await service.handle_payment_callback(
                PaymentCallbackCommand(
                    payment_id=payment.id, status="paid", provider_ref=None, actor=make_actor()
                ),
                uow=uow,
            )

    async def test_mark_payment_expired(self) -> None:
        service = make_service(provider=None)
        uow = make_uow()
        invoice_id = await self._make_invoice(uow)
        with self.assertRaises(NotImplementedError):
            await service.initiate_payment(
                InitiatePaymentCommand(
                    invoice_id=invoice_id,
                    method="evcplus",
                    msisdn="+2526000000",
                    amount=25.00,
                    currency="USD",
                    idempotency_key="idem-key-h",
                    actor=make_actor(),
                ),
                uow=uow,
            )
        payment_id = next(iter(uow.payments.by_id.values())).id.value

        expired = await service.mark_payment_expired(
            MarkPaymentExpiredCommand(payment_id=payment_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(expired.status, "expired")

    async def test_get_payment_by_id_not_found_raises(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.get_payment_by_id(
                GetPaymentByIdQuery(payment_id=NON_EXISTENT_ID), uow=uow
            )



# --- TransportFee tests removed by ADR-0040 -------------------------------------------------
#
# `billing.TransportFee` no longer exists — school->student fees moved to `school_erp`
# (ADR-0038 §2), migration `7387f1b2ee6a`. Deleted rather than ported: the replacement aggregate
# has a materially different shape (partial payments, discount, transport context).

class ScheduledJobApplicationTests(unittest.IsolatedAsyncioTestCase):
    """`sweep_expired_subscriptions`/`reconcile_expired_payments` (Backend Stabilization phase)
    — the subscription-status-sweep and payment-reconciliation scheduled jobs' own entry
    points. Uses two `BillingApplicationService` instances sharing one fake `uow`, each with
    its own `FixedClock`, to simulate "time passing" between creation and the sweep."""

    async def test_sweep_expired_subscriptions_expires_past_period_end(self) -> None:
        """A `Subscription` only gets a real `current_period_end` once a payment actually
        succeeds (`handle_payment_callback(status="paid")` calls `Subscription.renew()`,
        `application/services.py`'s own module docstring) — `open_organization_subscription` alone
        leaves it `TRIAL`/`current_period_end=None`. This test drives the full pay-and-confirm
        flow so the sweep has a real, in-the-past period end to find."""
        early_clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        provider = FakePaymentProvider()
        early_service = BillingApplicationService(
            clock=early_clock, id_generator=SequentialIdGenerator(), payment_provider=provider
        )
        uow = make_uow()
        plan = await early_service.create_plan(
            CreatePlanCommand(
                name="Parent Plan",
                billing_scope="organization",
                amount=10.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        renewal = await early_service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan.id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        payment = await early_service.initiate_payment(
            InitiatePaymentCommand(
                invoice_id=renewal.id,
                method="evcplus",
                msisdn="+2526000000",
                amount=10.00,
                currency="USD",
                idempotency_key="idem-sweep-1",
                actor=make_actor(),
            ),
            uow=uow,
        )
        await early_service.handle_payment_callback(
            PaymentCallbackCommand(
                payment_id=payment.id,
                status="paid",
                provider_ref="EVC-REF-SWEEP-1",
                actor=make_actor(),
            ),
            uow=uow,
        )
        # current_period_end is now early_clock.now() + 30 days = 2026-01-31.

        late_clock = FixedClock(datetime(2026, 3, 1, tzinfo=timezone.utc))
        late_service = BillingApplicationService(
            clock=late_clock, id_generator=SequentialIdGenerator()
        )
        expired_count = await late_service.sweep_expired_subscriptions(uow=uow)

        self.assertEqual(expired_count, 1)
        stored = await uow.subscriptions.get(SubscriptionId(renewal.subscription_id))
        self.assertEqual(stored.status.value, "expired")

    async def test_sweep_expired_subscriptions_skips_not_yet_due(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        provider = FakePaymentProvider()
        service = BillingApplicationService(
            clock=clock, id_generator=SequentialIdGenerator(), payment_provider=provider
        )
        uow = make_uow()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Parent Plan",
                billing_scope="organization",
                amount=10.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        renewal = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan.id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        payment = await service.initiate_payment(
            InitiatePaymentCommand(
                invoice_id=renewal.id,
                method="evcplus",
                msisdn="+2526000000",
                amount=10.00,
                currency="USD",
                idempotency_key="idem-sweep-2",
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.handle_payment_callback(
            PaymentCallbackCommand(
                payment_id=payment.id,
                status="paid",
                provider_ref="EVC-REF-SWEEP-2",
                actor=make_actor(),
            ),
            uow=uow,
        )
        # current_period_end is now 2026-01-31 - still in the future relative to `clock` itself.

        expired_count = await service.sweep_expired_subscriptions(uow=uow)
        self.assertEqual(expired_count, 0)
        stored = await uow.subscriptions.get(SubscriptionId(renewal.subscription_id))
        self.assertEqual(stored.status.value, "active")

    async def test_reconcile_expired_payments_expires_stale_pending(self) -> None:
        early_clock = FixedClock(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
        early_service = BillingApplicationService(
            clock=early_clock, id_generator=SequentialIdGenerator(), payment_provider=None
        )
        uow = make_uow()
        plan = await early_service.create_plan(
            CreatePlanCommand(
                name="Parent Plan",
                billing_scope="organization",
                amount=25.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        invoice = await early_service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan.id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(NotImplementedError):
            await early_service.initiate_payment(
                InitiatePaymentCommand(
                    invoice_id=invoice.id,
                    method="evcplus",
                    msisdn="+2526000000",
                    amount=25.00,
                    currency="USD",
                    idempotency_key="idem-reconcile-1",
                    actor=make_actor(),
                ),
                uow=uow,
            )
        payment_id = next(iter(uow.payments.by_id.values())).id.value

        late_clock = FixedClock(datetime(2026, 1, 1, 1, 0, 0, tzinfo=timezone.utc))
        late_service = BillingApplicationService(
            clock=late_clock, id_generator=SequentialIdGenerator()
        )
        expired_count = await late_service.reconcile_expired_payments(
            timeout_minutes=30, uow=uow
        )

        self.assertEqual(expired_count, 1)
        stored = await uow.payments.get(PaymentId(payment_id))
        self.assertEqual(stored.status.value, "expired")

    async def test_reconcile_expired_payments_skips_recent_pending(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        service = BillingApplicationService(
            clock=clock, id_generator=SequentialIdGenerator(), payment_provider=None
        )
        uow = make_uow()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Parent Plan",
                billing_scope="organization",
                amount=25.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        invoice = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan.id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(NotImplementedError):
            await service.initiate_payment(
                InitiatePaymentCommand(
                    invoice_id=invoice.id,
                    method="evcplus",
                    msisdn="+2526000000",
                    amount=25.00,
                    currency="USD",
                    idempotency_key="idem-reconcile-2",
                    actor=make_actor(),
                ),
                uow=uow,
            )

        expired_count = await service.reconcile_expired_payments(
            timeout_minutes=30, uow=uow
        )
        self.assertEqual(expired_count, 0)

    async def test_reconcile_expired_payments_ignores_paid(self) -> None:
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        provider = FakePaymentProvider()
        service = BillingApplicationService(
            clock=clock, id_generator=SequentialIdGenerator(), payment_provider=provider
        )
        uow = make_uow()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Parent Plan",
                billing_scope="organization",
                amount=25.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        invoice = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan.id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        payment = await service.initiate_payment(
            InitiatePaymentCommand(
                invoice_id=invoice.id,
                method="evcplus",
                msisdn="+2526000000",
                amount=25.00,
                currency="USD",
                idempotency_key="idem-reconcile-3",
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.handle_payment_callback(
            PaymentCallbackCommand(
                payment_id=payment.id,
                status="paid",
                provider_ref="EVC-REF-1",
                actor=make_actor(),
            ),
            uow=uow,
        )

        late_clock = FixedClock(datetime(2026, 3, 1, tzinfo=timezone.utc))
        late_service = BillingApplicationService(
            clock=late_clock, id_generator=SequentialIdGenerator()
        )
        expired_count = await late_service.reconcile_expired_payments(
            timeout_minutes=30, uow=uow
        )
        self.assertEqual(expired_count, 0)


class PlanPaginationApplicationTests(unittest.IsolatedAsyncioTestCase):
    """`GET /billing/plans` pagination/filtering/sorting (API Contracts §7/§8) — mirrors
    `test_organization_application.py`'s `OrganizationPaginationApplicationTests` exactly."""

    async def test_list_plans_paginates_and_reports_total(self) -> None:
        service = make_service()
        uow = make_uow()
        for i in range(3):
            await service.create_plan(
                CreatePlanCommand(
                    name=f"Plan {i}",
                    billing_scope="organization",
                    amount=10.00 + i,
                    currency="USD",
                    billing_cycle="monthly",
                    vehicle_limit=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await service.list_plans(
            ListPlansQuery(page_request=OffsetPageRequest(page=1, page_size=2)), uow=uow
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(page.page, 1)
        self.assertEqual(page.page_size, 2)
        self.assertEqual(len(page.data), 2)

        second_page = await service.list_plans(
            ListPlansQuery(page_request=OffsetPageRequest(page=2, page_size=2)), uow=uow
        )
        self.assertEqual(len(second_page.data), 1)

    async def test_list_plans_filters_by_billing_cycle(self) -> None:
        """Replaces the former `test_list_plans_filters_by_billing_scope` — ADR-0016 removed
        `BillingScope.PARENT`, leaving `billing_scope` with exactly one value (`organization`),
        so filtering by it can no longer distinguish rows. `billing_cycle` exercises the
        identical filterable-fields mechanism with a field that still has multiple values."""
        service = make_service()
        uow = make_uow()
        await service.create_plan(
            CreatePlanCommand(
                name="Monthly Plan",
                billing_scope="organization",
                amount=50.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.create_plan(
            CreatePlanCommand(
                name="Annual Plan",
                billing_scope="organization",
                amount=500.00,
                currency="USD",
                billing_cycle="annual",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )

        page = await service.list_plans(
            ListPlansQuery(
                page_request=OffsetPageRequest(),
                filters=[FilterCondition(field="billing_cycle", op="eq", value="annual")],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].name, "Annual Plan")

    async def test_list_plans_sorts_descending_by_name(self) -> None:
        service = make_service()
        uow = make_uow()
        for name in ("Alpha", "Beta", "Gamma"):
            await service.create_plan(
                CreatePlanCommand(
                    name=name,
                    billing_scope="organization",
                    amount=10.00,
                    currency="USD",
                    billing_cycle="monthly",
                    vehicle_limit=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await service.list_plans(
            ListPlansQuery(
                page_request=OffsetPageRequest(),
                sort=[SortSpec(field="name", descending=True)],
            ),
            uow=uow,
        )
        self.assertEqual([p.name for p in page.data], ["Gamma", "Beta", "Alpha"])


class SubscriptionPaginationApplicationTests(unittest.IsolatedAsyncioTestCase):
    """`GET /billing/subscriptions` pagination/filtering/sorting (API Contracts §7/§8)."""

    async def _make_plan(self, service: BillingApplicationService, uow) -> str:
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Parent Plan",
                billing_scope="organization",
                amount=10.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        return plan.id

    async def test_list_subscriptions_paginates_and_reports_total(self) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        # Distinct organization_id per call — `open_organization_subscription` now reuses any
        # existing non-terminal subscription for the *same* organization (ADR-0016: keyed on
        # `organization_id` alone), so three distinct rows need three distinct organizations.
        # ADR-0021's `_enforce_own_organization` restricts an org_admin actor to their own org -
        # a Founder actor (unrestricted) is what a real caller opening subscriptions across
        # multiple organizations would actually be.
        for i in range(3):
            await service.open_organization_subscription(
                OpenOrganizationSubscriptionCommand(
                    organization_id=f"org-page-{i}",
                    plan_id=plan_id,
                    actor=make_founder_actor(),
                ),
                uow=uow,
            )

        page = await service.list_subscriptions(
            ListSubscriptionsQuery(page_request=OffsetPageRequest(page=1, page_size=2)),
            uow=uow,
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

        second_page = await service.list_subscriptions(
            ListSubscriptionsQuery(page_request=OffsetPageRequest(page=2, page_size=2)),
            uow=uow,
        )
        self.assertEqual(len(second_page.data), 1)

    async def test_list_subscriptions_filters_by_status(self) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        first = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan_id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan_id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.suspend_subscription(
            SuspendSubscriptionCommand(
                subscription_id=first.subscription_id, actor=make_actor()
            ),
            uow=uow,
        )

        page = await service.list_subscriptions(
            ListSubscriptionsQuery(
                page_request=OffsetPageRequest(),
                filters=[FilterCondition(field="status", op="eq", value="suspended")],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].id, first.subscription_id)

    async def test_list_subscriptions_sorts_ascending_by_status(self) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        # Distinct organization_id per call — see the identical note on
        # `test_list_subscriptions_paginates_and_reports_total` above (including the Founder
        # actor, for the same ADR-0021 `_enforce_own_organization` reason).
        first = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id="org-sort-1",
                plan_id=plan_id,
                actor=make_founder_actor(),
            ),
            uow=uow,
        )
        second = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id="org-sort-2",
                plan_id=plan_id,
                actor=make_founder_actor(),
            ),
            uow=uow,
        )
        await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id="org-sort-3",
                plan_id=plan_id,
                actor=make_founder_actor(),
            ),
            uow=uow,
        )
        await service.suspend_subscription(
            SuspendSubscriptionCommand(
                subscription_id=first.subscription_id, actor=make_actor()
            ),
            uow=uow,
        )
        await service.cancel_subscription(
            CancelSubscriptionCommand(
                subscription_id=second.subscription_id, actor=make_actor()
            ),
            uow=uow,
        )
        # third subscription is left "trial" - alphabetically: cancelled < suspended < trial.

        page = await service.list_subscriptions(
            ListSubscriptionsQuery(
                page_request=OffsetPageRequest(),
                sort=[SortSpec(field="status", descending=False)],
            ),
            uow=uow,
        )
        self.assertEqual([s.status for s in page.data], ["cancelled", "suspended", "trial"])


class InvoicePaginationApplicationTests(unittest.IsolatedAsyncioTestCase):
    """`GET /billing/invoices` pagination/filtering/sorting (API Contracts §7/§8). Sort test
    uses `status`, not `amount` - `_field_text`'s generic string-based comparison (this file's
    in-memory `list_page` equivalent) does not sort a `Money` value object numerically, so a
    string-typed field is the only one that reliably matches real Postgres numeric-column
    ordering behavior here."""

    async def _make_subscription(
        self, service: BillingApplicationService, uow
    ) -> tuple[str, str]:
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Org Plan",
                billing_scope="organization",
                amount=100.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        renewal = await service.open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                plan_id=plan.id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        return plan.id, renewal.subscription_id

    async def test_list_invoices_paginates_and_reports_total(self) -> None:
        service = make_service()
        uow = make_uow()
        _plan_id, subscription_id = await self._make_subscription(service, uow)
        # open_organization_subscription already issued one invoice - issue two more for a total of 3.
        for i in range(2):
            await service.issue_invoice(
                IssueInvoiceCommand(
                    organization_id=VALID_ORG_ULID,
                    subscription_id=subscription_id,
                    amount=100.00,
                    currency="USD",
                    period_start=date(2026, 8 + i, 1),
                    period_end=date(2026, 8 + i, 28),
                    due_at=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await service.list_invoices(
            ListInvoicesQuery(page_request=OffsetPageRequest(page=1, page_size=2)), uow=uow
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_invoices_filters_by_status(self) -> None:
        service = make_service()
        uow = make_uow()
        _plan_id, subscription_id = await self._make_subscription(service, uow)
        second = await service.issue_invoice(
            IssueInvoiceCommand(
                organization_id=VALID_ORG_ULID,
                subscription_id=subscription_id,
                amount=50.00,
                currency="USD",
                period_start=date(2026, 9, 1),
                period_end=date(2026, 9, 28),
                due_at=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.void_invoice(
            VoidInvoiceCommand(invoice_id=second.id, actor=make_actor()), uow=uow
        )

        page = await service.list_invoices(
            ListInvoicesQuery(
                page_request=OffsetPageRequest(),
                filters=[FilterCondition(field="status", op="eq", value="void")],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].id, second.id)

    async def test_list_invoices_sorts_descending_by_status(self) -> None:
        service = make_service()
        uow = make_uow()
        _plan_id, subscription_id = await self._make_subscription(service, uow)
        second = await service.issue_invoice(
            IssueInvoiceCommand(
                organization_id=VALID_ORG_ULID,
                subscription_id=subscription_id,
                amount=50.00,
                currency="USD",
                period_start=date(2026, 9, 1),
                period_end=date(2026, 9, 28),
                due_at=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.void_invoice(
            VoidInvoiceCommand(invoice_id=second.id, actor=make_actor()), uow=uow
        )
        # renewal's own invoice stays "issued"; `second` is now "void" - descending: void > issued.

        page = await service.list_invoices(
            ListInvoicesQuery(
                page_request=OffsetPageRequest(),
                sort=[SortSpec(field="status", descending=True)],
            ),
            uow=uow,
        )
        self.assertEqual([inv.status for inv in page.data], ["void", "issued"])


class BillingStatsApplicationTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0020: `get_billing_stats`, backing `platform_audit.PlatformStatsApplicationService`.
    Subscriptions/invoices are constructed directly (not via the full command flow) — the same
    "seed the fake repository straight" shortcut `AccountLockoutApplicationTests`-style tests
    elsewhere in this codebase already use when the aggregate's own constructor is simple
    enough to call directly."""

    @staticmethod
    def _make_subscription(
        *, id_generator: IdGenerator, status: SubscriptionStatus, current_period_end: datetime | None
    ) -> Subscription:
        return Subscription(
            id=SubscriptionId(id_generator.new_id()),
            organization_id=OrganizationId(VALID_ORG_ULID),
            plan_id=PlanId(VALID_ORG_ULID),
            status=status,
            current_period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            current_period_end=current_period_end,
            auto_renew=True,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    @staticmethod
    def _make_invoice(
        *,
        id_generator: IdGenerator,
        status: InvoiceStatus,
        amount: float,
        paid_at: datetime | None,
    ) -> Invoice:
        invoice_id = id_generator.new_id()
        return Invoice(
            id=InvoiceId(invoice_id),
            organization_id=OrganizationId(VALID_ORG_ULID),
            subscription_id=SubscriptionId(id_generator.new_id()),
            number=invoice_id,
            amount=Money(amount=amount, currency="USD"),
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 28),
            status=status,
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            due_at=None,
            paid_at=paid_at,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    async def test_reports_status_breakdown_expiring_and_revenue(self) -> None:
        service = make_service()
        uow = make_uow()
        ids = SequentialIdGenerator()
        uow.subscriptions.add(
            self._make_subscription(
                id_generator=ids,
                status=SubscriptionStatus.ACTIVE,
                current_period_end=datetime(2026, 1, 15, tzinfo=timezone.utc),
            )
        )
        uow.subscriptions.add(
            self._make_subscription(
                id_generator=ids,
                status=SubscriptionStatus.ACTIVE,
                current_period_end=datetime(2026, 6, 1, tzinfo=timezone.utc),
            )
        )
        uow.subscriptions.add(
            self._make_subscription(
                id_generator=ids, status=SubscriptionStatus.CANCELLED, current_period_end=None
            )
        )
        uow.invoices.add(
            self._make_invoice(
                id_generator=ids,
                status=InvoiceStatus.PAID,
                amount=100.0,
                paid_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
            )
        )
        uow.invoices.add(
            self._make_invoice(
                id_generator=ids,
                status=InvoiceStatus.PAID,
                amount=50.0,
                paid_at=datetime(2026, 2, 1, tzinfo=timezone.utc),  # outside the window
            )
        )
        uow.invoices.add(
            self._make_invoice(
                id_generator=ids, status=InvoiceStatus.ISSUED, amount=75.0, paid_at=None
            )
        )

        stats = await service.get_billing_stats(
            expiring_window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expiring_window_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            revenue_window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            revenue_window_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            uow=uow,
        )

        self.assertEqual(stats.subscription_by_status, {"active": 2, "cancelled": 1})
        self.assertEqual(stats.expiring_soon, 1)  # only the Jan 15 one is within the window
        self.assertEqual(stats.revenue, 100.0)  # only the Jan-paid invoice is within the window

    async def test_active_by_billing_cycle_joins_plan_and_excludes_terminal_and_cancelled(
        self,
    ) -> None:
        """Organization Management phase — Platform Finance "Monthly vs Annual Subscribers"."""
        service = make_service()
        uow = make_uow()
        ids = SequentialIdGenerator()

        monthly_plan = await service.create_plan(
            CreatePlanCommand(
                name="Monthly",
                billing_scope="organization",
                amount=10.0,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        annual_plan = await service.create_plan(
            CreatePlanCommand(
                name="Annual",
                billing_scope="organization",
                amount=100.0,
                currency="USD",
                billing_cycle="annual",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )

        def _sub(*, status: SubscriptionStatus, plan_id: str) -> Subscription:
            return Subscription(
                id=SubscriptionId(ids.new_id()),
                organization_id=OrganizationId(VALID_ORG_ULID),
                plan_id=PlanId(plan_id),
                status=status,
                current_period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                current_period_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
                auto_renew=True,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

        uow.subscriptions.add(_sub(status=SubscriptionStatus.ACTIVE, plan_id=monthly_plan.id))
        uow.subscriptions.add(_sub(status=SubscriptionStatus.TRIAL, plan_id=monthly_plan.id))
        uow.subscriptions.add(_sub(status=SubscriptionStatus.ACTIVE, plan_id=annual_plan.id))
        # Cancelled must not count, even though it's on a real plan.
        uow.subscriptions.add(_sub(status=SubscriptionStatus.CANCELLED, plan_id=annual_plan.id))

        stats = await service.get_billing_stats(
            expiring_window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expiring_window_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            revenue_window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            revenue_window_end=datetime(2026, 1, 31, tzinfo=timezone.utc),
            uow=uow,
        )

        self.assertEqual(stats.active_by_billing_cycle, {"monthly": 2, "annual": 1})


if __name__ == "__main__":
    unittest.main()
