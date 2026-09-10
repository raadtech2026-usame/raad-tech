"""SQLAlchemy repositories for `platform_finance` (ADR-0040 §1).

Composes `SqlAlchemyRepositoryBase` like every other module. **No `_apply_scope` call appears in
the hand-written aggregate queries below, and that is deliberate, not an omission** — these
tables carry no `organization_id`, so there is no tenant to scope by. RBAC is the only gate on
this data (`founder`/`finance_staff` only), which is exactly the posture `billing.plans` and
`device_inventory` already take for platform-level tables.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import FilterField, SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.platform_finance.application.ports import PlatformFinanceUnitOfWork
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
    PlatformCategoryKind,
    PlatformCategoryStatus,
    PlatformExpenseId,
    PlatformIncomeId,
    PlatformIncomeKind,
)
from raad.modules.platform_finance.infra.models import (
    PlatformExpenseModel,
    PlatformFinancialCategoryModel,
    PlatformIncomeModel,
)

_ZERO = Decimal("0.00")


def _dec(value: object) -> Decimal:
    if value is None:
        return _ZERO
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _char(value: str | None) -> str | None:
    """Strips PostgreSQL `CHAR(n)` blank padding — the same permanent rule `school_erp`'s own
    mappers document (CLAUDE.md, Permanent Engineering Lessons). Applied here for the id and
    currency columns, so a padded value never reaches the domain layer."""
    return value.rstrip() if value is not None else None


def _naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


# ---- Mappers (inlined: three small aggregates, no separate module earns its keep) ------------


def _category_to_model(
    category: PlatformFinancialCategory,
    *,
    existing: PlatformFinancialCategoryModel | None = None,
) -> PlatformFinancialCategoryModel:
    model = existing or PlatformFinancialCategoryModel(id=str(category.id))
    model.name = category.name
    model.kind = category.kind.value
    model.description = category.description
    model.status = category.status.value
    model.created_at = _naive(category.created_at)
    model.updated_at = _naive(category.updated_at)
    return model


def _model_to_category(model: PlatformFinancialCategoryModel) -> PlatformFinancialCategory:
    return PlatformFinancialCategory(
        id=PlatformCategoryId(_char(model.id)),
        name=model.name,
        kind=PlatformCategoryKind(model.kind),
        description=model.description,
        status=PlatformCategoryStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _expense_to_model(
    expense: PlatformExpense, *, existing: PlatformExpenseModel | None = None
) -> PlatformExpenseModel:
    model = existing or PlatformExpenseModel(id=str(expense.id))
    model.kind = expense.kind.value
    model.category_id = str(expense.category_id) if expense.category_id else None
    model.amount = expense.amount.amount
    model.currency = expense.amount.currency
    model.occurred_on = expense.occurred_on
    model.description = expense.description
    model.vendor = expense.vendor
    model.reference = expense.reference
    model.attachment_url = expense.attachment_url
    model.is_voided = expense.is_voided
    model.created_at = _naive(expense.created_at)
    model.updated_at = _naive(expense.updated_at)
    return model


def _model_to_expense(model: PlatformExpenseModel) -> PlatformExpense:
    return PlatformExpense(
        id=PlatformExpenseId(_char(model.id)),
        kind=ExpenseKind(model.kind),
        category_id=PlatformCategoryId(_char(model.category_id)) if model.category_id else None,
        amount=Money(amount=_dec(model.amount), currency=_char(model.currency)),
        occurred_on=model.occurred_on,
        description=model.description,
        vendor=model.vendor,
        reference=model.reference,
        attachment_url=model.attachment_url,
        is_voided=model.is_voided,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _income_to_model(
    income: PlatformIncome, *, existing: PlatformIncomeModel | None = None
) -> PlatformIncomeModel:
    model = existing or PlatformIncomeModel(id=str(income.id))
    model.kind = income.kind.value
    model.category_id = str(income.category_id) if income.category_id else None
    model.amount = income.amount.amount
    model.currency = income.amount.currency
    model.occurred_on = income.occurred_on
    model.description = income.description
    model.source = income.source
    model.reference = income.reference
    model.is_voided = income.is_voided
    model.created_at = _naive(income.created_at)
    model.updated_at = _naive(income.updated_at)
    return model


def _model_to_income(model: PlatformIncomeModel) -> PlatformIncome:
    return PlatformIncome(
        id=PlatformIncomeId(_char(model.id)),
        kind=PlatformIncomeKind(model.kind),
        category_id=PlatformCategoryId(_char(model.category_id)) if model.category_id else None,
        amount=Money(amount=_dec(model.amount), currency=_char(model.currency)),
        occurred_on=model.occurred_on,
        description=model.description,
        source=model.source,
        reference=model.reference,
        is_voided=model.is_voided,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


# ---- Repositories --------------------------------------------------------------------------


class SqlAlchemyPlatformCategoryRepository(
    SqlAlchemyRepositoryBase[PlatformFinancialCategoryModel], PlatformCategoryRepository
):
    model = PlatformFinancialCategoryModel

    filterable_fields = {"kind": FilterField(column="kind"), "status": FilterField(column="status")}
    sortable_fields = {"name": "name", "created_at": "created_at"}
    searchable_fields = ("name",)

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[PlatformFinancialCategory, PlatformFinancialCategoryModel]] = {}

    async def get(self, category_id: PlatformCategoryId) -> PlatformFinancialCategory | None:
        return self._track(await self.get_by_id(str(category_id)))

    def add(self, category: PlatformFinancialCategory) -> None:
        model = _category_to_model(category)
        super().add(model)
        self._tracked[str(category.id)] = (category, model)

    async def list_all(self) -> list[PlatformFinancialCategory]:
        rows = await self.list_scoped()
        return [_model_to_category(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for category, model in self._tracked.values():
            _category_to_model(category, existing=model)

    def _track(
        self, row: PlatformFinancialCategoryModel | None
    ) -> PlatformFinancialCategory | None:
        if row is None:
            return None
        category = _model_to_category(row)
        self._tracked[row.id] = (category, row)
        return category


class _PlatformLedgerMixin:
    """`sum_between`/`sum_by_kind_between` are identical for both ledger tables; written once so
    they cannot drift apart and silently mis-state the Platform P&L."""

    async def sum_between(self, *, start: date, end: date) -> Decimal:
        statement = select(func.coalesce(func.sum(self.model.amount), 0)).where(  # type: ignore[attr-defined]
            self.model.occurred_on >= start,  # type: ignore[attr-defined]
            self.model.occurred_on <= end,  # type: ignore[attr-defined]
            self.model.is_voided.is_(False),  # type: ignore[attr-defined]
            self.model.deleted_at.is_(None),  # type: ignore[attr-defined]
        )
        return _dec((await self._session.execute(statement)).scalar())  # type: ignore[attr-defined]

    async def sum_by_kind_between(self, *, start: date, end: date) -> dict[str, Decimal]:
        statement = (
            select(
                self.model.kind,  # type: ignore[attr-defined]
                func.coalesce(func.sum(self.model.amount), 0).label("total"),  # type: ignore[attr-defined]
            )
            .where(
                self.model.occurred_on >= start,  # type: ignore[attr-defined]
                self.model.occurred_on <= end,  # type: ignore[attr-defined]
                self.model.is_voided.is_(False),  # type: ignore[attr-defined]
                self.model.deleted_at.is_(None),  # type: ignore[attr-defined]
            )
            .group_by(self.model.kind)  # type: ignore[attr-defined]
        )
        rows = (await self._session.execute(statement)).all()  # type: ignore[attr-defined]
        return {row.kind: _dec(row.total) for row in rows}


class SqlAlchemyPlatformExpenseRepository(
    _PlatformLedgerMixin,
    SqlAlchemyRepositoryBase[PlatformExpenseModel],
    PlatformExpenseRepository,
):
    model = PlatformExpenseModel

    filterable_fields = {
        "kind": FilterField(column="kind"),
        "category_id": FilterField(column="category_id"),
        "currency": FilterField(column="currency"),
        "occurred_on": FilterField(column="occurred_on"),
    }
    sortable_fields = {
        "amount": "amount",
        "occurred_on": "occurred_on",
        "kind": "kind",
        "created_at": "created_at",
    }
    searchable_fields = ("description", "vendor", "reference")

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[PlatformExpense, PlatformExpenseModel]] = {}

    async def get(self, expense_id: PlatformExpenseId) -> PlatformExpense | None:
        return self._track(await self.get_by_id(str(expense_id)))

    def add(self, expense: PlatformExpense) -> None:
        model = _expense_to_model(expense)
        super().add(model)
        self._tracked[str(expense.id)] = (expense, model)

    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[PlatformExpense]:
        raw = await super().list_page(
            request, sort=sort or [], filters=filters or [], search=search
        )
        return OffsetPage(
            data=[self._track(row) for row in raw.data],  # type: ignore[misc]
            total=raw.total,
            page=raw.page,
            page_size=raw.page_size,
        )

    def flush_tracked_changes(self) -> None:
        for expense, model in self._tracked.values():
            _expense_to_model(expense, existing=model)

    def _track(self, row: PlatformExpenseModel | None) -> PlatformExpense | None:
        if row is None:
            return None
        expense = _model_to_expense(row)
        self._tracked[row.id] = (expense, row)
        return expense


class SqlAlchemyPlatformIncomeRepository(
    _PlatformLedgerMixin,
    SqlAlchemyRepositoryBase[PlatformIncomeModel],
    PlatformIncomeRepository,
):
    model = PlatformIncomeModel

    filterable_fields = {
        "kind": FilterField(column="kind"),
        "category_id": FilterField(column="category_id"),
        "currency": FilterField(column="currency"),
        "occurred_on": FilterField(column="occurred_on"),
    }
    sortable_fields = {
        "amount": "amount",
        "occurred_on": "occurred_on",
        "kind": "kind",
        "created_at": "created_at",
    }
    searchable_fields = ("description", "source", "reference")

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[PlatformIncome, PlatformIncomeModel]] = {}

    async def get(self, income_id: PlatformIncomeId) -> PlatformIncome | None:
        return self._track(await self.get_by_id(str(income_id)))

    def add(self, income: PlatformIncome) -> None:
        model = _income_to_model(income)
        super().add(model)
        self._tracked[str(income.id)] = (income, model)

    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[PlatformIncome]:
        raw = await super().list_page(
            request, sort=sort or [], filters=filters or [], search=search
        )
        return OffsetPage(
            data=[self._track(row) for row in raw.data],  # type: ignore[misc]
            total=raw.total,
            page=raw.page,
            page_size=raw.page_size,
        )

    def flush_tracked_changes(self) -> None:
        for income, model in self._tracked.values():
            _income_to_model(income, existing=model)

    def _track(self, row: PlatformIncomeModel | None) -> PlatformIncome | None:
        if row is None:
            return None
        income = _model_to_income(row)
        self._tracked[row.id] = (income, row)
        return income


class SqlAlchemyPlatformFinanceUnitOfWork(SqlAlchemyUnitOfWork, PlatformFinanceUnitOfWork):
    categories: SqlAlchemyPlatformCategoryRepository
    expenses: SqlAlchemyPlatformExpenseRepository
    income: SqlAlchemyPlatformIncomeRepository

    async def __aenter__(self) -> "SqlAlchemyPlatformFinanceUnitOfWork":
        await super().__aenter__()
        self.categories = SqlAlchemyPlatformCategoryRepository(self.session, scope=self.scope)
        self.expenses = SqlAlchemyPlatformExpenseRepository(self.session, scope=self.scope)
        self.income = SqlAlchemyPlatformIncomeRepository(self.session, scope=self.scope)
        return self

    async def commit(self) -> None:
        self.categories.flush_tracked_changes()
        self.expenses.flush_tracked_changes()
        self.income.flush_tracked_changes()
        await super().commit()
