"""PostgreSQL-backed integration tests for subscription provisioning (ADR-0039, ADR-0040 §5).

**This file exists because a fully green suite shipped a completely non-functional billing
engine.** `open_organization_subscription` creates a `Subscription` and its first `Invoice` in
*one* Unit of Work. That path was covered only by `tests/unit/test_billing_application.py`,
against in-memory fake repositories — which have no session, no flush and no foreign keys — and
by integration tests that seeded the subscription and the invoice in *separate* commits. So
nothing ever exercised the one thing that mattered, and every real call died on
`fk_invoices__subscriptions` with the whole transaction rolled back. Zero subscriptions had ever
been persisted on a live database.

The root cause was flush ordering: SQLAlchemy derives per-object INSERT order from `relationship()`
edges, and this codebase deliberately declares none between separate aggregates, so the flush fell
back to sorting mappers alphabetically by class name — `InvoiceModel` before `SubscriptionModel`.
`SqlAlchemyUnitOfWork._flush_in_dependency_order` fixes it for every module by deriving the order
from `MetaData.sorted_tables`.

Every test here therefore asserts against the **real** database. `MultiAggregateFlushOrderTests`
is the direct regression; `ProvisioningRollbackTests` proves the failure mode is now atomic and
loud rather than partial and silent.

Requires a reachable PostgreSQL database (`RAAD_DB__URL`). Skipped, never failed, when
unavailable. Every row created is deleted in `asyncTearDown` in FK-respecting order.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.errors.exceptions import NotFoundError
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import SystemClock
from raad.modules.billing.application.commands import (
    OpenOrganizationSubscriptionCommand,
)
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.billing.domain.entities import Invoice, Plan, Subscription
from raad.modules.billing.domain.value_objects import (
    BillingCycle,
    BillingScope,
    InvoiceId,
    Money,
    OrganizationId,
    PlanId,
    SubscriptionId,
)
from raad.modules.billing.infra.repositories import SqlAlchemyBillingUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = (
    "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."
)


class _BillingIntegrationCase(unittest.IsolatedAsyncioTestCase):
    """Shared fixture: real engine, real UoW, FK-ordered cleanup."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self.org_id = self.id_generator.new_id()
        self.founder = Principal(
            user_id=self.id_generator.new_id(), role=Role.FOUNDER, org_id=None
        )
        self._invoice_ids: list[str] = []
        self._subscription_ids: list[str] = []
        self._plan_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        # Best-effort and exception-proof. A teardown that raises leaves every row it had not
        # yet deleted behind *and* masks the test result — which is exactly how an earlier run
        # of this file leaked three subscriptions into a shared database.
        try:
            await self._cleanup()
        except Exception:  # noqa: BLE001 - a cleanup failure must not mask a test outcome
            pass
        finally:
            await self.engine.dispose()

    async def _cleanup(self) -> None:
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
            # Outbox/audit rows reference these aggregates by id only (no FK), so they are
            # cleaned separately rather than cascading.
            all_ids = self._invoice_ids + self._subscription_ids + self._plan_ids
            if all_ids:
                await conn.execute(
                    text("DELETE FROM outbox WHERE aggregate_id = ANY(:ids)"),
                    {"ids": all_ids},
                )
                await conn.execute(
                    text("DELETE FROM audit_entries WHERE entity_id = ANY(:ids)"),
                    {"ids": all_ids},
                )

    def _new_uow(self) -> SqlAlchemyBillingUnitOfWork:
        return SqlAlchemyBillingUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    def _service(self) -> BillingApplicationService:
        return BillingApplicationService(
            clock=self.clock, id_generator=self.id_generator, payment_provider=None
        )

    async def _seed_plan(self, price: str = "15.00") -> PlanId:
        plan = Plan.create(
            id=PlanId(self.id_generator.new_id()),
            name=f"Plan {self.tag}",
            billing_scope=BillingScope.ORGANIZATION,
            price=Money(float(price), "USD"),
            billing_cycle=BillingCycle.MONTHLY,
            clock=self.clock,
        )
        async with self._new_uow() as uow:
            uow.plans.add(plan)
            uow.record_events(plan.pull_domain_events())
            await uow.commit()
        self._plan_ids.append(str(plan.id))
        return plan.id

    async def _count(self, table: str, column: str, value: str) -> int:
        async with self.engine.begin() as conn:
            result = await conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :v"), {"v": value}
            )
            return int(result.scalar_one())


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class MultiAggregateFlushOrderTests(_BillingIntegrationCase):
    """The direct regression for the flush-ordering defect."""

    async def test_subscription_and_invoice_persist_from_one_unit_of_work(self) -> None:
        """Parent and child aggregate, created together, committed once, both on disk.

        Before the fix this raised `IntegrityError: insert or update on table "invoices"
        violates foreign key constraint "fk_invoices__subscriptions"` — SQLAlchemy emitted the
        child INSERT first. It is the single assertion that would have caught the outage.
        """
        plan_id = await self._seed_plan()

        subscription = Subscription.open(
            id=SubscriptionId(self.id_generator.new_id()),
            organization_id=OrganizationId(self.org_id),
            plan_id=plan_id,
            clock=self.clock,
        )
        invoice = Invoice.issue(
            id=InvoiceId(self.id_generator.new_id()),
            organization_id=OrganizationId(self.org_id),
            subscription_id=subscription.id,
            amount=Money(15.00, "USD"),
            period_start=date(2026, 9, 1),
            period_end=date(2026, 10, 1),
            due_at=None,
            clock=self.clock,
        )

        async with self._new_uow() as uow:
            uow.subscriptions.add(subscription)
            uow.invoices.add(invoice)  # child added second, as the real service does
            uow.record_events(subscription.pull_domain_events())
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()

        self._subscription_ids.append(str(subscription.id))
        self._invoice_ids.append(str(invoice.id))

        self.assertEqual(await self._count("subscriptions", "id", str(subscription.id)), 1)
        self.assertEqual(await self._count("invoices", "id", str(invoice.id)), 1)

    async def test_child_added_before_parent_still_persists(self) -> None:
        """Insertion order into the session must not matter — only FK dependency does.

        A caller that happens to build the invoice first is not making a mistake; the Unit of
        Work owns ordering, so this must work identically.
        """
        plan_id = await self._seed_plan()
        subscription = Subscription.open(
            id=SubscriptionId(self.id_generator.new_id()),
            organization_id=OrganizationId(self.org_id),
            plan_id=plan_id,
            clock=self.clock,
        )
        invoice = Invoice.issue(
            id=InvoiceId(self.id_generator.new_id()),
            organization_id=OrganizationId(self.org_id),
            subscription_id=subscription.id,
            amount=Money(15.00, "USD"),
            period_start=date(2026, 9, 1),
            period_end=date(2026, 10, 1),
            due_at=None,
            clock=self.clock,
        )

        async with self._new_uow() as uow:
            uow.invoices.add(invoice)  # deliberately first
            uow.subscriptions.add(subscription)
            await uow.commit()

        self._subscription_ids.append(str(subscription.id))
        self._invoice_ids.append(str(invoice.id))
        self.assertEqual(await self._count("invoices", "id", str(invoice.id)), 1)

    async def test_three_aggregates_across_two_foreign_keys_in_one_commit(self) -> None:
        """Plan → Subscription → Invoice, one Unit of Work, two FK hops.

        A single ordered pair could pass by luck; a chain cannot. `PlanModel` sorts *after*
        `InvoiceModel` alphabetically too, so pre-fix this failed on whichever FK was reached
        first.
        """
        plan = Plan.create(
            id=PlanId(self.id_generator.new_id()),
            name=f"Chain {self.tag}",
            billing_scope=BillingScope.ORGANIZATION,
            price=Money(25.00, "USD"),
            billing_cycle=BillingCycle.MONTHLY,
            clock=self.clock,
        )
        subscription = Subscription.open(
            id=SubscriptionId(self.id_generator.new_id()),
            organization_id=OrganizationId(self.org_id),
            plan_id=plan.id,
            clock=self.clock,
        )
        invoice = Invoice.issue(
            id=InvoiceId(self.id_generator.new_id()),
            organization_id=OrganizationId(self.org_id),
            subscription_id=subscription.id,
            amount=Money(25.00, "USD"),
            period_start=date(2026, 9, 1),
            period_end=date(2026, 10, 1),
            due_at=None,
            clock=self.clock,
        )

        async with self._new_uow() as uow:
            uow.invoices.add(invoice)
            uow.plans.add(plan)
            uow.subscriptions.add(subscription)
            await uow.commit()

        self._plan_ids.append(str(plan.id))
        self._subscription_ids.append(str(subscription.id))
        self._invoice_ids.append(str(invoice.id))

        self.assertEqual(await self._count("plans", "id", str(plan.id)), 1)
        self.assertEqual(await self._count("subscriptions", "id", str(subscription.id)), 1)
        self.assertEqual(await self._count("invoices", "id", str(invoice.id)), 1)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class OpenOrganizationSubscriptionTests(_BillingIntegrationCase):
    """The real application service against the real database — the path onboarding calls."""

    async def test_opens_subscription_and_issues_first_invoice(self) -> None:
        plan_id = await self._seed_plan("30.00")

        invoice_dto = await self._service().open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=self.org_id, plan_id=str(plan_id), actor=self.founder
            ),
            uow=self._new_uow(),
        )
        self._invoice_ids.append(invoice_dto.id)

        async with self._new_uow() as uow:
            subscription = await uow.subscriptions.get_active_by_organization(
                OrganizationId(self.org_id)
            )
        self.assertIsNotNone(subscription)
        self._subscription_ids.append(str(subscription.id))

        self.assertEqual(
            await self._count("subscriptions", "organization_id", self.org_id), 1
        )
        self.assertEqual(await self._count("invoices", "organization_id", self.org_id), 1)
        self.assertEqual(invoice_dto.amount, 30.00)
        self.assertEqual(str(subscription.plan_id), str(plan_id))

    async def test_reopening_reuses_the_subscription_and_adds_a_second_invoice(self) -> None:
        """Renewal must not open a second subscription row for the same organization."""
        plan_id = await self._seed_plan("30.00")
        command = OpenOrganizationSubscriptionCommand(
            organization_id=self.org_id, plan_id=str(plan_id), actor=self.founder
        )
        service = self._service()

        first = await service.open_organization_subscription(command, uow=self._new_uow())
        second = await service.open_organization_subscription(command, uow=self._new_uow())
        self._invoice_ids.extend([first.id, second.id])

        async with self._new_uow() as uow:
            subscription = await uow.subscriptions.get_active_by_organization(
                OrganizationId(self.org_id)
            )
        self._subscription_ids.append(str(subscription.id))

        self.assertEqual(
            await self._count("subscriptions", "organization_id", self.org_id), 1
        )
        self.assertEqual(await self._count("invoices", "organization_id", self.org_id), 2)

    async def test_the_commit_writes_audit_rows_for_both_aggregates(self) -> None:
        """ADR-0007: business rows and their audit trail land in the same transaction.

        Worth asserting here specifically: pre-fix the transaction rolled back, so the audit
        trail was silent about an organization that appeared to onboard successfully.
        """
        plan_id = await self._seed_plan("30.00")
        invoice_dto = await self._service().open_organization_subscription(
            OpenOrganizationSubscriptionCommand(
                organization_id=self.org_id, plan_id=str(plan_id), actor=self.founder
            ),
            uow=self._new_uow(),
        )
        self._invoice_ids.append(invoice_dto.id)
        async with self._new_uow() as uow:
            subscription = await uow.subscriptions.get_active_by_organization(
                OrganizationId(self.org_id)
            )
        self._subscription_ids.append(str(subscription.id))

        async with self.engine.begin() as conn:
            actions = (
                await conn.execute(
                    text(
                        "SELECT action FROM audit_entries WHERE organization_id = :org "
                        "ORDER BY action"
                    ),
                    {"org": self.org_id},
                )
            ).scalars().all()
        self.assertIn("SubscriptionOpened", actions)
        self.assertIn("InvoiceIssued", actions)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class ProvisioningRollbackTests(_BillingIntegrationCase):
    """Failure must be atomic and loud — never a half-provisioned organization."""

    async def test_an_unknown_plan_raises_and_writes_nothing(self) -> None:
        missing_plan = self.id_generator.new_id()

        with self.assertRaises(NotFoundError):
            await self._service().open_organization_subscription(
                OpenOrganizationSubscriptionCommand(
                    organization_id=self.org_id, plan_id=missing_plan, actor=self.founder
                ),
                uow=self._new_uow(),
            )

        self.assertEqual(
            await self._count("subscriptions", "organization_id", self.org_id), 0
        )
        self.assertEqual(await self._count("invoices", "organization_id", self.org_id), 0)

    async def test_a_failed_commit_leaves_neither_aggregate_behind(self) -> None:
        """The parent flushes first now, so a *child* failure must still roll the parent back.

        Constructed with an invoice whose number collides with itself on a second insert, which
        fails at the database rather than in Python — the only kind of failure that can happen
        after the subscription row is already in the transaction.
        """
        plan_id = await self._seed_plan()
        subscription = Subscription.open(
            id=SubscriptionId(self.id_generator.new_id()),
            organization_id=OrganizationId(self.org_id),
            plan_id=plan_id,
            clock=self.clock,
        )
        invoice_id = InvoiceId(self.id_generator.new_id())
        first = Invoice.issue(
            id=invoice_id,
            organization_id=OrganizationId(self.org_id),
            subscription_id=subscription.id,
            amount=Money(15.00, "USD"),
            period_start=date(2026, 9, 1),
            period_end=date(2026, 10, 1),
            due_at=None,
            clock=self.clock,
        )
        duplicate = Invoice.issue(
            id=invoice_id,  # same primary key -> guaranteed DB-level failure
            organization_id=OrganizationId(self.org_id),
            subscription_id=subscription.id,
            amount=Money(15.00, "USD"),
            period_start=date(2026, 10, 1),
            period_end=date(2026, 11, 1),
            due_at=None,
            clock=self.clock,
        )

        with self.assertRaises(Exception):
            async with self._new_uow() as uow:
                uow.subscriptions.add(subscription)
                uow.invoices.add(first)
                uow.invoices.add(duplicate)
                await uow.commit()

        self.assertEqual(
            await self._count("subscriptions", "id", str(subscription.id)), 0
        )
        self.assertEqual(await self._count("invoices", "id", str(invoice_id)), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
