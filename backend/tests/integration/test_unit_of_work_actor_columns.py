"""`created_by`/`updated_by` are stamped by `SqlAlchemyUnitOfWork.commit()` (finance P0.6).

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
otherwise.

Why an integration test: the rule that matters most here is negative. Repositories re-project
every tracked aggregate onto its ORM row before commit, including rows that were only *read*, so
a naive "stamp every dirty row" would turn each read into an UPDATE and bump `row_version`. Only
a real SQLAlchemy session and a real row can show that this does not happen. Uses
`platform_expenses` because it carries every audit column and needs no tenant set-up; the
stamping itself lives in `core/db/unit_of_work.py` and is the same for every module.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from raad.core.audit.writer import AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.logging.context import bind_context, reset_context
from raad.core.time.clock import SystemClock
from raad.modules.platform_finance.domain.entities import PlatformExpense
from raad.modules.platform_finance.domain.value_objects import (
    ExpenseKind,
    Money,
    PlatformExpenseId,
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
class ActorColumnStampingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.ids = UlidGenerator()
        self.clock = SystemClock()
        self.creator = self.ids.new_id()
        self.voider = self.ids.new_id()
        self.reader = self.ids.new_id()
        self._expense_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._expense_ids:
                await conn.execute(
                    text("DELETE FROM platform_expenses WHERE id = ANY(:ids)"),
                    {"ids": self._expense_ids},
                )
        await self.engine.dispose()

    def _uow(self) -> SqlAlchemyPlatformFinanceUnitOfWork:
        return SqlAlchemyPlatformFinanceUnitOfWork(
            self.session_factory, OutboxWriter(), AuditWriter()
        )

    async def _as(self, actor_id: str | None, action) -> None:
        tokens = bind_context(principal_id=actor_id)
        try:
            await action()
        finally:
            reset_context(tokens)

    async def _row(self, expense_id: str):
        async with self.engine.connect() as conn:
            return (
                await conn.execute(
                    text(
                        "SELECT created_by, updated_by, row_version, is_voided "
                        "FROM platform_expenses WHERE id = :id"
                    ),
                    {"id": expense_id},
                )
            ).one()

    async def _record(self) -> str:
        expense = PlatformExpense.record(
            id=PlatformExpenseId(self.ids.new_id()),
            kind=ExpenseKind.OTHER,
            category_id=None,
            amount=Money(amount=Decimal("10.00"), currency="USD"),
            occurred_on=date(2097, 6, 1),
            clock=self.clock,
        )
        async with self._uow() as uow:
            uow.expenses.add(expense)
            uow.record_events(expense.pull_domain_events())
            await uow.commit()
        self._expense_ids.append(str(expense.id))
        return str(expense.id)

    async def test_insert_stamps_both_columns_with_the_acting_user(self) -> None:
        created: list[str] = []

        async def record() -> None:
            created.append(await self._record())

        await self._as(self.creator, record)
        row = await self._row(created[0])
        self.assertEqual((row.created_by, row.updated_by), (self.creator, self.creator))

    async def test_an_update_stamps_updated_by_and_keeps_created_by(self) -> None:
        created: list[str] = []

        async def record() -> None:
            created.append(await self._record())

        await self._as(self.creator, record)

        async def void() -> None:
            async with self._uow() as uow:
                loaded = await uow.expenses.get(PlatformExpenseId(created[0]))
                loaded.void(reason="entered twice", clock=self.clock)
                uow.record_events(loaded.pull_domain_events())
                await uow.commit()

        await self._as(self.voider, void)
        row = await self._row(created[0])
        self.assertTrue(row.is_voided)
        self.assertEqual((row.created_by, row.updated_by), (self.creator, self.voider))

    async def test_a_read_that_changes_nothing_is_not_stamped_or_versioned(self) -> None:
        created: list[str] = []

        async def record() -> None:
            created.append(await self._record())

        await self._as(self.creator, record)
        before = await self._row(created[0])

        async def read_and_commit() -> None:
            async with self._uow() as uow:
                await uow.expenses.get(PlatformExpenseId(created[0]))
                await uow.commit()

        await self._as(self.reader, read_and_commit)
        after = await self._row(created[0])
        self.assertEqual(after.updated_by, self.creator)
        self.assertEqual(after.row_version, before.row_version)

    async def test_without_a_bound_user_the_columns_stay_null(self) -> None:
        created: list[str] = []

        async def record() -> None:
            created.append(await self._record())

        await self._as(None, record)
        row = await self._row(created[0])
        self.assertEqual((row.created_by, row.updated_by), (None, None))


if __name__ == "__main__":
    unittest.main()
