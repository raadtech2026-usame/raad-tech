"""Outbound ports for `platform_finance` (Backend LLD §4.2).

`SubscriptionRevenuePort` is how the Platform P&L learns what RAAD actually collected in
subscription revenue **without this module reading `billing`'s tables**
(`.claude/rules/backend.md` #3). Its concrete adapter lives in `core/di/` (the composition root)
and calls `billing`'s own application service — the same provisioning-port shape ADR-0003
established.

That indirection is what keeps `PlatformIncomeKind.SUBSCRIPTION` honest: subscription revenue is
*read* from billing, never *recorded* here, so the same payment can never be counted twice.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.platform_finance.domain.repositories import (
    PlatformCategoryRepository,
    PlatformExpenseRepository,
    PlatformIncomeRepository,
)


class SubscriptionRevenuePort(ABC):
    """SaaS revenue facts, owned by `billing` — three distinct numbers, never merged into one
    (Platform Finance's own "Invoiced is distinct from Collected is distinct from Receivables"
    accounting requirement)."""

    @abstractmethod
    async def collected_between(self, *, start: date, end: date) -> Decimal:
        """Actual payments received in the window (invoices whose `paid_at` falls in it)."""
        raise NotImplementedError

    @abstractmethod
    async def invoiced_between(self, *, start: date, end: date) -> Decimal:
        """Amount billed to organizations in the window (invoices `issued_at` in it), regardless
        of whether collected yet."""
        raise NotImplementedError

    @abstractmethod
    async def receivables_asof(self, *, as_of: date) -> Decimal:
        """Amount still owed as of `as_of` — a point-in-time balance, not a period sum."""
        raise NotImplementedError

    @abstractmethod
    async def currencies_between(self, *, start: date, end: date) -> set[str]:
        """The currencies of exactly the invoices behind the three figures above for this
        window (receivables as of `end`), so the P&L can refuse to add a foreign-currency
        subscription amount into RAAD's single-currency books (finance P0.5)."""
        raise NotImplementedError


class PlatformFinanceUnitOfWork(UnitOfWork):
    categories: PlatformCategoryRepository
    expenses: PlatformExpenseRepository
    income: PlatformIncomeRepository
