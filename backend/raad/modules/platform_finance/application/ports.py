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
    """Collected SaaS revenue in a window, owned by `billing`."""

    @abstractmethod
    async def collected_between(self, *, start: date, end: date) -> Decimal:
        raise NotImplementedError


class PlatformFinanceUnitOfWork(UnitOfWork):
    categories: PlatformCategoryRepository
    expenses: PlatformExpenseRepository
    income: PlatformIncomeRepository
