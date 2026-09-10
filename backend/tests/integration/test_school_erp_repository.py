"""`school_erp` repository integration tests against a live PostgreSQL (ADR-0038, ADR-0040).

Three things only a real database can prove, and all three carry money:

  1. **Tenant isolation** — ADR-0021's `_apply_scope` really does keep one school's student
     invoices, payments and ledger out of another school's reads. This is the single
     highest-risk property in the module: every table here is financial, and every one is
     tenant-owned. `.claude/rules/testing.md` #3 requires tenant isolation to have explicit
     regression coverage rather than incidental coverage.
  2. **`NUMERIC(12,2)` round-trips as an exact `Decimal`** — the reason this module does not
     reuse `billing`'s float-backed `Money`. A float round-trip through asyncpg is where
     `100.00` quietly becomes `99.99999999999999`.
  3. **The grouped Vehicle Financial Overview query** — `summarise_by_vehicle` is hand-written
     SQL with a `GREATEST(net - paid, 0)` clamp and a scope filter. Neither can be verified
     against a fake; both are how a per-bus revenue figure becomes wrong.

Every test cleans up the rows it created (children before parents), leaving the schema exactly
as found — the same discipline `test_billing_repository.py` established.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.pagination import OffsetPageRequest
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.modules.school_erp.domain.entities import (
    Expense,
    FeePlan,
    StudentInvoice,
    StudentPayment,
)
from raad.modules.school_erp.domain.value_objects import (
    BillingPeriod,
    ExpenseId,
    FeePlanId,
    Money,
    OrganizationId,
    StudentId,
    StudentInvoiceId,
    StudentPaymentId,
    StudentPaymentMethod,
    VehicleId,
)
from raad.modules.school_erp.infra.repositories import SqlAlchemySchoolErpUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = (
    "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."
)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class SchoolErpRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        # Two distinct organizations — the whole point of the isolation tests below.
        self.org_a = f"ORGA{uuid.uuid4().hex[:22].upper()}"[:26]
        self.org_b = f"ORGB{uuid.uuid4().hex[:22].upper()}"[:26]
        self._payment_ids: list[str] = []
        self._invoice_ids: list[str] = []
        self._fee_plan_ids: list[str] = []
        self._expense_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            # Children before parents: payments reference invoices, invoices reference fee plans.
            for table, ids in (
                ("erp_student_payments", self._payment_ids),
                ("erp_student_invoices", self._invoice_ids),
                ("erp_fee_plans", self._fee_plan_ids),
                ("erp_expenses", self._expense_ids),
            ):
                if ids:
                    await conn.execute(
                        text(f"DELETE FROM {table} WHERE id = ANY(:ids)"), {"ids": ids}
                    )

    def _uow(self, organization_id: str | None) -> SqlAlchemySchoolErpUnitOfWork:
        """A Unit of Work scoped to one organization, or unrestricted when `None`.

        This mirrors exactly what `get_school_erp_uow` does per HTTP request, so these tests
        exercise the real enforcement path rather than a substitute for it.
        """
        uow = SqlAlchemySchoolErpUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )
        uow.scope = TenantRegionScope(
            organization_ids=[organization_id] if organization_id else None
        )
        return uow

    async def _issue_invoice(
        self,
        *,
        organization_id: str,
        amount: str = "100.00",
        vehicle_id: str | None = "BUS0000000000000000000001",
        period: str = "2026-09",
        student_id: str | None = None,
    ) -> StudentInvoice:
        invoice = StudentInvoice.issue(
            id=StudentInvoiceId(self.id_generator.new_id()),
            organization_id=OrganizationId(organization_id),
            student_id=StudentId(student_id or self.id_generator.new_id()),
            fee_plan_id=None,
            period=BillingPeriod(period),
            amount=Money(amount=Decimal(amount), currency="USD"),
            due_date=date(2026, 9, 30),
            vehicle_id=VehicleId(vehicle_id) if vehicle_id else None,
            clock=self.clock,
        )
        async with self._uow(organization_id) as uow:
            uow.student_invoices.add(invoice)
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
        self._invoice_ids.append(str(invoice.id))
        return invoice

    # -- Round-trip ---------------------------------------------------------------------------

    async def test_student_invoice_round_trips_with_exact_decimal_amounts(self) -> None:
        invoice = await self._issue_invoice(organization_id=self.org_a, amount="123.45")

        async with self._uow(self.org_a) as uow:
            fetched = await uow.student_invoices.get(invoice.id)

        self.assertIsNotNone(fetched)
        # Exactness is the claim: `Decimal("123.45")`, not 123.44999999999999.
        self.assertEqual(fetched.amount.amount, Decimal("123.45"))
        self.assertEqual(fetched.balance_due, Decimal("123.45"))
        self.assertEqual(str(fetched.period), "2026-09")
        self.assertEqual(str(fetched.vehicle_id), "BUS0000000000000000000001")

    async def test_fee_plan_round_trips(self) -> None:
        plan = FeePlan.create(
            id=FeePlanId(self.id_generator.new_id()),
            organization_id=OrganizationId(self.org_a),
            name=f"Standard {uuid.uuid4().hex[:6]}",
            amount=Money(amount=Decimal("30.00"), currency="USD"),
            default_discount_amount=Decimal("5.00"),
            clock=self.clock,
        )
        async with self._uow(self.org_a) as uow:
            uow.fee_plans.add(plan)
            uow.record_events(plan.pull_domain_events())
            await uow.commit()
        self._fee_plan_ids.append(str(plan.id))

        async with self._uow(self.org_a) as uow:
            fetched = await uow.fee_plans.get(plan.id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.amount.amount, Decimal("30.00"))
        self.assertEqual(fetched.default_discount_amount, Decimal("5.00"))

    # -- Tenant isolation ---------------------------------------------------------------------

    async def test_another_organization_cannot_get_this_invoice_by_id(self) -> None:
        invoice = await self._issue_invoice(organization_id=self.org_a)

        async with self._uow(self.org_b) as uow:
            fetched = await uow.student_invoices.get(invoice.id)

        # `None`, not a 403 — this codebase's established 404-over-403 posture for cross-tenant
        # probing, enforced at the repository layer so no call site can forget it.
        self.assertIsNone(fetched)

    async def test_listing_never_returns_another_organizations_invoices(self) -> None:
        await self._issue_invoice(organization_id=self.org_a)
        await self._issue_invoice(organization_id=self.org_b)

        async with self._uow(self.org_a) as uow:
            page = await uow.student_invoices.list_page(
                OffsetPageRequest(page=1, page_size=100), filters=[], sort=[], search=None
            )

        self.assertTrue(page.data, "org A should see its own invoice")
        for invoice in page.data:
            self.assertEqual(str(invoice.organization_id), self.org_a)

    async def test_vehicle_summary_is_scoped_to_the_calling_organization(self) -> None:
        """The grouped financial query applies `_apply_scope` too — a leak here would put one
        school's revenue into another school's dashboard totals."""
        shared_vehicle = "BUS0000000000000000000009"
        await self._issue_invoice(
            organization_id=self.org_a, amount="100.00", vehicle_id=shared_vehicle
        )
        await self._issue_invoice(
            organization_id=self.org_b, amount="500.00", vehicle_id=shared_vehicle
        )

        async with self._uow(self.org_a) as uow:
            summaries = await uow.student_invoices.summarise_by_vehicle(
                period=BillingPeriod("2026-09")
            )

        rows = [s for s in summaries if s.vehicle_id == shared_vehicle]
        self.assertEqual(len(rows), 1)
        # 100.00 only — org B's 500.00 must not appear despite sharing a vehicle id.
        self.assertEqual(rows[0].billed_amount, Decimal("100.00"))

    async def test_totals_are_scoped_to_the_calling_organization(self) -> None:
        await self._issue_invoice(organization_id=self.org_a, amount="100.00")
        await self._issue_invoice(organization_id=self.org_b, amount="900.00")

        async with self._uow(self.org_a) as uow:
            totals = await uow.student_invoices.summarise_totals(period=BillingPeriod("2026-09"))

        self.assertEqual(totals.billed_amount, Decimal("100.00"))

    # -- Payment application ------------------------------------------------------------------

    async def test_partial_payment_persists_and_leaves_a_real_balance(self) -> None:
        invoice = await self._issue_invoice(organization_id=self.org_a, amount="100.00")

        async with self._uow(self.org_a) as uow:
            loaded = await uow.student_invoices.get(invoice.id)
            payment = StudentPayment.record(
                id=StudentPaymentId(self.id_generator.new_id()),
                organization_id=loaded.organization_id,
                invoice_id=loaded.id,
                student_id=loaded.student_id,
                amount=Money(amount=Decimal("40.00"), currency="USD"),
                method=StudentPaymentMethod.CASH,
                received_on=date(2026, 9, 4),
                clock=self.clock,
            )
            loaded.apply_payment(
                amount=payment.amount, clock=self.clock
            )
            uow.student_payments.add(payment)
            uow.record_events(payment.pull_domain_events())
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()
            self._payment_ids.append(str(payment.id))

        async with self._uow(self.org_a) as uow:
            refetched = await uow.student_invoices.get(invoice.id)

        self.assertEqual(refetched.status.value, "partially_paid")
        self.assertEqual(refetched.amount_paid, Decimal("40.00"))
        self.assertEqual(refetched.balance_due, Decimal("60.00"))

    async def test_overpaid_invoice_never_contributes_negative_outstanding(self) -> None:
        """`GREATEST(net - paid, 0)` in SQL, matching `balance_due`'s Python clamp — otherwise a
        single overpaid student would cancel out another student's genuine debt in a bus total."""
        vehicle = "BUS0000000000000000000007"
        overpaid = await self._issue_invoice(
            organization_id=self.org_a, amount="100.00", vehicle_id=vehicle
        )
        await self._issue_invoice(
            organization_id=self.org_a, amount="100.00", vehicle_id=vehicle
        )

        async with self._uow(self.org_a) as uow:
            loaded = await uow.student_invoices.get(overpaid.id)
            loaded.apply_payment(
                amount=Money(amount=Decimal("250.00"), currency="USD"), clock=self.clock
            )
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        async with self._uow(self.org_a) as uow:
            summaries = await uow.student_invoices.summarise_by_vehicle(
                period=BillingPeriod("2026-09")
            )

        row = next(s for s in summaries if s.vehicle_id == vehicle)
        # The unpaid invoice's full 100.00 still shows as outstanding.
        self.assertEqual(row.outstanding_amount, Decimal("100.00"))

    # -- Ledger -------------------------------------------------------------------------------

    async def test_expense_sum_by_vehicle_is_scoped_and_exact(self) -> None:
        vehicle = "BUS0000000000000000000005"
        for org, amount in ((self.org_a, "80.50"), (self.org_b, "999.00")):
            expense = Expense.record(
                id=ExpenseId(self.id_generator.new_id()),
                organization_id=OrganizationId(org),
                category_id=None,
                amount=Money(amount=Decimal(amount), currency="USD"),
                occurred_on=date(2026, 9, 10),
                vehicle_id=VehicleId(vehicle),
                clock=self.clock,
            )
            async with self._uow(org) as uow:
                uow.expenses.add(expense)
                uow.record_events(expense.pull_domain_events())
                await uow.commit()
            self._expense_ids.append(str(expense.id))

        async with self._uow(self.org_a) as uow:
            by_vehicle = await uow.expenses.sum_by_vehicle_between(
                start=date(2026, 9, 1), end=date(2026, 9, 30)
            )

        self.assertEqual(by_vehicle.get(vehicle), Decimal("80.50"))

    async def test_an_expense_with_no_vehicle_is_absent_from_the_per_bus_totals(
        self,
    ) -> None:
        """General overhead must not appear in a per-bus aggregate at all.

        `GROUP BY vehicle_id` happily produces a NULL bucket, and the caller keyed this map by
        `vehicle_id or ""` — so every unattributed cost was charged to the Vehicle Financial
        Overview's "Unassigned" row. Live-reproduced against the running API. A fake-backed test
        cannot see this: the shape of the NULL bucket is a property of the SQL.
        """
        attributed = "BUS0000000000000000000006"
        for vehicle_id, amount in ((VehicleId(attributed), "40.00"), (None, "500.00")):
            expense = Expense.record(
                id=ExpenseId(self.id_generator.new_id()),
                organization_id=OrganizationId(self.org_a),
                category_id=None,
                amount=Money(amount=Decimal(amount), currency="USD"),
                occurred_on=date(2026, 10, 4),
                vehicle_id=vehicle_id,
                clock=self.clock,
            )
            async with self._uow(self.org_a) as uow:
                uow.expenses.add(expense)
                uow.record_events(expense.pull_domain_events())
                await uow.commit()
            self._expense_ids.append(str(expense.id))

        async with self._uow(self.org_a) as uow:
            by_vehicle = await uow.expenses.sum_by_vehicle_between(
                start=date(2026, 10, 1), end=date(2026, 10, 31)
            )
            total = await uow.expenses.sum_between(
                start=date(2026, 10, 1), end=date(2026, 10, 31)
            )

        self.assertEqual(by_vehicle, {attributed: Decimal("40.00")})
        self.assertNotIn("", by_vehicle)
        self.assertIsNone(by_vehicle.get(None))
        # The unattributed 500.00 is still a real cost — it belongs to Profit & Loss.
        self.assertEqual(total, Decimal("540.00"))


if __name__ == "__main__":
    unittest.main()
