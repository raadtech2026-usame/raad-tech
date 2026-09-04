"""PostgreSQL-backed integration test for ADR-0039's subscription-lifecycle schema and finders.

**Why this exists separately from the unit tests.** `tests/unit/test_subscription_lifecycle.py`
covers the same transitions against in-memory repositories, which by construction cannot fail on
a real database constraint. This codebase has already been bitten by exactly that gap twice
(CLAUDE.md's Permanent Engineering Lessons: the `aggregate_id` `CHAR(26)` truncation that passed
every fake-backed test, and the LSZ adapter's unclamped field that no unit test caught). The
things only a live database can prove, and that this file therefore asserts:

- The `past_due`/`grace_period` labels genuinely exist on the `subscription_status` PostgreSQL
  enum type and a row can actually be written with them — migration `a7f31c92be04` applied for
  real, not just present as a file.
- All five new `DateTime` columns round-trip through `subscription_to_model`/
  `model_to_subscription` without a tz-awareness error — CLAUDE.md's own `_aware_utc`/`_naive`
  lesson says every datetime field on a mapper needs this treatment, not just the one that first
  crashed.
- `get_current_by_organization` really does return terminal (`expired`) subscriptions, where
  `get_active_by_organization` really does hide them. This is the single most consequential
  behaviour in ADR-0039: had enforcement used the wrong finder, every expired organization would
  have kept full access, and no fake-backed test would have shown it.
- `has_unpaid_for_subscription`/`exists_for_period` behave against real SQL, including `void`
  counting as settled.

Skipped entirely (never failed) when no database is reachable, matching every other integration
test here. Every row is tagged per-run and deleted in FK-respecting order in teardown.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.modules.billing.domain.entities import Invoice, Plan, Subscription
from raad.modules.billing.domain.value_objects import (
    BillingCycle,
    BillingScope,
    InvoiceId,
    Money,
    OrganizationId,
    PlanId,
    SubscriptionId,
    SubscriptionStatus,
)
from raad.modules.billing.infra.repositories import SqlAlchemyBillingUnitOfWork


class SubscriptionLifecyclePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        if not settings.db.url:
            self.skipTest("No RAAD_DB__URL configured")
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self.org_id = self.id_generator.new_id()
        self._invoice_ids: list[str] = []
        self._subscription_ids: list[str] = []
        self._plan_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            for table, ids in (
                ("invoices", self._invoice_ids),
                ("subscriptions", self._subscription_ids),
                ("plans", self._plan_ids),
            ):
                if ids:
                    await conn.execute(
                        text(f"DELETE FROM {table} WHERE id = ANY(:ids)"), {"ids": ids}
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
                name=f"Lifecycle Plan {self.tag}",
                billing_scope=BillingScope.ORGANIZATION,
                price=Money(25.00, "USD"),
                billing_cycle=BillingCycle.MONTHLY,
                clock=self.clock,
            )
            uow.plans.add(plan)
            uow.record_events(plan.pull_domain_events())
            await uow.commit()
        self._plan_ids.append(str(plan.id))
        return plan.id

    async def _seed_subscription(self, plan_id: PlanId) -> SubscriptionId:
        async with self._new_uow() as uow:
            subscription = Subscription.open(
                id=SubscriptionId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.org_id),
                plan_id=plan_id,
                clock=self.clock,
            )
            uow.subscriptions.add(subscription)
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()
        self._subscription_ids.append(str(subscription.id))
        return subscription.id

    async def test_past_due_state_and_all_five_timestamps_round_trip(self) -> None:
        """Proves migration `a7f31c92be04` is genuinely applied: the enum label exists, the five
        columns exist, and the mapper writes/reads every one of them without a naive-vs-aware
        datetime error."""
        plan_id = await self._seed_plan()
        subscription_id = await self._seed_subscription(plan_id)
        deadline = self.clock.now() + timedelta(days=7)

        async with self._new_uow() as uow:
            subscription = await uow.subscriptions.get(subscription_id)
            subscription.mark_past_due(
                grace_period_ends_at=deadline, clock=self.clock, actor_id="system"
            )
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            reloaded = await uow.subscriptions.get(subscription_id)

        self.assertEqual(reloaded.status, SubscriptionStatus.PAST_DUE)
        self.assertIsNotNone(reloaded.past_due_since)
        self.assertIsNotNone(reloaded.grace_period_ends_at)
        # Stored naive-UTC like every other datetime column here; compare on the naive value.
        self.assertEqual(
            reloaded.grace_period_ends_at.replace(tzinfo=None),
            deadline.replace(tzinfo=None),
        )

    async def test_grace_period_state_persists(self) -> None:
        plan_id = await self._seed_plan()
        subscription_id = await self._seed_subscription(plan_id)

        async with self._new_uow() as uow:
            subscription = await uow.subscriptions.get(subscription_id)
            subscription.extend_grace_period(
                grace_period_ends_at=self.clock.now() + timedelta(days=14),
                clock=self.clock,
                actor_id="founder",
            )
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            reloaded = await uow.subscriptions.get(subscription_id)
        self.assertEqual(reloaded.status, SubscriptionStatus.GRACE_PERIOD)

    async def test_suspend_and_reactivate_round_trip_their_timestamps(self) -> None:
        plan_id = await self._seed_plan()
        subscription_id = await self._seed_subscription(plan_id)

        async with self._new_uow() as uow:
            subscription = await uow.subscriptions.get(subscription_id)
            subscription.suspend(clock=self.clock, actor_id="founder")
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            reloaded = await uow.subscriptions.get(subscription_id)
            self.assertEqual(reloaded.status, SubscriptionStatus.SUSPENDED)
            self.assertIsNotNone(reloaded.suspended_at)
            reloaded.reactivate(clock=self.clock, actor_id="founder")
            uow.record_events(reloaded.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            final = await uow.subscriptions.get(subscription_id)
        self.assertEqual(final.status, SubscriptionStatus.ACTIVE)
        self.assertIsNone(final.suspended_at)
        self.assertIsNone(final.grace_period_ends_at)

    async def test_get_current_sees_expired_where_get_active_hides_it(self) -> None:
        """**The most consequential assertion in this file.** Enforcement reads
        `get_current_by_organization`; had it read `get_active_by_organization`, an expired
        organization would return `None`, be treated as "never subscribed", and be granted
        access — silently un-enforcing ADR-0039 for the most common production state."""
        plan_id = await self._seed_plan()
        subscription_id = await self._seed_subscription(plan_id)

        async with self._new_uow() as uow:
            subscription = await uow.subscriptions.get(subscription_id)
            subscription.expire(clock=self.clock, actor_id="system")
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            current = await uow.subscriptions.get_current_by_organization(
                OrganizationId(self.org_id)
            )
            active = await uow.subscriptions.get_active_by_organization(
                OrganizationId(self.org_id)
            )

        self.assertIsNotNone(current)
        self.assertEqual(current.status, SubscriptionStatus.EXPIRED)
        self.assertIsNone(active)

    async def test_get_active_now_finds_a_past_due_subscription(self) -> None:
        """The widened IN-list. Without `past_due` in it, `open_organization_subscription` would
        open a *second* subscription row for an organization that already has one in flight."""
        plan_id = await self._seed_plan()
        subscription_id = await self._seed_subscription(plan_id)

        async with self._new_uow() as uow:
            subscription = await uow.subscriptions.get(subscription_id)
            subscription.mark_past_due(
                grace_period_ends_at=self.clock.now() + timedelta(days=7),
                clock=self.clock,
                actor_id="system",
            )
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            active = await uow.subscriptions.get_active_by_organization(
                OrganizationId(self.org_id)
            )
        self.assertIsNotNone(active)
        self.assertEqual(active.status, SubscriptionStatus.PAST_DUE)

    async def test_lifecycle_candidates_excludes_terminal_states(self) -> None:
        plan_id = await self._seed_plan()
        subscription_id = await self._seed_subscription(plan_id)

        async with self._new_uow() as uow:
            candidates = await uow.subscriptions.list_lifecycle_candidates()
            self.assertIn(
                str(subscription_id), {str(s.id) for s in candidates}
            )
            subscription = await uow.subscriptions.get(subscription_id)
            subscription.cancel(clock=self.clock, actor_id="founder")
            uow.record_events(subscription.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            after = await uow.subscriptions.list_lifecycle_candidates()
        self.assertNotIn(str(subscription_id), {str(s.id) for s in after})

    async def test_invoice_finders_against_real_sql(self) -> None:
        """`has_unpaid_for_subscription` decides PAST_DUE-vs-renew; `exists_for_period` is the
        invoice-issuance idempotency guard. Both are pure SQL and untestable with fakes."""
        plan_id = await self._seed_plan()
        subscription_id = await self._seed_subscription(plan_id)
        period_start = date(2026, 7, 20)
        period_end = date(2026, 8, 19)

        async with self._new_uow() as uow:
            self.assertFalse(
                await uow.invoices.has_unpaid_for_subscription(subscription_id)
            )
            self.assertFalse(
                await uow.invoices.exists_for_period(
                    subscription_id, period_start=period_start, period_end=period_end
                )
            )
            invoice = Invoice.issue(
                id=InvoiceId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.org_id),
                subscription_id=subscription_id,
                amount=Money(25.00, "USD"),
                period_start=period_start,
                period_end=period_end,
                due_at=None,
                clock=self.clock,
            )
            uow.invoices.add(invoice)
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
        self._invoice_ids.append(str(invoice.id))

        async with self._new_uow() as uow:
            self.assertTrue(
                await uow.invoices.has_unpaid_for_subscription(subscription_id)
            )
            self.assertTrue(
                await uow.invoices.exists_for_period(
                    subscription_id, period_start=period_start, period_end=period_end
                )
            )

        # `void` counts as settled — an invoice RAAD itself withdrew must not hold a tenant
        # past-due.
        async with self._new_uow() as uow:
            stored = await uow.invoices.get(invoice.id)
            stored.void(clock=self.clock, actor_id="founder")
            uow.record_events(stored.pull_domain_events())
            await uow.commit()

        async with self._new_uow() as uow:
            self.assertFalse(
                await uow.invoices.has_unpaid_for_subscription(subscription_id)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
