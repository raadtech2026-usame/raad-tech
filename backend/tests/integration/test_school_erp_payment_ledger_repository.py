"""ADR-0047 payment ledger and vehicle-income queries against a live PostgreSQL.

What only a real database can prove, all of it about money:

  1. **Tenant isolation** on the two new tables and on every hand-written income aggregate.
  2. **`CHAR(26)` padding never splits a bus.** Student income is keyed by the allocation's
     `vehicle_id`; a padded key would silently become a second, unmatched bus row.
  3. **Voided payments and the `received_on` window** are applied in SQL, where the totals are.
  4. **The idempotency key is enforced by a real partial unique index**, per organization.
  5. **Two concurrent payments on one invoice cannot both commit** — `row_version` optimistic
     locking on the invoice refuses the second, so money is never applied twice.
  6. **`created_by` is stamped from the acting user** on the new rows (finance P0.6).

Every test deletes what it created: allocations, payments, lines, invoices, income.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.logging.context import principal_id_var
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.modules.school_erp.domain.entities import (
    BilledChild,
    Income,
    ParentInvoice,
    ParentPayment,
    PaymentAllocationInput,
)
from raad.modules.school_erp.domain.value_objects import (
    BillingPeriod,
    IncomeId,
    IncomeType,
    Money,
    OrganizationId,
    ParentId,
    ParentInvoiceId,
    ParentPaymentId,
    StudentId,
    StudentPaymentMethod,
    VehicleId,
)
from raad.modules.school_erp.infra.repositories import SqlAlchemySchoolErpUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


@unittest.skipUnless(_db_available(), "RAAD_DB__URL not configured")
class ParentPaymentLedgerRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.ids = UlidGenerator()
        self.clock = SystemClock()
        self.org_a = f"ORGA{uuid.uuid4().hex[:22].upper()}"[:26]
        self.org_b = f"ORGB{uuid.uuid4().hex[:22].upper()}"[:26]
        self.bus = self.ids.new_id()
        self._invoice_ids: list[str] = []
        self._income_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._invoice_ids:
                await conn.execute(
                    text(
                        "DELETE FROM erp_parent_payment_allocations WHERE parent_payment_id IN "
                        "(SELECT id FROM erp_parent_payments WHERE parent_invoice_id = ANY(:ids))"
                    ),
                    {"ids": self._invoice_ids},
                )
                await conn.execute(
                    text("DELETE FROM erp_parent_payments WHERE parent_invoice_id = ANY(:ids)"),
                    {"ids": self._invoice_ids},
                )
                await conn.execute(
                    text("DELETE FROM erp_parent_invoice_lines WHERE parent_invoice_id = ANY(:ids)"),
                    {"ids": self._invoice_ids},
                )
                await conn.execute(
                    text("DELETE FROM erp_parent_invoices WHERE id = ANY(:ids)"),
                    {"ids": self._invoice_ids},
                )
            if self._income_ids:
                await conn.execute(
                    text("DELETE FROM erp_income WHERE id = ANY(:ids)"), {"ids": self._income_ids}
                )
        await self.engine.dispose()

    def _uow(self, organization_id: str | None) -> SqlAlchemySchoolErpUnitOfWork:
        uow = SqlAlchemySchoolErpUnitOfWork(self.session_factory, OutboxWriter(), AuditWriter())
        uow.scope = TenantRegionScope(organization_ids=[organization_id] if organization_id else None)
        return uow

    async def _invoice(self, org: str, *, students: int = 2, amount: str = "100.00") -> ParentInvoice:
        invoice = ParentInvoice.generate(
            id=ParentInvoiceId(self.ids.new_id()),
            organization_id=OrganizationId(org),
            parent_id=ParentId(self.ids.new_id()),
            period=BillingPeriod("2026-09"),
            amount=Money(amount=Decimal(amount), currency="USD"),
            due_date=date(2026, 9, 30),
            children=[
                BilledChild(line_id=self.ids.new_id(), student_id=self.ids.new_id(), vehicle_id=self.bus)
                for _ in range(students)
            ],
            clock=self.clock,
        )
        async with self._uow(org) as uow:
            uow.parent_invoices.add(invoice)
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
        self._invoice_ids.append(str(invoice.id))
        return invoice

    async def _pay(
        self, org: str, invoice_id, amount: str, *, received_on=date(2026, 9, 12), key: str | None = None
    ) -> ParentPayment:
        async with self._uow(org) as uow:
            invoice = await uow.parent_invoices.get(invoice_id)
            allocations = invoice.default_allocation(Decimal(amount))
            payment_id = self.ids.new_id()
            invoice.apply_payment(
                payment_id=payment_id, allocations=allocations, currency="USD", clock=self.clock
            )
            payment = ParentPayment.record(
                id=ParentPaymentId(payment_id),
                organization_id=invoice.organization_id,
                parent_id=invoice.parent_id,
                invoice_id=invoice.id,
                amount=Money(amount=Decimal(amount), currency="USD"),
                method=StudentPaymentMethod.BANK_TRANSFER,
                received_on=received_on,
                reference="TX-1",
                idempotency_key=key,
                allocations=[
                    PaymentAllocationInput(
                        allocation_id=self.ids.new_id(),
                        line_id=a.line_id,
                        student_id=str(invoice.line_for(a.line_id).student_id),
                        vehicle_id=str(invoice.line_for(a.line_id).vehicle_id),
                        amount=a.amount,
                    )
                    for a in allocations
                ],
                clock=self.clock,
            )
            uow.parent_payments.add(payment)
            uow.record_events(invoice.pull_domain_events())
            uow.record_events(payment.pull_domain_events())
            await uow.commit()
        return payment

    # -- Round trip -------------------------------------------------------------------------

    async def test_a_payment_round_trips_with_exact_allocations_and_line_balances(self) -> None:
        invoice = await self._invoice(self.org_a, students=3, amount="100.00")
        payment = await self._pay(self.org_a, invoice.id, "10.00")

        async with self._uow(self.org_a) as uow:
            stored = await uow.parent_payments.get(payment.id)
            reloaded = await uow.parent_invoices.get(invoice.id)

        self.assertEqual(stored.amount.amount, Decimal("10.00"))
        self.assertEqual(sum(a.amount.amount for a in stored.allocations), Decimal("10.00"))
        self.assertEqual({str(a.vehicle_id) for a in stored.allocations}, {self.bus})
        self.assertEqual(reloaded.amount_paid, Decimal("10.00"))
        self.assertEqual(sum(l.amount_paid for l in reloaded.lines), Decimal("10.00"))
        self.assertEqual(stored.reference, "TX-1")

    async def test_listing_by_invoice_parent_and_student(self) -> None:
        invoice = await self._invoice(self.org_a)
        payment = await self._pay(self.org_a, invoice.id, "20.00")
        student_id = str(invoice.lines[0].student_id)
        async with self._uow(self.org_a) as uow:
            by_invoice = await uow.parent_payments.list_for_invoice(invoice.id)
            by_parent = await uow.parent_payments.list_for_parent(invoice.parent_id)
            by_student = await uow.parent_payments.list_for_student(StudentId(student_id))
            invoices_for_student = await uow.parent_invoices.list_for_student(StudentId(student_id))
        for listed in (by_invoice, by_parent, by_student):
            self.assertEqual([str(p.id) for p in listed], [str(payment.id)])
        self.assertEqual([str(i.id) for i in invoices_for_student], [str(invoice.id)])

    # -- Tenant isolation -------------------------------------------------------------------

    async def test_another_organization_sees_no_payment_and_no_income(self) -> None:
        invoice = await self._invoice(self.org_a)
        payment = await self._pay(self.org_a, invoice.id, "20.00")
        window = dict(start=date(2026, 9, 1), end=date(2026, 9, 30))
        async with self._uow(self.org_b) as uow:
            self.assertIsNone(await uow.parent_payments.get(payment.id))
            self.assertEqual(await uow.parent_payments.sum_student_income_between(**window), Decimal("0.00"))
            self.assertEqual(await uow.parent_payments.student_income_by_vehicle_between(**window), {})
            self.assertEqual(await uow.parent_payments.currencies_between(**window), set())
            self.assertEqual(await uow.parent_payments.list_for_parent(invoice.parent_id), [])

    # -- Aggregates: padding, voids, window -------------------------------------------------

    async def test_student_income_is_keyed_by_the_unpadded_vehicle_and_skips_voids(self) -> None:
        invoice = await self._invoice(self.org_a, students=2)
        await self._pay(self.org_a, invoice.id, "30.00", received_on=date(2026, 9, 12))
        voided = await self._pay(self.org_a, invoice.id, "20.00", received_on=date(2026, 9, 13))
        await self._pay(self.org_a, invoice.id, "10.00", received_on=date(2026, 10, 2))
        async with self._uow(self.org_a) as uow:
            loaded = await uow.parent_payments.get(voided.id)
            loaded.void(reason="Bounced", clock=self.clock)
            reloaded_invoice = await uow.parent_invoices.get(invoice.id)
            reloaded_invoice.reverse_payment(
                payment_id=str(voided.id), allocations=loaded.as_line_allocations(), clock=self.clock
            )
            uow.record_events(loaded.pull_domain_events())
            uow.record_events(reloaded_invoice.pull_domain_events())
            await uow.commit()

        window = dict(start=date(2026, 9, 1), end=date(2026, 9, 30))
        async with self._uow(self.org_a) as uow:
            total = await uow.parent_payments.sum_student_income_between(**window)
            by_vehicle = await uow.parent_payments.student_income_by_vehicle_between(**window)
            rows = await uow.parent_payments.student_income_rows_between(
                vehicle_id=VehicleId(self.bus), **window
            )
            invoice_after = await uow.parent_invoices.get(invoice.id)

        self.assertEqual(total, Decimal("30.00"))
        self.assertEqual(by_vehicle, {self.bus: Decimal("30.00")})
        self.assertEqual(sum(r.amount for r in rows), Decimal("30.00"))
        self.assertTrue(all(r.parent_id == str(invoice.parent_id) for r in rows))
        self.assertEqual(invoice_after.amount_paid, Decimal("40.00"))  # 30 + October's 10

    async def test_income_by_type_and_vehicle(self) -> None:
        async with self._uow(self.org_a) as uow:
            for amount, income_type, vehicle in (
                ("25.00", IncomeType.DAILY_VEHICLE, self.bus),
                ("35.00", IncomeType.DAILY_VEHICLE, self.bus),
                ("100.00", IncomeType.OTHER, self.bus),
                ("500.00", IncomeType.OTHER, None),
            ):
                income = Income.record(
                    id=IncomeId(self.ids.new_id()),
                    organization_id=OrganizationId(self.org_a),
                    category_id=None,
                    amount=Money(amount=Decimal(amount), currency="USD"),
                    occurred_on=date(2026, 9, 5),
                    income_type=income_type,
                    vehicle_id=VehicleId(vehicle) if vehicle else None,
                    clock=self.clock,
                )
                uow.income.add(income)
                uow.record_events(income.pull_domain_events())
                self._income_ids.append(str(income.id))
            await uow.commit()

        window = dict(start=date(2026, 9, 1), end=date(2026, 9, 30))
        async with self._uow(self.org_a) as uow:
            by_type = await uow.income.sum_by_type_between(**window)
            by_vehicle = await uow.income.sum_by_vehicle_and_type_between(**window)
            entries = await uow.income.list_for_vehicle_between(vehicle_id=VehicleId(self.bus), **window)
        async with self._uow(self.org_b) as uow:
            other_org = await uow.income.sum_by_type_between(**window)

        self.assertEqual(by_type, {"daily_vehicle": Decimal("60.00"), "other": Decimal("600.00")})
        self.assertEqual(
            by_vehicle,
            {(self.bus, "daily_vehicle"): Decimal("60.00"), (self.bus, "other"): Decimal("100.00")},
        )
        self.assertEqual(len(entries), 3)
        self.assertEqual(str(entries[0].vehicle_id), self.bus)
        self.assertEqual(other_org, {})

    # -- Integrity --------------------------------------------------------------------------

    async def test_an_idempotency_key_is_unique_within_an_organization(self) -> None:
        invoice = await self._invoice(self.org_a, amount="200.00")
        await self._pay(self.org_a, invoice.id, "10.00", key="key-duplicate-001")
        async with self._uow(self.org_a) as uow:
            found = await uow.parent_payments.get_by_idempotency_key("key-duplicate-001")
        self.assertIsNotNone(found)
        with self.assertRaises(IntegrityError):
            await self._pay(self.org_a, invoice.id, "10.00", key="key-duplicate-001")

        other = await self._invoice(self.org_b)
        await self._pay(self.org_b, other.id, "10.00", key="key-duplicate-001")  # other tenant: fine

    async def test_two_concurrent_payments_on_one_invoice_cannot_both_commit(self) -> None:
        invoice = await self._invoice(self.org_a, students=1, amount="50.00")
        first = self._uow(self.org_a)
        second = self._uow(self.org_a)
        async with first:
            async with second:
                for uow in (first, second):
                    loaded = await uow.parent_invoices.get(invoice.id)
                    allocations = loaded.default_allocation(Decimal("50.00"))
                    loaded.apply_payment(
                        payment_id=self.ids.new_id(), allocations=allocations,
                        currency="USD", clock=self.clock,
                    )
                await first.commit()
                with self.assertRaises(StaleDataError):
                    await second.commit()
        async with self._uow(self.org_a) as uow:
            reloaded = await uow.parent_invoices.get(invoice.id)
        self.assertEqual(reloaded.amount_paid, Decimal("50.00"))

    async def test_new_rows_are_stamped_with_the_acting_user(self) -> None:
        invoice = await self._invoice(self.org_a)
        actor = self.ids.new_id()
        token = principal_id_var.set(actor)
        try:
            payment = await self._pay(self.org_a, invoice.id, "20.00")
        finally:
            principal_id_var.reset(token)
        async with self.engine.connect() as conn:
            payment_by = (
                await conn.execute(
                    text("SELECT created_by FROM erp_parent_payments WHERE id = :id"), {"id": str(payment.id)}
                )
            ).scalar()
            allocation_by = (
                await conn.execute(
                    text(
                        "SELECT DISTINCT created_by FROM erp_parent_payment_allocations "
                        "WHERE parent_payment_id = :id"
                    ),
                    {"id": str(payment.id)},
                )
            ).scalars().all()
            invoice_by = (
                await conn.execute(
                    text("SELECT updated_by FROM erp_parent_invoices WHERE id = :id"), {"id": str(invoice.id)}
                )
            ).scalar()
        self.assertEqual(payment_by.rstrip(), actor)
        self.assertEqual([value.rstrip() for value in allocation_by], [actor])
        self.assertEqual(invoice_by.rstrip(), actor)


if __name__ == "__main__":
    unittest.main()
