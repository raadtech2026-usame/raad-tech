"""Repository interfaces for `platform_finance` (Backend LLD §7.1/§7.2). Framework-free."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.modules.platform_finance.domain.entities import (
    PlatformExpense,
    PlatformFinancialCategory,
    PlatformIncome,
)
from raad.modules.platform_finance.domain.value_objects import (
    PlatformCategoryId,
    PlatformExpenseId,
    PlatformIncomeId,
)


class PlatformCategoryRepository(ABC):
    @abstractmethod
    async def get(self, category_id: PlatformCategoryId) -> PlatformFinancialCategory | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, category: PlatformFinancialCategory) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[PlatformFinancialCategory]:
        raise NotImplementedError


class PlatformExpenseRepository(ABC):
    @abstractmethod
    async def get(self, expense_id: PlatformExpenseId) -> PlatformExpense | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, expense: PlatformExpense) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[PlatformExpense]:
        raise NotImplementedError

    @abstractmethod
    async def sum_between(self, *, start: date, end: date) -> Decimal:
        raise NotImplementedError

    @abstractmethod
    async def currencies_between(self, *, start: date, end: date) -> set[str]:
        """The distinct currencies among exactly the rows `sum_between` adds up — the P&L checks
        them before presenting a total (finance P0.5)."""
        raise NotImplementedError

    @abstractmethod
    async def sum_by_kind_between(self, *, start: date, end: date) -> dict[str, Decimal]:
        """Cost per operating heading — what makes "where does the money go" answerable."""
        raise NotImplementedError


class PlatformIncomeRepository(ABC):
    @abstractmethod
    async def get(self, income_id: PlatformIncomeId) -> PlatformIncome | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, income: PlatformIncome) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[PlatformIncome]:
        raise NotImplementedError

    @abstractmethod
    async def sum_between(self, *, start: date, end: date) -> Decimal:
        raise NotImplementedError

    @abstractmethod
    async def currencies_between(self, *, start: date, end: date) -> set[str]:
        """The distinct currencies among exactly the rows `sum_between` adds up — the P&L checks
        them before presenting a total (finance P0.5)."""
        raise NotImplementedError

    @abstractmethod
    async def sum_by_kind_between(self, *, start: date, end: date) -> dict[str, Decimal]:
        raise NotImplementedError
