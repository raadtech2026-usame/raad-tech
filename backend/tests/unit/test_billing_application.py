"""Application-layer tests for `billing`'s `BillingApplicationService` (Phase 15). Stdlib
`unittest` — no `pytest` (not an approved dependency), mirroring
`test_transport_ops_trip_application.py`'s exact structure. Uses in-memory fakes for all five
repositories bundled onto one fake `BillingUnitOfWork`, plus a fake `PaymentProviderPort` — no
SQLAlchemy, no FastAPI, no real database.

Covers: Plan CRUD-lite, `renew_parent_subscription`'s open-or-reuse orchestration, Subscription
status transitions, Invoice issuance/void, Payment idempotency (find-or-return), the documented
"no provider bound -> NotImplementedError at the charge step, Payment already persisted as
PENDING" behavior, the successful-charge path with a bound fake provider,
`handle_payment_callback`'s paid/failed cascades (paid: Invoice.mark_paid + Subscription.renew in
the same transaction; failed: only Payment mutated, Invoice left untouched — the resolved
Invoice-vs-Payment "FAILED" conflict), and TransportFee CRUD-lite.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from raad.core.errors.exceptions import DomainError, NotFoundError
from raad.core.ids.generator import IdGenerator
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
    PaymentCallbackCommand,
    RenewParentSubscriptionCommand,
    SuspendSubscriptionCommand,
    VoidInvoiceCommand,
    WaiveTransportFeeCommand,
)
from raad.modules.billing.application.ports import BillingUnitOfWork, PaymentProviderPort
from raad.modules.billing.application.queries import (
    GetInvoiceByIdQuery,
    GetPaymentByIdQuery,
    GetPlanByIdQuery,
    GetSubscriptionByIdQuery,
    GetTransportFeeByIdQuery,
    ListInvoicesQuery,
    ListPaymentsQuery,
    ListPlansQuery,
    ListSubscriptionsQuery,
    ListTransportFeesQuery,
)
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.billing.domain.entities import (
    Invoice,
    Payment,
    Plan,
    Subscription,
    TransportFee,
)
from raad.modules.billing.domain.repositories import (
    InvoiceRepository,
    PaymentRepository,
    PlanRepository,
    SubscriptionRepository,
    TransportFeeRepository,
)
from raad.modules.billing.domain.value_objects import (
    InvoiceId,
    Money,
    PaymentId,
    PlanId,
    SubscriberId,
    SubscriberType,
    SubscriptionId,
    TransportFeeId,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
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


def make_actor(org_id: str = VALID_ORG_ULID) -> Principal:
    return Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=org_id)


class InMemoryPlanRepository(PlanRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Plan] = {}

    async def get(self, plan_id: PlanId) -> Plan | None:
        return self.by_id.get(str(plan_id))

    def add(self, plan: Plan) -> None:
        self.by_id[str(plan.id)] = plan

    async def list_all(self) -> list[Plan]:
        return list(self.by_id.values())


class InMemorySubscriptionRepository(SubscriptionRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Subscription] = {}

    async def get(self, subscription_id: SubscriptionId) -> Subscription | None:
        return self.by_id.get(str(subscription_id))

    def add(self, subscription: Subscription) -> None:
        self.by_id[str(subscription.id)] = subscription

    async def list_all(self) -> list[Subscription]:
        return list(self.by_id.values())

    async def get_active_by_subscriber(
        self, subscriber_type: SubscriberType, subscriber_id: SubscriberId
    ) -> Subscription | None:
        return next(
            (
                s
                for s in self.by_id.values()
                if s.subscriber_type == subscriber_type
                and str(s.subscriber_id) == str(subscriber_id)
                and s.status.value in ("trial", "active", "suspended")
            ),
            None,
        )


class InMemoryInvoiceRepository(InvoiceRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Invoice] = {}

    async def get(self, invoice_id: InvoiceId) -> Invoice | None:
        return self.by_id.get(str(invoice_id))

    def add(self, invoice: Invoice) -> None:
        self.by_id[str(invoice.id)] = invoice

    async def list_all(self) -> list[Invoice]:
        return list(self.by_id.values())


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


class InMemoryTransportFeeRepository(TransportFeeRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, TransportFee] = {}

    async def get(self, transport_fee_id: TransportFeeId) -> TransportFee | None:
        return self.by_id.get(str(transport_fee_id))

    def add(self, transport_fee: TransportFee) -> None:
        self.by_id[str(transport_fee.id)] = transport_fee

    async def list_all(self) -> list[TransportFee]:
        return list(self.by_id.values())


class FakeBillingUnitOfWork(BillingUnitOfWork):
    def __init__(
        self,
        plans: InMemoryPlanRepository,
        subscriptions: InMemorySubscriptionRepository,
        invoices: InMemoryInvoiceRepository,
        payments: InMemoryPaymentRepository,
        transport_fees: InMemoryTransportFeeRepository,
    ) -> None:
        self.plans = plans
        self.subscriptions = subscriptions
        self.invoices = invoices
        self.payments = payments
        self.transport_fees = transport_fees
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
    def __init__(self, provider_ref: str = "EVC-REF-999") -> None:
        self.provider_ref = provider_ref
        self.charge_calls: list[dict] = []

    async def charge(self, *, amount: Money, msisdn: str, reference: str) -> str:
        self.charge_calls.append(
            {"amount": amount, "msisdn": msisdn, "reference": reference}
        )
        return self.provider_ref


def make_uow() -> FakeBillingUnitOfWork:
    return FakeBillingUnitOfWork(
        InMemoryPlanRepository(),
        InMemorySubscriptionRepository(),
        InMemoryInvoiceRepository(),
        InMemoryPaymentRepository(),
        InMemoryTransportFeeRepository(),
    )


def make_service(provider: PaymentProviderPort | None = None) -> BillingApplicationService:
    return BillingApplicationService(
        clock=CLOCK, id_generator=SequentialIdGenerator(), payment_provider=provider
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
        plans = await service.list_plans(ListPlansQuery(), uow=uow)
        self.assertEqual(len(plans), 1)


class SubscriptionApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def _make_plan(self, service: BillingApplicationService, uow) -> str:
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Parent Plan",
                billing_scope="parent",
                amount=10.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        return plan.id

    async def test_renew_parent_subscription_opens_new_subscription_and_issues_invoice(
        self,
    ) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)

        invoice = await service.renew_parent_subscription(
            RenewParentSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                parent_id="parent-ref-001",
                plan_id=plan_id,
                msisdn="+2526000000",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(invoice.status, "issued")
        self.assertEqual(len(uow.subscriptions.by_id), 1)
        self.assertEqual(len(uow.invoices.by_id), 1)

    async def test_renew_parent_subscription_reuses_existing_active_subscription(
        self,
    ) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        command = RenewParentSubscriptionCommand(
            organization_id=VALID_ORG_ULID,
            parent_id="parent-ref-002",
            plan_id=plan_id,
            msisdn="+2526000000",
            actor=make_actor(),
        )
        await service.renew_parent_subscription(command, uow=uow)
        self.assertEqual(len(uow.subscriptions.by_id), 1)

        await service.renew_parent_subscription(command, uow=uow)
        self.assertEqual(
            len(uow.subscriptions.by_id), 1, "second renewal must reuse, not duplicate"
        )
        self.assertEqual(len(uow.invoices.by_id), 2, "each renewal issues its own invoice")

    async def test_renew_parent_subscription_missing_plan_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.renew_parent_subscription(
                RenewParentSubscriptionCommand(
                    organization_id=VALID_ORG_ULID,
                    parent_id="parent-ref-003",
                    plan_id=NON_EXISTENT_ID,
                    msisdn="+2526000000",
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_expire_suspend_cancel_subscription(self) -> None:
        service = make_service()
        uow = make_uow()
        plan_id = await self._make_plan(service, uow)
        invoice = await service.renew_parent_subscription(
            RenewParentSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                parent_id="parent-ref-004",
                plan_id=plan_id,
                msisdn="+2526000000",
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
        await service.renew_parent_subscription(
            RenewParentSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                parent_id="parent-ref-005",
                plan_id=plan_id,
                msisdn="+2526000000",
                actor=make_actor(),
            ),
            uow=uow,
        )
        subscriptions = await service.list_subscriptions(ListSubscriptionsQuery(), uow=uow)
        self.assertEqual(len(subscriptions), 1)


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
        renewal = await service.renew_parent_subscription(
            RenewParentSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                parent_id="parent-ref-006",
                plan_id=plan.id,
                msisdn="+2526000000",
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


class PaymentApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def _make_invoice(self, uow) -> str:
        service = make_service()
        plan = await service.create_plan(
            CreatePlanCommand(
                name="Parent Plan",
                billing_scope="parent",
                amount=25.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        invoice = await service.renew_parent_subscription(
            RenewParentSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                parent_id="parent-ref-payment",
                plan_id=plan.id,
                msisdn="+2526000000",
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


class TransportFeeApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_mark_paid_overdue_waive_lifecycle(self) -> None:
        service = make_service()
        uow = make_uow()
        fee = await service.create_transport_fee(
            CreateTransportFeeCommand(
                organization_id=VALID_ORG_ULID,
                student_id="student-ref-001",
                period="2026-07",
                amount=20.00,
                currency="USD",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(fee.status, "due")

        overdue = await service.mark_transport_fee_overdue(
            MarkTransportFeeOverdueCommand(transport_fee_id=fee.id, actor=make_actor()),
            uow=uow,
        )
        self.assertEqual(overdue.status, "overdue")

        paid = await service.mark_transport_fee_paid(
            MarkTransportFeePaidCommand(transport_fee_id=fee.id, actor=make_actor()), uow=uow
        )
        self.assertEqual(paid.status, "paid")

    async def test_waive_transport_fee(self) -> None:
        service = make_service()
        uow = make_uow()
        fee = await service.create_transport_fee(
            CreateTransportFeeCommand(
                organization_id=VALID_ORG_ULID,
                student_id="student-ref-002",
                period="2026-08",
                amount=20.00,
                currency="USD",
                actor=make_actor(),
            ),
            uow=uow,
        )
        waived = await service.waive_transport_fee(
            WaiveTransportFeeCommand(transport_fee_id=fee.id, actor=make_actor()), uow=uow
        )
        self.assertEqual(waived.status, "waived")

    async def test_get_transport_fee_by_id_not_found_raises(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.get_transport_fee_by_id(
                GetTransportFeeByIdQuery(transport_fee_id=NON_EXISTENT_ID), uow=uow
            )

    async def test_list_transport_fees_returns_all(self) -> None:
        service = make_service()
        uow = make_uow()
        await service.create_transport_fee(
            CreateTransportFeeCommand(
                organization_id=VALID_ORG_ULID,
                student_id="student-ref-003",
                period="2026-09",
                amount=20.00,
                currency="USD",
                actor=make_actor(),
            ),
            uow=uow,
        )
        fees = await service.list_transport_fees(ListTransportFeesQuery(), uow=uow)
        self.assertEqual(len(fees), 1)


class ScheduledJobApplicationTests(unittest.IsolatedAsyncioTestCase):
    """`sweep_expired_subscriptions`/`reconcile_expired_payments` (Backend Stabilization phase)
    — the subscription-status-sweep and payment-reconciliation scheduled jobs' own entry
    points. Uses two `BillingApplicationService` instances sharing one fake `uow`, each with
    its own `FixedClock`, to simulate "time passing" between creation and the sweep."""

    async def test_sweep_expired_subscriptions_expires_past_period_end(self) -> None:
        """A `Subscription` only gets a real `current_period_end` once a payment actually
        succeeds (`handle_payment_callback(status="paid")` calls `Subscription.renew()`,
        `application/services.py`'s own module docstring) — `renew_parent_subscription` alone
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
                billing_scope="parent",
                amount=10.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        renewal = await early_service.renew_parent_subscription(
            RenewParentSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                parent_id="parent-ref-sweep-1",
                plan_id=plan.id,
                msisdn="+2526000000",
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
                billing_scope="parent",
                amount=10.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        renewal = await service.renew_parent_subscription(
            RenewParentSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                parent_id="parent-ref-sweep-2",
                plan_id=plan.id,
                msisdn="+2526000000",
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
                billing_scope="parent",
                amount=25.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        invoice = await early_service.renew_parent_subscription(
            RenewParentSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                parent_id="parent-ref-reconcile-1",
                plan_id=plan.id,
                msisdn="+2526000000",
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
                billing_scope="parent",
                amount=25.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        invoice = await service.renew_parent_subscription(
            RenewParentSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                parent_id="parent-ref-reconcile-2",
                plan_id=plan.id,
                msisdn="+2526000000",
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
                billing_scope="parent",
                amount=25.00,
                currency="USD",
                billing_cycle="monthly",
                vehicle_limit=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        invoice = await service.renew_parent_subscription(
            RenewParentSubscriptionCommand(
                organization_id=VALID_ORG_ULID,
                parent_id="parent-ref-reconcile-3",
                plan_id=plan.id,
                msisdn="+2526000000",
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


if __name__ == "__main__":
    unittest.main()
