"""`platform_finance` (C12) domain + application tests (ADR-0040 §1).

Stdlib `unittest`, in-memory fakes, no database. This module had no test file at all before this
one; what it guards is RAAD's own books, so the gaps mattered.

**The invariant worth the most here** is the mirror of school finance's: *subscription revenue is
read from `billing`, never recorded as a `PlatformIncome` row.* `PlatformIncome.__init__`
rejects `PlatformIncomeKind.SUBSCRIPTION` outright, and `get_platform_pnl` reports it as its own
line beside `other_income` — so the same organization payment can never be counted twice, once
through `SubscriptionRevenuePort` and again by hand.

The second is structural: nothing in this module carries an `organization_id`. There is no
tenant column, therefore no scope filter, therefore RBAC is the whole gate (ADR-0040 §1/§7). The
`Money` tests below cover the third — `Decimal` with explicit `ROUND_HALF_UP`, not float and not
banker's rounding.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from raad.core.errors.exceptions import DomainError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.platform_finance.application.ports import (
    PlatformFinanceUnitOfWork,
    SubscriptionRevenuePort,
)
from raad.modules.platform_finance.application.services import (
    PlatformFinanceApplicationService,
)
from raad.modules.platform_finance.domain.entities import (
    PlatformExpense,
    PlatformFinancialCategory,
    PlatformIncome,
)
from raad.modules.platform_finance.domain.repositories import (
    PlatformCategoryRepository,
    PlatformExpenseRepository,
    PlatformIncomeRepository,
)
from raad.modules.platform_finance.domain.value_objects import (
    ExpenseKind,
    Money,
    PlatformCategoryId,
    PlatformExpenseId,
    PlatformIncomeId,
    PlatformIncomeKind,
)


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc))
ULID = "01J8Z3K9G6X8YV5T4N2R7QPF01"


class SequentialIdGenerator(IdGenerator):
    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


def _paginate(items: list, page_request: OffsetPageRequest) -> OffsetPage:
    items = sorted(items, key=lambda item: str(item.id))
    start = page_request.offset
    return OffsetPage(
        data=items[start : start + page_request.page_size],
        total=len(items),
        page=page_request.page,
        page_size=page_request.page_size,
    )


class InMemoryCategoryRepository(PlatformCategoryRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, PlatformFinancialCategory] = {}

    async def get(self, category_id: PlatformCategoryId):
        return self.by_id.get(str(category_id))

    def add(self, category: PlatformFinancialCategory) -> None:
        self.by_id[str(category.id)] = category

    async def list_all(self) -> list[PlatformFinancialCategory]:
        return list(self.by_id.values())


class InMemoryExpenseRepository(PlatformExpenseRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, PlatformExpense] = {}

    async def get(self, expense_id: PlatformExpenseId):
        return self.by_id.get(str(expense_id))

    def add(self, expense: PlatformExpense) -> None:
        self.by_id[str(expense.id)] = expense

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[PlatformExpense]:
        return _paginate(list(self.by_id.values()), page_request)

    def _live(self, start: date, end: date) -> list[PlatformExpense]:
        return [
            e
            for e in self.by_id.values()
            if not e.is_voided and start <= e.occurred_on <= end
        ]

    async def sum_between(self, *, start: date, end: date) -> Decimal:
        return sum((e.amount.amount for e in self._live(start, end)), Decimal("0.00"))

    async def sum_by_kind_between(self, *, start: date, end: date) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for expense in self._live(start, end):
            key = expense.kind.value
            totals[key] = totals.get(key, Decimal("0.00")) + expense.amount.amount
        return totals


class InMemoryIncomeRepository(PlatformIncomeRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, PlatformIncome] = {}

    async def get(self, income_id: PlatformIncomeId):
        return self.by_id.get(str(income_id))

    def add(self, income: PlatformIncome) -> None:
        self.by_id[str(income.id)] = income

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[PlatformIncome]:
        return _paginate(list(self.by_id.values()), page_request)

    def _live(self, start: date, end: date) -> list[PlatformIncome]:
        return [
            i
            for i in self.by_id.values()
            if not i.is_voided and start <= i.occurred_on <= end
        ]

    async def sum_between(self, *, start: date, end: date) -> Decimal:
        return sum((i.amount.amount for i in self._live(start, end)), Decimal("0.00"))

    async def sum_by_kind_between(self, *, start: date, end: date) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for income in self._live(start, end):
            key = income.kind.value
            totals[key] = totals.get(key, Decimal("0.00")) + income.amount.amount
        return totals


class FakePlatformFinanceUnitOfWork(PlatformFinanceUnitOfWork):
    def __init__(self) -> None:
        self.categories = InMemoryCategoryRepository()
        self.expenses = InMemoryExpenseRepository()
        self.income = InMemoryIncomeRepository()
        self.recorded_events: list = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FixedSubscriptionRevenue(SubscriptionRevenuePort):
    def __init__(self, amount: Decimal) -> None:
        self.amount = amount
        self.calls = 0

    async def collected_between(self, *, start: date, end: date) -> Decimal:
        self.calls += 1
        return self.amount

    async def invoiced_between(self, *, start: date, end: date) -> Decimal:
        return self.amount

    async def receivables_asof(self, *, as_of: date) -> Decimal:
        return self.amount


FOUNDER = Principal(user_id="founder-1", role=Role.FOUNDER, org_id=None)


class MoneyTests(unittest.TestCase):
    def test_rejects_a_float_amount(self) -> None:
        with self.assertRaises(DomainError):
            Money(amount=10.5, currency="USD")  # type: ignore[arg-type]

    def test_quantises_half_up_not_bankers(self) -> None:
        """Python's default rounding turns 10.005 into 10.00. A bursar expects 10.01."""
        self.assertEqual(
            Money(amount=Decimal("10.005"), currency="USD").amount, Decimal("10.01")
        )


