"""`platform_finance` repository integration tests against a live PostgreSQL (ADR-0040 §1).

Pre-deployment audit finding (§C/§L): `platform_finance`'s own test depth was "thin — unit/
fake-repo tests only... This is the one module where RBAC is the entire tenant gate (no
organization_id column exists to double-check against)." This file closes exactly that gap,
mirroring `test_school_erp_repository.py`'s shape for the two things only a real database proves
here:

  1. **No tenant scope exists to enforce, and that must never regress into one being added by
     accident.** `platform_expenses`/`platform_income`/`platform_financial_categories` carry no
     `organization_id` column at all (ADR-0040 §1, deliberate) — `_apply_scope` is structurally a
     no-op for these models (`hasattr(self.model, "organization_id")` is `False`), so a UoW
     constructed with an arbitrary, unrelated scope must still see every row. RBAC
     (`founder`/`finance_staff` only) is the *entire* gate; this test is what would fail loudly
     if a future change ever gave one of these models an `organization_id` column without also
     re-deriving what "scoped" should mean for platform-level data.
  2. **`NUMERIC(12,2)` round-trips as an exact `Decimal`, and the shared `sum_between`/
     `sum_by_kind_between` mixin sums correctly and excludes voided rows** — a float round-trip
     through asyncpg is where `100.00` quietly becomes `99.99999999999999`, and "excludes voided"
     is a `WHERE` clause a fake repository cannot verify.

Every test cleans up the rows it created (children before parents — none of these three tables
reference each other, but categories are created independently of ledger rows), leaving the
schema exactly as found, the same discipline `test_school_erp_repository.py` established.
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
from raad.core.tenancy.scope import TenantRegionScope
from raad.core.time.clock import SystemClock
from raad.modules.platform_finance.domain.entities import (
    PlatformExpense,
    PlatformFinancialCategory,
    PlatformIncome,
)
from raad.modules.platform_finance.domain.value_objects import (
    ExpenseKind,
    Money,
    PlatformCategoryId,
    PlatformCategoryKind,
    PlatformExpenseId,
    PlatformIncomeId,
    PlatformIncomeKind,
)
from raad.modules.platform_finance.infra.repositories import (
    SqlAlchemyPlatformFinanceUnitOfWork,
)


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = (
    "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."
)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class PlatformFinanceRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self._category_ids: list[str] = []
        self._expense_ids: list[str] = []
        self._income_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            for table, ids in (
                ("platform_expenses", self._expense_ids),
                ("platform_income", self._income_ids),
                ("platform_financial_categories", self._category_ids),
            ):
                if ids:
                    await conn.execute(
                        text(f"DELETE FROM {table} WHERE id = ANY(:ids)"), {"ids": ids}
                    )

    def _uow(self, *, foreign_scope: bool = False) -> SqlAlchemyPlatformFinanceUnitOfWork:
        """A Unit of Work, optionally carrying a scope that names an unrelated "organization" —
        proving that scope is inert here, never that it is respected. `get_platform_finance_uow`
        never sets a scope in production for exactly this reason (no column for it to match), so
        the `foreign_scope=True` case is the regression guard, not the normal path.
        """
        uow = SqlAlchemyPlatformFinanceUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )
        if foreign_scope:
            uow.scope = TenantRegionScope(organization_ids=[self.id_generator.new_id()])
        return uow

    async def _create_category(
        self, *, kind: PlatformCategoryKind = PlatformCategoryKind.EXPENSE
    ) -> PlatformFinancialCategory:
        category = PlatformFinancialCategory.create(
            id=PlatformCategoryId(self.id_generator.new_id()),
            name=f"Category {uuid.uuid4().hex[:8]}",
            kind=kind,
            clock=self.clock,
        )
        async with self._uow() as uow:
            uow.categories.add(category)
            uow.record_events(category.pull_domain_events())
            await uow.commit()
        self._category_ids.append(str(category.id))
        return category

    async def _record_expense(
        self,
        *,
        amount: str = "100.00",
        kind: ExpenseKind = ExpenseKind.RENT,
        occurred_on: date = date(2099, 1, 10),
        category_id: PlatformCategoryId | None = None,
    ) -> PlatformExpense:
        expense = PlatformExpense.record(
            id=PlatformExpenseId(self.id_generator.new_id()),
            kind=kind,
            category_id=category_id,
            amount=Money(amount=Decimal(amount), currency="USD"),
            occurred_on=occurred_on,
            clock=self.clock,
        )
        async with self._uow() as uow:
            uow.expenses.add(expense)
            uow.record_events(expense.pull_domain_events())
            await uow.commit()
        self._expense_ids.append(str(expense.id))
        return expense

    async def _record_income(
        self,
        *,
        amount: str = "200.00",
        kind: PlatformIncomeKind = PlatformIncomeKind.GRANT,
        occurred_on: date = date(2099, 1, 10),
    ) -> PlatformIncome:
        income = PlatformIncome.record(
            id=PlatformIncomeId(self.id_generator.new_id()),
            kind=kind,
            category_id=None,
            amount=Money(amount=Decimal(amount), currency="USD"),
            occurred_on=occurred_on,
            clock=self.clock,
        )
        async with self._uow() as uow:
            uow.income.add(income)
            uow.record_events(income.pull_domain_events())
            await uow.commit()
        self._income_ids.append(str(income.id))
        return income

    # -- Round-trip ---------------------------------------------------------------------------

    async def test_expense_round_trips_with_exact_decimal_amount(self) -> None:
        expense = await self._record_expense(amount="123.45")

        async with self._uow() as uow:
            fetched = await uow.expenses.get(expense.id)

        self.assertIsNotNone(fetched)
        # Exactness is the claim: Decimal("123.45"), not 123.44999999999999.
        self.assertEqual(fetched.amount.amount, Decimal("123.45"))
        self.assertEqual(fetched.kind, ExpenseKind.RENT)
        self.assertFalse(fetched.is_voided)

    async def test_income_round_trips_with_exact_decimal_amount(self) -> None:
        income = await self._record_income(amount="999.99")

        async with self._uow() as uow:
            fetched = await uow.income.get(income.id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.amount.amount, Decimal("999.99"))
        self.assertEqual(fetched.kind, PlatformIncomeKind.GRANT)

    async def test_void_reason_round_trips_on_both_ledger_tables(self) -> None:
        """`voided_reason` (migration `b3d7e1f94a26`) is persisted by the mapper, not just held
        on the in-memory aggregate — a fake repository cannot prove that."""
        expense = await self._record_expense(amount="12.00")
        income = await self._record_income(amount="34.00")

        async with self._uow() as uow:
            loaded_expense = await uow.expenses.get(expense.id)
            loaded_income = await uow.income.get(income.id)
            loaded_expense.void(reason="Entered twice", clock=self.clock)
            loaded_income.void(reason="Grant was withdrawn", clock=self.clock)
            uow.record_events(loaded_expense.pull_domain_events())
            uow.record_events(loaded_income.pull_domain_events())
            await uow.commit()

        async with self._uow() as uow:
            fetched_expense = await uow.expenses.get(expense.id)
            fetched_income = await uow.income.get(income.id)

        self.assertTrue(fetched_expense.is_voided)
        self.assertEqual(fetched_expense.voided_reason, "Entered twice")
        self.assertTrue(fetched_income.is_voided)
        self.assertEqual(fetched_income.voided_reason, "Grant was withdrawn")

    async def test_category_round_trips_and_is_listed(self) -> None:
        category = await self._create_category(kind=PlatformCategoryKind.INCOME)

        async with self._uow() as uow:
            fetched = await uow.categories.get(category.id)
            all_categories = await uow.categories.list_all()

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.kind, PlatformCategoryKind.INCOME)
        self.assertIn(str(category.id), {str(c.id) for c in all_categories})

    async def test_expense_can_carry_a_category(self) -> None:
        category = await self._create_category(kind=PlatformCategoryKind.EXPENSE)
        expense = await self._record_expense(category_id=category.id)

        async with self._uow() as uow:
            fetched = await uow.expenses.get(expense.id)

        self.assertEqual(str(fetched.category_id), str(category.id))

    # -- No tenant scope exists, and none must be silently reintroduced --------------------------

    async def test_an_unrelated_scope_does_not_hide_the_expense(self) -> None:
        """`_apply_scope` is a structural no-op here — there is no `organization_id` column for
        it to filter by. A UoW carrying some other id as its "scope" must still see this row,
        proving RBAC (not tenancy) is genuinely the only gate on this data."""
        expense = await self._record_expense(amount="55.00")

        async with self._uow(foreign_scope=True) as uow:
            fetched = await uow.expenses.get(expense.id)

        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.amount.amount, Decimal("55.00"))

    async def test_an_unrelated_scope_does_not_hide_the_category_from_list_all(self) -> None:
        category = await self._create_category()

        async with self._uow(foreign_scope=True) as uow:
            all_categories = await uow.categories.list_all()

        self.assertIn(str(category.id), {str(c.id) for c in all_categories})

    # -- Aggregates -----------------------------------------------------------------------------

    async def test_sum_between_totals_exactly_and_excludes_voided_rows(self) -> None:
        window = (date(2099, 1, 1), date(2099, 1, 31))
        await self._record_expense(amount="80.50", occurred_on=date(2099, 1, 5))
        voided = await self._record_expense(amount="1000.00", occurred_on=date(2099, 1, 6))

        async with self._uow() as uow:
            loaded = await uow.expenses.get(voided.id)
            loaded.void(reason="test cleanup", clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()

        async with self._uow() as uow:
            total = await uow.expenses.sum_between(start=window[0], end=window[1])

        # 1000.00 must be excluded — only the non-voided 80.50 counts.
        self.assertEqual(total, Decimal("80.50"))

    async def test_sum_by_kind_between_groups_correctly(self) -> None:
        window = (date(2099, 1, 1), date(2099, 1, 31))
        await self._record_expense(amount="30.00", kind=ExpenseKind.FUEL, occurred_on=date(2099, 1, 8))
        await self._record_expense(amount="20.00", kind=ExpenseKind.FUEL, occurred_on=date(2099, 1, 9))
        await self._record_expense(
            amount="500.00", kind=ExpenseKind.SALARIES, occurred_on=date(2099, 1, 9)
        )

        async with self._uow() as uow:
            by_kind = await uow.expenses.sum_by_kind_between(start=window[0], end=window[1])

        self.assertEqual(by_kind.get("fuel"), Decimal("50.00"))
        self.assertEqual(by_kind.get("salaries"), Decimal("500.00"))

    async def test_income_sum_between_excludes_out_of_window_rows(self) -> None:
        await self._record_income(amount="70.00", occurred_on=date(2099, 1, 15))
        await self._record_income(amount="9999.00", occurred_on=date(2025, 1, 1))

        async with self._uow() as uow:
            total = await uow.income.sum_between(start=date(2099, 1, 1), end=date(2099, 1, 31))

        self.assertEqual(total, Decimal("70.00"))


if __name__ == "__main__":
    unittest.main()
