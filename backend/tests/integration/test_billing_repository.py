"""PostgreSQL-backed integration test for `billing`'s `SqlAlchemyBillingUnitOfWork`/five
repositories (Phase 15). Stdlib `unittest` — no `pytest` (not an approved dependency), using
`unittest.IsolatedAsyncioTestCase` against the real `SqlAlchemyBillingUnitOfWork` and the live
migrated schema (Alembic head `addb6114f18a`), not fakes — mirroring
`test_transport_ops_trip_repository.py`'s skip-guard/cleanup pattern exactly.

Covers what no in-memory unit test can prove: the round trip through the real identity-map/
`flush_tracked_changes` mechanics for all five aggregates, `SubscriptionRepository.
get_active_by_subscriber`'s direct-`select()` correctness, and `PaymentRepository.
get_by_idempotency_key`'s direct-`select()` correctness. The DB-level uniqueness proof of
`ux_payments__idempotency_key`/`ux_payments__provider_provider_ref`/`ux_invoices__number` lives
in `test_postgres_repository_invariants.py`, not duplicated here.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run
marker and deletes them in `tearDown` in FK-respecting order (payments before invoices before
subscriptions before plans; transport_fees independently), leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import ValidationError
from raad.core.events.outbox import OutboxWriter
from raad.core.audit.writer import AuditWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.time.clock import SystemClock
from raad.modules.billing.domain.entities import Invoice, Payment, Plan, Subscription, TransportFee
from raad.modules.billing.domain.value_objects import (
    BillingCycle,
    BillingScope,
    InvoiceId,
    Money,
    OrganizationId,
    PaymentId,
    PlanId,
    StudentId,
    SubscriberId,
    SubscriberType,
    SubscriptionId,
    TransportFeeId,
)
from raad.modules.billing.infra.repositories import SqlAlchemyBillingUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class BillingRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_payment_ids: list[str] = []
        self._created_invoice_ids: list[str] = []
        self._created_subscription_ids: list[str] = []
        self._created_plan_ids: list[str] = []
        self._created_transport_fee_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_payment_ids:
                await conn.execute(
                    text("DELETE FROM payments WHERE id = ANY(:ids)"),
                    {"ids": self._created_payment_ids},
                )
            if self._created_invoice_ids:
                await conn.execute(
                    text("DELETE FROM invoices WHERE id = ANY(:ids)"),
                    {"ids": self._created_invoice_ids},
                )
            if self._created_subscription_ids:
                await conn.execute(
                    text("DELETE FROM subscriptions WHERE id = ANY(:ids)"),
                    {"ids": self._created_subscription_ids},
                )
            if self._created_plan_ids:
                await conn.execute(
                    text("DELETE FROM plans WHERE id = ANY(:ids)"),
                    {"ids": self._created_plan_ids},
                )
            if self._created_transport_fee_ids:
                await conn.execute(
                    text("DELETE FROM transport_fees WHERE id = ANY(:ids)"),
                    {"ids": self._created_transport_fee_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyBillingUnitOfWork:
        return SqlAlchemyBillingUnitOfWork(self.session_factory, self.outbox_writer, self.audit_writer)

    async def _seed_plan(self, uow: SqlAlchemyBillingUnitOfWork) -> PlanId:
        plan = Plan.create(
            id=PlanId(self.id_generator.new_id()),
            name=f"Plan {self.tag}",
            billing_scope=BillingScope.PARENT,
            price=Money(15.00, "USD"),
            billing_cycle=BillingCycle.MONTHLY,
            clock=self.clock,
        )
        uow.plans.add(plan)
        uow.record_events(plan.pull_domain_events())
        await uow.commit()
        self._created_plan_ids.append(str(plan.id))
        return plan.id

    async def _seed_subscription(
        self, uow: SqlAlchemyBillingUnitOfWork, org_id: str, plan_id: PlanId
    ) -> SubscriptionId:
        subscription = Subscription.open(
            id=SubscriptionId(self.id_generator.new_id()),
            organization_id=OrganizationId(org_id),
            subscriber_type=SubscriberType.PARENT,
            subscriber_id=SubscriberId(self.id_generator.new_id()),
            plan_id=plan_id,
            clock=self.clock,
        )
        uow.subscriptions.add(subscription)
        uow.record_events(subscription.pull_domain_events())
        await uow.commit()
        self._created_subscription_ids.append(str(subscription.id))
        return subscription.id

    async def _seed_invoice(
        self, uow: SqlAlchemyBillingUnitOfWork, org_id: str, subscription_id: SubscriptionId
    ) -> Invoice:
        invoice = Invoice.issue(
            id=InvoiceId(self.id_generator.new_id()),
            organization_id=OrganizationId(org_id),
            subscription_id=subscription_id,
            amount=Money(15.00, "USD"),
            period_start=date(2026, 7, 20),
            period_end=date(2026, 8, 19),
            due_at=None,
            clock=self.clock,
        )
        uow.invoices.add(invoice)
        uow.record_events(invoice.pull_domain_events())
        await uow.commit()
        self._created_invoice_ids.append(str(invoice.id))
        return invoice

    async def test_plan_add_then_get_round_trips(self) -> None:
        async with self._new_uow() as uow:
            plan_id = await self._seed_plan(uow)

        async with self._new_uow() as uow:
            fetched = await uow.plans.get(plan_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.id), str(plan_id))
        self.assertEqual(fetched.status.value, "active")

    async def test_plan_mutation_after_get_persists_without_a_second_add(self) -> None:
        async with self._new_uow() as uow:
            plan_id = await self._seed_plan(uow)

        async with self._new_uow() as uow:
            loaded = await uow.plans.get(plan_id)
            loaded.disable(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.plans.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.plans.get(plan_id)

        self.assertEqual(refetched.status.value, "inactive")

    async def test_subscription_add_then_get_round_trips(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            plan_id = await self._seed_plan(uow)
            subscription_id = await self._seed_subscription(uow, org_id, plan_id)

        async with self._new_uow() as uow:
            fetched = await uow.subscriptions.get(subscription_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(fetched.status.value, "trial")

    async def test_get_active_by_subscriber_finds_non_terminal_subscription(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            plan_id = await self._seed_plan(uow)
            subscription = Subscription.open(
                id=SubscriptionId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                subscriber_type=SubscriberType.PARENT,
                subscriber_id=SubscriberId(f"subscriber-{self.tag}"),
                plan_id=plan_id,
                clock=self.clock,
            )
            uow.subscriptions.add(subscription)
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()
            self._created_subscription_ids.append(str(subscription.id))

        async with self._new_uow() as uow:
            found = await uow.subscriptions.get_active_by_subscriber(
                SubscriberType.PARENT, SubscriberId(f"subscriber-{self.tag}")
            )
        self.assertIsNotNone(found)
        self.assertEqual(str(found.id), str(subscription.id))

    async def test_get_active_by_subscriber_excludes_cancelled(self) -> None:
        org_id = self.id_generator.new_id()
        subscriber_id = SubscriberId(f"cancelled-{self.tag}")
        async with self._new_uow() as uow:
            plan_id = await self._seed_plan(uow)
            subscription = Subscription.open(
                id=SubscriptionId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                subscriber_type=SubscriberType.PARENT,
                subscriber_id=subscriber_id,
                plan_id=plan_id,
                clock=self.clock,
            )
            subscription.cancel(clock=self.clock)
            uow.subscriptions.add(subscription)
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()
            self._created_subscription_ids.append(str(subscription.id))

        async with self._new_uow() as uow:
            found = await uow.subscriptions.get_active_by_subscriber(
                SubscriberType.PARENT, subscriber_id
            )
        self.assertIsNone(found)

    async def test_invoice_add_then_get_round_trips(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            plan_id = await self._seed_plan(uow)
            subscription_id = await self._seed_subscription(uow, org_id, plan_id)
            invoice = await self._seed_invoice(uow, org_id, subscription_id)

        async with self._new_uow() as uow:
            fetched = await uow.invoices.get(invoice.id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.number, str(invoice.id))
        self.assertEqual(fetched.status.value, "issued")

    async def test_payment_add_then_get_round_trips(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            plan_id = await self._seed_plan(uow)
            subscription_id = await self._seed_subscription(uow, org_id, plan_id)
            invoice = await self._seed_invoice(uow, org_id, subscription_id)

        async with self._new_uow() as uow:
            payment = Payment.initiate(
                id=PaymentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                invoice_id=invoice.id,
                provider="evcplus",
                msisdn_masked="+2526••••••",
                amount=Money(15.00, "USD"),
                idempotency_key=f"idem-{self.tag}",
                clock=self.clock,
            )
            uow.payments.add(payment)
            uow.record_events(payment.pull_domain_events())
            await uow.commit()
            self._created_payment_ids.append(str(payment.id))

        async with self._new_uow() as uow:
            fetched = await uow.payments.get(payment.id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.status.value, "pending")
        self.assertEqual(fetched.idempotency_key, f"idem-{self.tag}")

    async def test_get_by_idempotency_key_finds_the_payment(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            plan_id = await self._seed_plan(uow)
            subscription_id = await self._seed_subscription(uow, org_id, plan_id)
            invoice = await self._seed_invoice(uow, org_id, subscription_id)

        idempotency_key = f"idem-lookup-{self.tag}"
        async with self._new_uow() as uow:
            payment = Payment.initiate(
                id=PaymentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                invoice_id=invoice.id,
                provider="evcplus",
                msisdn_masked=None,
                amount=Money(15.00, "USD"),
                idempotency_key=idempotency_key,
                clock=self.clock,
            )
            uow.payments.add(payment)
            uow.record_events(payment.pull_domain_events())
            await uow.commit()
            self._created_payment_ids.append(str(payment.id))

        async with self._new_uow() as uow:
            found = await uow.payments.get_by_idempotency_key(idempotency_key)
            not_found = await uow.payments.get_by_idempotency_key(f"nonexistent-{self.tag}")

        self.assertIsNotNone(found)
        self.assertEqual(str(found.id), str(payment.id))
        self.assertIsNone(not_found)

    async def test_payment_mutation_after_get_persists_without_a_second_add(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            plan_id = await self._seed_plan(uow)
            subscription_id = await self._seed_subscription(uow, org_id, plan_id)
            invoice = await self._seed_invoice(uow, org_id, subscription_id)

        async with self._new_uow() as uow:
            payment = Payment.initiate(
                id=PaymentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                invoice_id=invoice.id,
                provider="evcplus",
                msisdn_masked=None,
                amount=Money(15.00, "USD"),
                idempotency_key=f"idem-mutate-{self.tag}",
                clock=self.clock,
            )
            uow.payments.add(payment)
            uow.record_events(payment.pull_domain_events())
            await uow.commit()
            self._created_payment_ids.append(str(payment.id))

        async with self._new_uow() as uow:
            loaded = await uow.payments.get(payment.id)
            loaded.mark_paid(provider_ref="EVC-REF-XYZ", clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.payments.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.payments.get(payment.id)

        self.assertEqual(refetched.status.value, "paid")
        self.assertEqual(refetched.provider_ref, "EVC-REF-XYZ")

    async def test_transport_fee_add_then_get_round_trips(self) -> None:
        org_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            fee = TransportFee.create(
                id=TransportFeeId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                student_id=StudentId(self.id_generator.new_id()),
                period="2026-07",
                amount=Money(20.00, "USD"),
                clock=self.clock,
            )
            uow.transport_fees.add(fee)
            uow.record_events(fee.pull_domain_events())
            await uow.commit()
            self._created_transport_fee_ids.append(str(fee.id))

        async with self._new_uow() as uow:
            fetched = await uow.transport_fees.get(fee.id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.status.value, "due")


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class PlanPaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemyPlanRepository.list_page` (`core/db/repository.py`'s `list_page`)
    against real SQL — mirrors `test_organization_repository.py`'s
    `OrganizationPaginationRepositoryTests` structure. `PlanModel` has no `organization_id`
    (`infra/models.py`'s own docstring), so — unlike `Invoice`/`Subscription` below — no parent
    row needs seeding first; isolation from other concurrently-running tests/seed data is via
    `search`/`self.tag` (a random per-run marker) rather than a tenant/parent filter, since no
    tenant column exists to filter by at all.
    """

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_plan_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_plan_ids:
                await conn.execute(
                    text("DELETE FROM plans WHERE id = ANY(:ids)"),
                    {"ids": self._created_plan_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyBillingUnitOfWork:
        return SqlAlchemyBillingUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed_plan(
        self, *, name: str, billing_scope: BillingScope = BillingScope.ORGANIZATION
    ) -> PlanId:
        async with self._new_uow() as uow:
            plan = Plan.create(
                id=PlanId(self.id_generator.new_id()),
                name=name,
                billing_scope=billing_scope,
                price=Money(15.00, "USD"),
                billing_cycle=BillingCycle.MONTHLY,
                clock=self.clock,
            )
            uow.plans.add(plan)
            uow.record_events(plan.pull_domain_events())
            await uow.commit()
            self._created_plan_ids.append(str(plan.id))
            return plan.id

    async def test_list_page_paginates_and_reports_total(self) -> None:
        for i in range(3):
            await self._seed_plan(name=f"Page Plan {self.tag} {i}")

        async with self._new_uow() as uow:
            page = await uow.plans.list_page(
                OffsetPageRequest(page=1, page_size=2),
                sort=[SortSpec(field="name")],
                filters=[],
                search=f"Page Plan {self.tag}",
            )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_page_filters_by_billing_scope(self) -> None:
        await self._seed_plan(
            name=f"Org Plan {self.tag}", billing_scope=BillingScope.ORGANIZATION
        )
        await self._seed_plan(
            name=f"Parent Plan {self.tag}", billing_scope=BillingScope.PARENT
        )

        async with self._new_uow() as uow:
            page = await uow.plans.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[FilterCondition(field="billing_scope", op="eq", value="parent")],
                search=self.tag,
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].name, f"Parent Plan {self.tag}")

    async def test_list_page_search_matches_name_substring(self) -> None:
        await self._seed_plan(name=f"Findable-{self.tag}")
        await self._seed_plan(name=f"Other-{self.tag}")

        async with self._new_uow() as uow:
            page = await uow.plans.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[],
                search=f"findable-{self.tag}",
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].name, f"Findable-{self.tag}")

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.plans.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[FilterCondition(field="vehicle_limit", op="eq", value="5")],
                    search=None,
                )

    async def test_list_page_rejects_non_whitelisted_sort_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.plans.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="id")],
                    filters=[],
                    search=None,
                )


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class SubscriptionPaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemySubscriptionRepository.list_page` against real SQL. Isolates each
    test's rows by filtering on `subscriber_id` (each seeded with a `self.tag`-unique value) -
    the same "filter on a value only this test's own rows can have" isolation
    `InvoicePaginationRepositoryTests` uses via `subscription_id` below.
    `SqlAlchemySubscriptionRepository.searchable_fields` is empty (`infra/repositories.py`), so
    no search test exists here, matching that deliberate no-search-field posture."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_subscription_ids: list[str] = []
        self._created_plan_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_subscription_ids:
                await conn.execute(
                    text("DELETE FROM subscriptions WHERE id = ANY(:ids)"),
                    {"ids": self._created_subscription_ids},
                )
            if self._created_plan_ids:
                await conn.execute(
                    text("DELETE FROM plans WHERE id = ANY(:ids)"),
                    {"ids": self._created_plan_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyBillingUnitOfWork:
        return SqlAlchemyBillingUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed_plan(self) -> PlanId:
        async with self._new_uow() as uow:
            plan = Plan.create(
                id=PlanId(self.id_generator.new_id()),
                name=f"Subscription Page Plan {self.tag}",
                billing_scope=BillingScope.PARENT,
                price=Money(15.00, "USD"),
                billing_cycle=BillingCycle.MONTHLY,
                clock=self.clock,
            )
            uow.plans.add(plan)
            uow.record_events(plan.pull_domain_events())
            await uow.commit()
            self._created_plan_ids.append(str(plan.id))
            return plan.id

    async def _seed_subscription(
        self, plan_id: PlanId, *, subscriber_suffix: str
    ) -> Subscription:
        async with self._new_uow() as uow:
            subscription = Subscription.open(
                id=SubscriptionId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                subscriber_type=SubscriberType.PARENT,
                subscriber_id=SubscriberId(f"{self.tag}-{subscriber_suffix}"),
                plan_id=plan_id,
                clock=self.clock,
            )
            uow.subscriptions.add(subscription)
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()
            self._created_subscription_ids.append(str(subscription.id))
            return subscription

    async def test_list_page_paginates_and_reports_total(self) -> None:
        plan_id = await self._seed_plan()
        for i in range(3):
            await self._seed_subscription(plan_id, subscriber_suffix=f"p-{i}")

        async with self._new_uow() as uow:
            page = await uow.subscriptions.list_page(
                OffsetPageRequest(page=1, page_size=2),
                sort=[SortSpec(field="created_at")],
                filters=[
                    FilterCondition(
                        field="subscriber_id",
                        op="in",
                        value=",".join(
                            f"{self.tag}-p-{i}" for i in range(3)
                        ),
                    )
                ],
                search=None,
            )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_page_filters_by_status(self) -> None:
        plan_id = await self._seed_plan()
        active = await self._seed_subscription(plan_id, subscriber_suffix="active")
        suspended = await self._seed_subscription(plan_id, subscriber_suffix="suspended")

        async with self._new_uow() as uow:
            loaded = await uow.subscriptions.get(suspended.id)
            loaded.suspend(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            page = await uow.subscriptions.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[
                    FilterCondition(
                        field="subscriber_id",
                        op="in",
                        value=",".join(
                            [
                                f"{self.tag}-active",
                                f"{self.tag}-suspended",
                            ]
                        ),
                    ),
                    FilterCondition(field="status", op="eq", value="suspended"),
                ],
                search=None,
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(str(page.data[0].id), str(suspended.id))
        self.assertIsNotNone(active)

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.subscriptions.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[FilterCondition(field="organization_id", op="eq", value="x")],
                    search=None,
                )

    async def test_list_page_rejects_non_whitelisted_sort_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.subscriptions.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="id")],
                    filters=[],
                    search=None,
                )


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class InvoicePaginationRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """Exercises `SqlAlchemyInvoiceRepository.list_page` against real SQL. Isolates each test's
    rows by filtering on its own freshly-created `subscription_id` (never shared across tests) -
    safer than relying on `self.tag` alone for a `billing`-wide, no-tenant-scope query, the same
    reasoning `SubscriptionPaginationRepositoryTests` applies via `subscriber_id`.
    """

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_invoice_ids: list[str] = []
        self._created_subscription_ids: list[str] = []
        self._created_plan_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_invoice_ids:
                await conn.execute(
                    text("DELETE FROM invoices WHERE id = ANY(:ids)"),
                    {"ids": self._created_invoice_ids},
                )
            if self._created_subscription_ids:
                await conn.execute(
                    text("DELETE FROM subscriptions WHERE id = ANY(:ids)"),
                    {"ids": self._created_subscription_ids},
                )
            if self._created_plan_ids:
                await conn.execute(
                    text("DELETE FROM plans WHERE id = ANY(:ids)"),
                    {"ids": self._created_plan_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyBillingUnitOfWork:
        return SqlAlchemyBillingUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def _seed_plan(self) -> PlanId:
        async with self._new_uow() as uow:
            plan = Plan.create(
                id=PlanId(self.id_generator.new_id()),
                name=f"Invoice Page Plan {self.tag}",
                billing_scope=BillingScope.PARENT,
                price=Money(15.00, "USD"),
                billing_cycle=BillingCycle.MONTHLY,
                clock=self.clock,
            )
            uow.plans.add(plan)
            uow.record_events(plan.pull_domain_events())
            await uow.commit()
            self._created_plan_ids.append(str(plan.id))
            return plan.id

    async def _seed_subscription(self, plan_id: PlanId) -> SubscriptionId:
        async with self._new_uow() as uow:
            subscription = Subscription.open(
                id=SubscriptionId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                subscriber_type=SubscriberType.PARENT,
                subscriber_id=SubscriberId(self.id_generator.new_id()),
                plan_id=plan_id,
                clock=self.clock,
            )
            uow.subscriptions.add(subscription)
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()
            self._created_subscription_ids.append(str(subscription.id))
            return subscription.id

    async def _seed_invoice(
        self,
        subscription_id: SubscriptionId,
        *,
        amount: float = 15.00,
        period_start: date = date(2026, 7, 1),
        period_end: date = date(2026, 7, 31),
    ) -> Invoice:
        async with self._new_uow() as uow:
            invoice = Invoice.issue(
                id=InvoiceId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.id_generator.new_id()),
                subscription_id=subscription_id,
                amount=Money(amount, "USD"),
                period_start=period_start,
                period_end=period_end,
                due_at=None,
                clock=self.clock,
            )
            uow.invoices.add(invoice)
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
            self._created_invoice_ids.append(str(invoice.id))
            return invoice

    async def test_list_page_paginates_and_reports_total(self) -> None:
        plan_id = await self._seed_plan()
        subscription_id = await self._seed_subscription(plan_id)
        for i in range(3):
            await self._seed_invoice(subscription_id, amount=10.00 + i)

        async with self._new_uow() as uow:
            page = await uow.invoices.list_page(
                OffsetPageRequest(page=1, page_size=2),
                sort=[SortSpec(field="created_at")],
                filters=[
                    FilterCondition(
                        field="subscription_id", op="eq", value=str(subscription_id)
                    )
                ],
                search=None,
            )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

    async def test_list_page_filters_by_status(self) -> None:
        plan_id = await self._seed_plan()
        subscription_id = await self._seed_subscription(plan_id)
        await self._seed_invoice(subscription_id)
        voided = await self._seed_invoice(subscription_id)

        async with self._new_uow() as uow:
            loaded = await uow.invoices.get(voided.id)
            loaded.void(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            page = await uow.invoices.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[
                    FilterCondition(
                        field="subscription_id", op="eq", value=str(subscription_id)
                    ),
                    FilterCondition(field="status", op="eq", value="void"),
                ],
                search=None,
            )
        self.assertEqual(page.total, 1)
        self.assertEqual(str(page.data[0].id), str(voided.id))

    async def test_list_page_search_matches_number_substring(self) -> None:
        plan_id = await self._seed_plan()
        subscription_id = await self._seed_subscription(plan_id)
        invoice = await self._seed_invoice(subscription_id)

        async with self._new_uow() as uow:
            page = await uow.invoices.list_page(
                OffsetPageRequest(),
                sort=[],
                filters=[],
                search=invoice.number[:12],
            )
        self.assertIn(str(invoice.id), {str(i.id) for i in page.data})

    async def test_list_page_rejects_non_whitelisted_filter_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.invoices.list_page(
                    OffsetPageRequest(),
                    sort=[],
                    filters=[FilterCondition(field="organization_id", op="eq", value="x")],
                    search=None,
                )

    async def test_list_page_rejects_non_whitelisted_sort_field(self) -> None:
        async with self._new_uow() as uow:
            with self.assertRaises(ValidationError):
                await uow.invoices.list_page(
                    OffsetPageRequest(),
                    sort=[SortSpec(field="id")],
                    filters=[],
                    search=None,
                )


if __name__ == "__main__":
    unittest.main()