class PlatformIncomeDomainTests(unittest.TestCase):
    def test_subscription_income_cannot_be_recorded_here(self) -> None:
        """The double-count guard: this revenue is `billing`'s and is read, never written."""
        with self.assertRaises(DomainError):
            PlatformIncome.record(
                id=PlatformIncomeId(ULID),
                kind=PlatformIncomeKind.SUBSCRIPTION,
                category_id=None,
                amount=Money(amount=Decimal("100.00"), currency="USD"),
                occurred_on=date(2026, 9, 1),
                clock=CLOCK,
            )

    def test_a_non_subscription_heading_records_normally(self) -> None:
        income = PlatformIncome.record(
            id=PlatformIncomeId(ULID),
            kind=PlatformIncomeKind.HARDWARE_SALE,
            category_id=None,
            amount=Money(amount=Decimal("100.00"), currency="USD"),
            occurred_on=date(2026, 9, 1),
            clock=CLOCK,
        )
        self.assertFalse(income.is_voided)
        self.assertEqual(income.amount.amount, Decimal("100.00"))

    def test_zero_amount_is_rejected(self) -> None:
        with self.assertRaises(DomainError):
            PlatformIncome.record(
                id=PlatformIncomeId(ULID),
                kind=PlatformIncomeKind.GRANT,
                category_id=None,
                amount=Money(amount=Decimal("0.00"), currency="USD"),
                occurred_on=date(2026, 9, 1),
                clock=CLOCK,
            )


class PlatformFinanceServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.uow = FakePlatformFinanceUnitOfWork()
        self.revenue = FixedSubscriptionRevenue(Decimal("1200.00"))
        self.service = PlatformFinanceApplicationService(
            clock=CLOCK,
            id_generator=SequentialIdGenerator(),
            subscription_revenue=self.revenue,
        )

    async def _expense(self, kind: str, amount: str, on: date = date(2026, 9, 10)):
        return await self.service.record_expense(
            kind=kind,
            category_id=None,
            amount=amount,
            currency="USD",
            occurred_on=on,
            description=None,
            vendor=None,
            reference=None,
            actor=FOUNDER,
            uow=self.uow,
        )

    async def test_pnl_reads_subscription_revenue_from_billing_not_from_this_table(
        self,
    ) -> None:
        await self.service.record_income(
            kind="hardware_sale",
            category_id=None,
            amount="300.00",
            currency="USD",
            occurred_on=date(2026, 9, 3),
            description="MDVR units",
            source="Reseller",
            reference=None,
            actor=FOUNDER,
            uow=self.uow,
        )
        await self._expense("salaries", "500.00")

        pnl = await self.service.get_platform_pnl(
            start=date(2026, 9, 1), end=date(2026, 9, 30), uow=self.uow
        )

        self.assertEqual(self.revenue.calls, 1)
        self.assertEqual(pnl.subscription_revenue, "1200.00")
        self.assertEqual(pnl.subscription_invoiced, "1200.00")
        self.assertEqual(pnl.subscription_receivables, "1200.00")
        self.assertEqual(pnl.other_income, "300.00")
        self.assertEqual(pnl.total_revenue, "1500.00")
        self.assertEqual(pnl.total_expenses, "500.00")
        self.assertEqual(pnl.net_profit, "1000.00")
        # Nothing in this module's own income table claims to be subscription revenue.
        self.assertNotIn("subscription", pnl.income_by_kind)

    async def test_pnl_reports_zero_subscription_revenue_when_billing_is_unwired(
        self,
    ) -> None:
        """Honest, and visibly wrong rather than plausibly wrong, if ever left unwired."""
        service = PlatformFinanceApplicationService(
            clock=CLOCK, id_generator=SequentialIdGenerator(), subscription_revenue=None
        )
        pnl = await service.get_platform_pnl(
            start=date(2026, 9, 1), end=date(2026, 9, 30), uow=self.uow
        )
        self.assertEqual(pnl.subscription_revenue, "0.00")
        self.assertEqual(pnl.subscription_invoiced, "0.00")
        self.assertEqual(pnl.subscription_receivables, "0.00")

    async def test_expenses_group_by_their_operating_heading(self) -> None:
        await self._expense("salaries", "500.00")
        await self._expense("rent", "250.00")
        await self._expense("salaries", "100.00")

        pnl = await self.service.get_platform_pnl(
            start=date(2026, 9, 1), end=date(2026, 9, 30), uow=self.uow
        )

        self.assertEqual(pnl.expenses_by_kind["salaries"], "600.00")
        self.assertEqual(pnl.expenses_by_kind["rent"], "250.00")

    async def test_voiding_an_expense_removes_it_from_the_pnl(self) -> None:
        expense = await self._expense("marketing", "80.00")
        await self.service.void_expense(
            expense_id=expense.id, reason="Duplicate entry", actor=FOUNDER, uow=self.uow
        )

        pnl = await self.service.get_platform_pnl(
            start=date(2026, 9, 1), end=date(2026, 9, 30), uow=self.uow
        )
        self.assertEqual(pnl.total_expenses, "0.00")
        self.assertTrue(self.uow.expenses.by_id[expense.id].is_voided)
        self.assertEqual(self.uow.expenses.by_id[expense.id].voided_reason, "Duplicate entry")

    async def test_voiding_without_a_reason_is_refused_and_keeps_it_in_the_pnl(self) -> None:
        expense = await self._expense("marketing", "80.00")
        for blank in (None, "", "   "):
            with self.subTest(reason=blank), self.assertRaises(DomainError):
                await self.service.void_expense(
                    expense_id=expense.id, reason=blank, actor=FOUNDER, uow=self.uow
                )
        pnl = await self.service.get_platform_pnl(
            start=date(2026, 9, 1), end=date(2026, 9, 30), uow=self.uow
        )
        self.assertEqual(pnl.total_expenses, "80.00")
        self.assertFalse(self.uow.expenses.by_id[expense.id].is_voided)

    async def test_voiding_an_unknown_expense_raises_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            await self.service.void_expense(
                expense_id="01J8Z3K9G6X8YV5T4N2R7QZZZ9",
                reason=None,
                actor=FOUNDER,
                uow=self.uow,
            )

    async def test_an_expense_cannot_be_filed_under_an_income_category(self) -> None:
        category = await self.service.create_category(
            name="Grants received",
            kind="income",
            description=None,
            actor=FOUNDER,
            uow=self.uow,
        )
        with self.assertRaises(DomainError):
            await self.service.record_expense(
                kind="rent",
                category_id=category.id,
                amount="10.00",
                currency="USD",
                occurred_on=date(2026, 9, 1),
                description=None,
                vendor=None,
                reference=None,
                actor=FOUNDER,
                uow=self.uow,
            )

    async def test_a_window_outside_the_entries_reports_nothing(self) -> None:
        await self._expense("fuel", "40.00", on=date(2026, 9, 10))
        pnl = await self.service.get_platform_pnl(
            start=date(2026, 10, 1), end=date(2026, 10, 31), uow=self.uow
        )
        self.assertEqual(pnl.total_expenses, "0.00")

    async def test_the_amount_string_rounds_half_up_before_it_reaches_money(self) -> None:
        """The application layer quantises before `Money` does, so it must round the same way.

        Leaving `_decimal` on `quantize`'s default (ROUND_HALF_EVEN) turned 10.005 into 10.00
        and left `Money`'s own explicit ROUND_HALF_UP nothing to act on — the documented rule
        would then hold only for values that reached the domain by some other path.
        """
        expense = await self._expense("rent", "10.005")
        self.assertEqual(expense.amount, "10.01")

    async def test_every_expense_heading_the_requirement_names_is_accepted(self) -> None:
        for kind in ExpenseKind:
            with self.subTest(kind=kind.value):
                await self._expense(kind.value, "1.00")
        self.assertEqual(len(self.uow.expenses.by_id), len(list(ExpenseKind)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
