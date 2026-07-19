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
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
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
        return SqlAlchemyBillingUnitOfWork(self.session_factory, self.outbox_writer)

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


if __name__ == "__main__":
    unittest.main()
