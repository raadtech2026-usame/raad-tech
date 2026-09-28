"""`ParentBillingProfile`/`ParentInvoice` repository integration tests against a live PostgreSQL
(ADR-0042, 2026-09-11 — supersedes ADR-0041 SS1).

Mirrors `test_school_erp_repository.py`'s exact structure and reasoning — three things only a
real database can prove, and all three carry money:

  1. **Tenant isolation** across the two new tables, the identical highest-risk property
     `test_school_erp_repository.py` already exists to protect for the other six.
  2. **`NUMERIC(12,2)` round-trips as an exact `Decimal`**, on every per-student line amount
     (ADR-0048) and on the invoice total that is their sum.
  3. **`summarise_lines_by_vehicle_between`** (ADR-0047) — billed and outstanding per line
     vehicle, from each line's own `amount_paid`, with `GREATEST` clamping only real SQL shows.
  4. **ADR-0048's constraints**: the per-student fee table's tenant scope, uniqueness and
     non-negative check; the partial unique index that lets a cancelled invoice's period be
     billed again; and the "already billed this period" lookup that keeps a child on one bill.

Every test cleans up the rows it created (lines before invoices, invoices before profiles),
leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.pagination import OffsetPageRequest
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.modules.school_erp.domain.entities import (
    BilledChild,
    LineAllocation,
    ParentBillingProfile,
    ParentInvoice,
    StudentBillingProfile,
)
from raad.modules.school_erp.domain.value_objects import (
    BillingPeriod,
    Money,
    OrganizationId,
    ParentBillingProfileId,
    ParentId,
    ParentInvoiceId,
    ParentInvoiceStatus,
    StudentBillingProfileId,
    StudentId,
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
class ParentInvoiceRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.org_a = f"ORGA{uuid.uuid4().hex[:22].upper()}"[:26]
        self.org_b = f"ORGB{uuid.uuid4().hex[:22].upper()}"[:26]
        self._invoice_ids: list[str] = []
        self._profile_ids: list[str] = []

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
            if self._profile_ids:
                await conn.execute(
                    text("DELETE FROM erp_parent_billing_profiles WHERE id = ANY(:ids)"),
                    {"ids": self._profile_ids},
                )
            await conn.execute(
                text("DELETE FROM erp_student_billing_profiles WHERE organization_id IN (:a, :b)"),
                {"a": self.org_a, "b": self.org_b},
            )

    def _uow(self, organization_id: str | None) -> SqlAlchemySchoolErpUnitOfWork:
        uow = SqlAlchemySchoolErpUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )
        uow.scope = TenantRegionScope(
            organization_ids=[organization_id] if organization_id else None
        )
        return uow

    async def _generate_invoice(
        self,
        *,
        organization_id: str,
        amount: str = "100.00",
        period: str = "2026-09",
        parent_id: str | None = None,
        children: list[BilledChild] | None = None,
        currency: str = "USD",
    ) -> ParentInvoice:
        invoice = ParentInvoice.generate(
            id=ParentInvoiceId(self.id_generator.new_id()),
            organization_id=OrganizationId(organization_id),
            parent_id=ParentId(parent_id or self.id_generator.new_id()),
            period=BillingPeriod(period),
            currency=currency,
            due_date=date(2026, 9, 30),
            children=children
            or [
                BilledChild(
                    line_id=self.id_generator.new_id(),
                    student_id=self.id_generator.new_id(),
                    amount=Decimal(amount),
                    vehicle_id="BUS0000000000000000000001",
                )
            ],
            clock=self.clock,
        )
        async with self._uow(organization_id) as uow:
            uow.parent_invoices.add(invoice)
            uow.record_events(invoice.pull_domain_events())
            await uow.commit()
        self._invoice_ids.append(str(invoice.id))
        return invoice

    # -- Round-trip ---------------------------------------------------------------------------

    async def test_parent_invoice_round_trips_with_exact_decimal_line_amounts(self) -> None:
        """Three children at their own fees ($10.00/$20.05/$69.95, ADR-0048) must round-trip
        through `NUMERIC(12,2)` exactly, on every line and on the $100 total."""
        fees = {self.id_generator.new_id(): Decimal(fee) for fee in ("10.00", "20.05", "69.95")}
        children = [
            BilledChild(line_id=self.id_generator.new_id(), student_id=sid, amount=fee)
            for sid, fee in fees.items()
        ]
        invoice = await self._generate_invoice(organization_id=self.org_a, children=children)

        async with self._uow(self.org_a) as uow:
            fetched = await uow.parent_invoices.get(invoice.id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.amount.amount, Decimal("100.00"))
        self.assertEqual(len(fetched.lines), 3)
        self.assertEqual(
            {str(line.student_id): line.amount.amount for line in fetched.lines}, fees
        )

    async def test_parent_billing_profile_round_trips(self) -> None:
        profile = ParentBillingProfile.open(
            id=ParentBillingProfileId(self.id_generator.new_id()),
            organization_id=OrganizationId(self.org_a),
            parent_id=ParentId(self.id_generator.new_id()),
            currency="USD",
            billing_start_period=BillingPeriod("2026-09"),
            due_day=10,
            clock=self.clock,
        )
        async with self._uow(self.org_a) as uow:
            uow.parent_billing_profiles.add(profile)
            uow.record_events(profile.pull_domain_events())
            await uow.commit()
        self._profile_ids.append(str(profile.id))

        async with self._uow(self.org_a) as uow:
            fetched = await uow.parent_billing_profiles.get_by_parent(profile.parent_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.currency, "USD")
        self.assertEqual(fetched.due_day, 10)
        async with self.engine.connect() as conn:
            stored_fee = (
                await conn.execute(
                    text("SELECT monthly_fee FROM erp_parent_billing_profiles WHERE id = :id"),
                    {"id": str(profile.id)},
                )
            ).scalar()
        self.assertIsNone(stored_fee, "the retired family fee is never written")

    # -- Tenant isolation ---------------------------------------------------------------------

    async def test_another_organization_cannot_get_this_invoice_by_id(self) -> None:
        invoice = await self._generate_invoice(organization_id=self.org_a)

        async with self._uow(self.org_b) as uow:
            fetched = await uow.parent_invoices.get(invoice.id)

        self.assertIsNone(fetched)

    async def test_listing_never_returns_another_organizations_invoices(self) -> None:
        await self._generate_invoice(organization_id=self.org_a)
        await self._generate_invoice(organization_id=self.org_b)

        async with self._uow(self.org_a) as uow:
            page = await uow.parent_invoices.list_page(
                OffsetPageRequest(page=1, page_size=100), filters=[], sort=[], search=None
            )

        self.assertTrue(all(str(inv.organization_id) == self.org_a for inv in page.data))

    # -- Idempotency guard ----------------------------------------------------------------------

    async def test_exists_for_parent_period_backs_the_idempotency_guard(self) -> None:
        parent_id = self.id_generator.new_id()
        await self._generate_invoice(
            organization_id=self.org_a, period="2026-09", parent_id=parent_id
        )

        async with self._uow(self.org_a) as uow:
            exists = await uow.parent_invoices.exists_for_parent_period(
                parent_id=ParentId(parent_id), period=BillingPeriod("2026-09")
            )
            exists_other_period = await uow.parent_invoices.exists_for_parent_period(
                parent_id=ParentId(parent_id), period=BillingPeriod("2026-10")
            )

        self.assertTrue(exists)
        self.assertFalse(exists_other_period)

    # -- Vehicle Financial Overview -------------------------------------------------------------

    async def test_lines_by_vehicle_use_each_students_own_paid_amount(self) -> None:
        """Two students on one bus, one fully paid and one not: the bus's outstanding figure is
        the unpaid student's balance, read from the lines themselves (ADR-0047 §2)."""
        student_a, student_b = self.id_generator.new_id(), self.id_generator.new_id()
        children = [
            BilledChild(line_id=self.id_generator.new_id(), student_id=student_a, amount=Decimal("50.00"), vehicle_id="BUS0000000000000000000009"),
            BilledChild(line_id=self.id_generator.new_id(), student_id=student_b, amount=Decimal("50.00"), vehicle_id="BUS0000000000000000000009"),
        ]
        invoice = await self._generate_invoice(
            organization_id=self.org_a, period="2026-09", children=children
        )
        async with self._uow(self.org_a) as uow:
            fetched = await uow.parent_invoices.get(invoice.id)
            line_a = next(l for l in fetched.lines if str(l.student_id) == student_a)
            fetched.apply_payment(
                payment_id="not-persisted-here",
                allocations=[LineAllocation(line_id=str(line_a.id), amount=Decimal("50.00"))],
                currency="USD",
                clock=self.clock,
            )
            uow.record_events(fetched.pull_domain_events())
            await uow.commit()

        today = self.clock.now().date()
        async with self._uow(self.org_a) as uow:
            summaries = await uow.parent_invoices.summarise_lines_by_vehicle_between(
                start=today, end=today
            )
            reloaded = await uow.parent_invoices.get(invoice.id)

        row = next(s for s in summaries if s.vehicle_id == "BUS0000000000000000000009")
        self.assertEqual(row.billed_amount, Decimal("100.00"))
        self.assertEqual(row.outstanding_amount, Decimal("50.00"))
        self.assertEqual(row.student_count, 2)
        self.assertIs(reloaded.status, ParentInvoiceStatus.PARTIAL)
        self.assertEqual(
            {str(l.student_id): l.amount_paid for l in reloaded.lines},
            {student_a: Decimal("50.00"), student_b: Decimal("0.00")},
        )

    # -- Currency guard (finance P0.5) ----------------------------------------------------------

    async def test_currency_queries_mirror_the_aggregate_filters(self) -> None:
        """`currencies_for_period`/`currencies_invoiced_between` must see exactly the rows the
        sums see: the period's non-cancelled invoices, in this organization only."""
        await self._generate_invoice(organization_id=self.org_a, period="2026-09")
        cancelled = await self._generate_invoice(
            organization_id=self.org_a, period="2026-09", currency="EUR"
        )
        await self._generate_invoice(organization_id=self.org_a, period="2026-10", currency="SOS")
        await self._generate_invoice(organization_id=self.org_b, period="2026-09", currency="KES")
        async with self._uow(self.org_a) as uow:
            loaded = await uow.parent_invoices.get(cancelled.id)
            loaded.cancel(reason="issued in error", clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        today = self.clock.now().date()
        async with self._uow(self.org_a) as uow:
            september = await uow.parent_invoices.currencies_for_period(
                period=BillingPeriod("2026-09")
            )
            all_periods = await uow.parent_invoices.currencies_for_period(period=None)
            invoiced_today = await uow.parent_invoices.currencies_invoiced_between(
                start=today, end=today
            )

        self.assertEqual(september, {"USD"})
        self.assertEqual(all_periods, {"USD", "SOS"})
        self.assertEqual(invoiced_today, {"USD", "SOS"})


    # -- ADR-0048: per-student fees ---------------------------------------------------------------

    async def _fee(self, org: str, student_id: str, fee: str, currency: str = "USD"):
        profile = StudentBillingProfile.open(
            id=StudentBillingProfileId(self.id_generator.new_id()),
            organization_id=OrganizationId(org),
            student_id=StudentId(student_id),
            monthly_fee=Money(amount=Decimal(fee), currency=currency),
            clock=self.clock,
        )
        async with self._uow(org) as uow:
            uow.student_billing_profiles.add(profile)
            uow.record_events(profile.pull_domain_events())
            await uow.commit()
        return profile

    async def test_student_fees_round_trip_exactly_and_stay_inside_their_organization(self) -> None:
        student_a, student_b = self.id_generator.new_id(), self.id_generator.new_id()
        await self._fee(self.org_a, student_a, "10.00")
        await self._fee(self.org_b, student_b, "30.00")

        async with self._uow(self.org_a) as uow:
            mine = await uow.student_billing_profiles.list_by_students([student_a, student_b])
            other = await uow.student_billing_profiles.get_by_student(StudentId(student_b))
        # CHAR(26) padding stripped: the key matches the unpadded id exactly.
        self.assertEqual(set(mine), {student_a})
        self.assertEqual(mine[student_a].monthly_fee, Money(amount=Decimal("10.00"), currency="USD"))
        self.assertIsNone(other)

    async def test_a_changed_fee_is_updated_in_place_and_audited(self) -> None:
        student = self.id_generator.new_id()
        profile = await self._fee(self.org_a, student, "10.00")
        async with self._uow(self.org_a) as uow:
            loaded = await uow.student_billing_profiles.get_by_student(StudentId(student))
            loaded.change_fee(monthly_fee=Money(amount=Decimal("12.50"), currency="USD"), clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT monthly_fee, row_version FROM erp_student_billing_profiles "
                        "WHERE student_id = :s"
                    ),
                    {"s": student},
                )
            ).all()
            audited = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM audit_entries WHERE entity_id = :id "
                        "AND action = 'school_erp.StudentBillingFeeSet'"
                    ),
                    {"id": str(profile.id)},
                )
            ).scalar()
        self.assertEqual([(r.monthly_fee, r.row_version) for r in rows], [(Decimal("12.50"), 2)])
        self.assertEqual(audited, 2)

    async def test_one_fee_per_student_and_never_negative(self) -> None:
        student = self.id_generator.new_id()
        await self._fee(self.org_a, student, "10.00")
        with self.assertRaises(IntegrityError):
            await self._fee(self.org_a, student, "20.00")
        now = datetime(2026, 9, 1)
        with self.assertRaises(IntegrityError):
            async with self.engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO erp_student_billing_profiles (id, created_at, updated_at, "
                        "row_version, organization_id, student_id, monthly_fee, currency) VALUES "
                        "(:id, :now, :now, 1, :org, :student, -1, 'USD')"
                    ),
                    {"id": self.id_generator.new_id(), "now": now, "org": self.org_a,
                     "student": self.id_generator.new_id()},
                )

    async def test_a_cancelled_invoice_frees_its_period_for_a_corrected_one(self) -> None:
        """The index used to be unconditional, so cancelling a wrong invoice made its period
        impossible to bill again — and made every later run for that period fail."""
        parent_id = self.id_generator.new_id()
        wrong = await self._generate_invoice(
            organization_id=self.org_a, period="2026-09", parent_id=parent_id
        )
        async with self._uow(self.org_a) as uow:
            loaded = await uow.parent_invoices.get(wrong.id)
            loaded.cancel(reason="Wrong fee", clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        corrected = await self._generate_invoice(
            organization_id=self.org_a, period="2026-09", parent_id=parent_id, amount="60.00"
        )
        self.assertNotEqual(corrected.id, wrong.id)
        with self.assertRaises(IntegrityError):
            await self._generate_invoice(
                organization_id=self.org_a, period="2026-09", parent_id=parent_id
            )

    async def test_billed_students_for_a_period_ignore_cancelled_and_other_tenants(self) -> None:
        live, cancelled, elsewhere = (self.id_generator.new_id() for _ in range(3))
        await self._generate_invoice(
            organization_id=self.org_a,
            children=[BilledChild(line_id=self.id_generator.new_id(), student_id=live, amount=Decimal("10.00"))],
        )
        voided = await self._generate_invoice(
            organization_id=self.org_a,
            children=[BilledChild(line_id=self.id_generator.new_id(), student_id=cancelled, amount=Decimal("10.00"))],
        )
        async with self._uow(self.org_a) as uow:
            loaded = await uow.parent_invoices.get(voided.id)
            loaded.cancel(reason="Issued in error", clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()
        await self._generate_invoice(
            organization_id=self.org_b,
            children=[BilledChild(line_id=self.id_generator.new_id(), student_id=elsewhere, amount=Decimal("10.00"))],
        )

        async with self._uow(self.org_a) as uow:
            billed = await uow.parent_invoices.billed_student_ids_for_period(
                period=BillingPeriod("2026-09")
            )
        self.assertIn(live, billed)
        self.assertNotIn(cancelled, billed)
        self.assertNotIn(elsewhere, billed)


if __name__ == "__main__":
    unittest.main()
