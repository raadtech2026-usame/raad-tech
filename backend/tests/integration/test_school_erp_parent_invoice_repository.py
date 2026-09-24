"""`ParentBillingProfile`/`ParentInvoice` repository integration tests against a live PostgreSQL
(ADR-0042, 2026-09-11 — supersedes ADR-0041 SS1).

Mirrors `test_school_erp_repository.py`'s exact structure and reasoning — three things only a
real database can prove, and all three carry money:

  1. **Tenant isolation** across the two new tables, the identical highest-risk property
     `test_school_erp_repository.py` already exists to protect for the other six.
  2. **`NUMERIC(12,2)` round-trips as an exact `Decimal`**, including the child-line amounts an
     equal split produces (`33.34`/`33.33`/`33.33` for a $100 total across three children).
  3. **`summarise_by_vehicle`'s pro-rata collected-share allocation** — hand-written SQL
     (`line.amount * invoice.amount_paid / invoice.amount`) that no fake can verify, since it
     depends on PostgreSQL's own decimal division and `GREATEST`/`NULLIF` clamping.

Every test cleans up the rows it created (lines before invoices, invoices before profiles),
leaving the schema exactly as found.
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
from raad.modules.school_erp.domain.entities import BilledChild, ParentBillingProfile, ParentInvoice
from raad.modules.school_erp.domain.value_objects import (
    BillingPeriod,
    Money,
    OrganizationId,
    ParentBillingProfileId,
    ParentId,
    ParentInvoiceId,
    ParentInvoiceStatus,
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
            amount=Money(amount=Decimal(amount), currency=currency),
            due_date=date(2026, 9, 30),
            children=children
            or [
                BilledChild(
                    line_id=self.id_generator.new_id(),
                    student_id=self.id_generator.new_id(),
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
        """A $100 total split across three children ($33.34/$33.33/$33.33) must round-trip
        through `NUMERIC(12,2)` exactly, on both the invoice total and every line."""
        student_ids = [self.id_generator.new_id() for _ in range(3)]
        children = [
            BilledChild(line_id=self.id_generator.new_id(), student_id=sid) for sid in student_ids
        ]
        invoice = await self._generate_invoice(
            organization_id=self.org_a, amount="100.00", children=children
        )

        async with self._uow(self.org_a) as uow:
            fetched = await uow.parent_invoices.get(invoice.id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.amount.amount, Decimal("100.00"))
        self.assertEqual(len(fetched.lines), 3)
        self.assertEqual(
            sum((line.amount.amount for line in fetched.lines), Decimal("0.00")),
            Decimal("100.00"),
        )

    async def test_parent_billing_profile_round_trips(self) -> None:
        profile = ParentBillingProfile.open(
            id=ParentBillingProfileId(self.id_generator.new_id()),
            organization_id=OrganizationId(self.org_a),
            parent_id=ParentId(self.id_generator.new_id()),
            monthly_fee=Money(amount=Decimal("80.00"), currency="USD"),
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
        self.assertEqual(fetched.monthly_fee.amount, Decimal("80.00"))
        self.assertEqual(fetched.due_day, 10)

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

    async def test_summarise_by_vehicle_prorates_the_collected_share(self) -> None:
        """One invoice, two lines on the same bus, 60% collected — each line's collected share
        must be its own 60% (`GREATEST`/`NULLIF`-safe SQL division), not the invoice's raw
        `amount_paid` double-counted onto both lines."""
        student_a, student_b = self.id_generator.new_id(), self.id_generator.new_id()
        children = [
            BilledChild(line_id=self.id_generator.new_id(), student_id=student_a, vehicle_id="BUS0000000000000000000009"),
            BilledChild(line_id=self.id_generator.new_id(), student_id=student_b, vehicle_id="BUS0000000000000000000009"),
        ]
        invoice = await self._generate_invoice(
            organization_id=self.org_a, amount="100.00", period="2026-09", children=children
        )
        async with self._uow(self.org_a) as uow:
            fetched = await uow.parent_invoices.get(invoice.id)
            fetched.set_payment_status(
                status=ParentInvoiceStatus.PARTIAL, amount_paid=Decimal("60.00"), clock=self.clock
            )
            uow.record_events(fetched.pull_domain_events())
            await uow.commit()

        async with self._uow(self.org_a) as uow:
            summaries = await uow.parent_invoices.summarise_by_vehicle(
                period=BillingPeriod("2026-09")
            )

        row = next(s for s in summaries if s.vehicle_id == "BUS0000000000000000000009")
        self.assertEqual(row.billed_amount, Decimal("100.00"))
        self.assertEqual(row.collected_amount, Decimal("60.00"))
        self.assertEqual(row.outstanding_amount, Decimal("40.00"))
        self.assertEqual(row.student_count, 2)

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


if __name__ == "__main__":
    unittest.main()
