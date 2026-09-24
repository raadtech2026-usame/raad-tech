"""Application service for `platform_finance` (ADR-0040 §1).

**The Platform P&L reads subscription revenue from `billing`, and never records it here.** That
is the one non-obvious thing in this file: `SubscriptionRevenuePort` returns what RAAD actually
collected in a window, `PlatformIncome` holds only the *other* revenue, and the two are summed in
`get_platform_pnl` rather than being merged into one table. Recording subscription revenue in
this module as well would count the same payments twice, which is why
`PlatformIncome.__init__` rejects `PlatformIncomeKind.SUBSCRIPTION` outright.

No `_enforce_own_organization` here: these tables carry no `organization_id`, and access is
gated entirely by RBAC (`founder`/`finance_staff`, ADR-0040 §7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from raad.core.errors.exceptions import ConflictError, DomainError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal
from raad.core.time.clock import Clock
from raad.modules.platform_finance.application.ports import (
    PlatformFinanceUnitOfWork,
    SubscriptionRevenuePort,
)
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

_ZERO = Decimal("0.00")


def _decimal(value: str, *, field: str) -> Decimal:
    try:
        # ROUND_HALF_UP, matching `Money`'s own explicit choice — see that value object's
        # comment. Quantising here with the default would overrule it before it ever applies.
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ArithmeticError, ValueError) as exc:
        raise DomainError(f"{field} must be a decimal amount: {value!r}") from exc


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


@dataclass(frozen=True)
class PlatformCategoryDTO:
    id: str
    name: str
    kind: str
    description: str | None
    status: str


@dataclass(frozen=True)
class PlatformExpenseDTO:
    id: str
    kind: str
    category_id: str | None
    amount: str
    currency: str
    occurred_on: date
    description: str | None
    vendor: str | None
    reference: str | None
    attachment_url: str | None
    is_voided: bool
    voided_reason: str | None


@dataclass(frozen=True)
class PlatformIncomeDTO:
    id: str
    kind: str
    category_id: str | None
    amount: str
    currency: str
    occurred_on: date
    description: str | None
    source: str | None
    reference: str | None
    is_voided: bool
    voided_reason: str | None


@dataclass(frozen=True)
class PlatformPnlDTO:
    """RAAD's own profit and loss for a window.

    `subscription_revenue` (what was actually *collected*) comes from `billing` through
    `SubscriptionRevenuePort`; `other_income` from this module's own table. Two lines, never
    merged — see module docstring. `subscription_invoiced`/`subscription_receivables` are the
    two further, distinct accounting facts Platform Finance requires alongside collected revenue
    (Invoiced ≠ Collected ≠ Receivables) — also read from `billing`, never recorded here, for the
    identical double-counting reason.
    """

    start: date
    end: date
    subscription_revenue: str
    #: Amount billed to organizations in this window, regardless of whether paid yet.
    subscription_invoiced: str
    #: Amount still owed as of `end` — a point-in-time balance, not a period sum.
    subscription_receivables: str
    other_income: str
    total_revenue: str
    total_expenses: str
    net_profit: str
    expenses_by_kind: dict[str, str]
    income_by_kind: dict[str, str]
    currency: str


def _category_dto(category: PlatformFinancialCategory) -> PlatformCategoryDTO:
    return PlatformCategoryDTO(
        id=str(category.id),
        name=category.name,
        kind=category.kind.value,
        description=category.description,
        status=category.status.value,
    )


def _expense_dto(expense: PlatformExpense) -> PlatformExpenseDTO:
    return PlatformExpenseDTO(
        id=str(expense.id),
        kind=expense.kind.value,
        category_id=str(expense.category_id) if expense.category_id else None,
        amount=_money(expense.amount.amount),
        currency=expense.amount.currency,
        occurred_on=expense.occurred_on,
        description=expense.description,
        vendor=expense.vendor,
        reference=expense.reference,
        attachment_url=expense.attachment_url,
        is_voided=expense.is_voided,
        voided_reason=expense.voided_reason,
    )


def _income_dto(income: PlatformIncome) -> PlatformIncomeDTO:
    return PlatformIncomeDTO(
        id=str(income.id),
        kind=income.kind.value,
        category_id=str(income.category_id) if income.category_id else None,
        amount=_money(income.amount.amount),
        currency=income.amount.currency,
        occurred_on=income.occurred_on,
        description=income.description,
        source=income.source,
        reference=income.reference,
        is_voided=income.is_voided,
        voided_reason=income.voided_reason,
    )


class PlatformFinanceApplicationService:
    #: Reporting currency for the platform ledger. RAAD's own books are kept in one currency —
    #: unlike school finance, where each organization sets its own — so the P&L reports it
    #: rather than inferring one from whichever row happened to be written first.
    DEFAULT_CURRENCY = "USD"

    def __init__(
        self,
        *,
        clock: Clock,
        id_generator: IdGenerator,
        subscription_revenue: SubscriptionRevenuePort | None = None,
    ) -> None:
        self._clock = clock
        self._id_generator = id_generator
        #: Optional so the service is constructible without `billing` wired. When absent the P&L
        #: reports subscription revenue as 0.00 — which is honest for a deployment that has not
        #: wired it, and visibly wrong rather than silently plausible if it were ever forgotten
        #: in production, since RAAD's whole revenue line would read zero.
        self._subscription_revenue = subscription_revenue

    # ---- Categories ------------------------------------------------------------------------

    async def create_category(
        self,
        *,
        name: str,
        kind: str,
        description: str | None,
        actor: Principal,
        uow: PlatformFinanceUnitOfWork,
    ) -> PlatformCategoryDTO:
        async with uow:
            category = PlatformFinancialCategory.create(
                id=PlatformCategoryId(self._id_generator.new_id()),
                name=name,
                kind=PlatformCategoryKind(kind),
                description=description,
                clock=self._clock,
                actor_id=actor.user_id,
            )
            uow.categories.add(category)
            uow.record_events(category.pull_domain_events())
            await uow.commit()
            return _category_dto(category)

    async def list_categories(
        self, *, uow: PlatformFinanceUnitOfWork
    ) -> list[PlatformCategoryDTO]:
        async with uow:
            return [_category_dto(c) for c in await uow.categories.list_all()]

    # ---- Expenses --------------------------------------------------------------------------

    async def record_expense(
        self,
        *,
        kind: str,
        category_id: str | None,
        amount: str,
        currency: str,
        occurred_on: date,
        description: str | None,
        vendor: str | None,
        reference: str | None,
        actor: Principal,
        uow: PlatformFinanceUnitOfWork,
    ) -> PlatformExpenseDTO:
        async with uow:
            resolved_category = await self._validate_category(
                uow, category_id, expected=PlatformCategoryKind.EXPENSE
            )
            expense = PlatformExpense.record(
                id=PlatformExpenseId(self._id_generator.new_id()),
                kind=ExpenseKind(kind),
                category_id=resolved_category,
                amount=Money(amount=_decimal(amount, field="amount"), currency=currency),
                occurred_on=occurred_on,
                description=description,
                vendor=vendor,
                reference=reference,
                clock=self._clock,
                actor_id=actor.user_id,
            )
            uow.expenses.add(expense)
            uow.record_events(expense.pull_domain_events())
            await uow.commit()
            return _expense_dto(expense)

    async def void_expense(
        self,
        *,
        expense_id: str,
        reason: str | None,
        actor: Principal,
        uow: PlatformFinanceUnitOfWork,
    ) -> PlatformExpenseDTO:
        async with uow:
            expense = await uow.expenses.get(PlatformExpenseId(expense_id))
            if expense is None:
                raise NotFoundError("Platform expense not found")
            expense.void(reason=reason, clock=self._clock, actor_id=actor.user_id)
            uow.record_events(expense.pull_domain_events())
            await uow.commit()
            return _expense_dto(expense)

    # ---- Income ----------------------------------------------------------------------------

    async def record_income(
        self,
        *,
        kind: str,
        category_id: str | None,
        amount: str,
        currency: str,
        occurred_on: date,
        description: str | None,
        source: str | None,
        reference: str | None,
        actor: Principal,
        uow: PlatformFinanceUnitOfWork,
    ) -> PlatformIncomeDTO:
        async with uow:
            resolved_category = await self._validate_category(
                uow, category_id, expected=PlatformCategoryKind.INCOME
            )
            income = PlatformIncome.record(
                id=PlatformIncomeId(self._id_generator.new_id()),
                kind=PlatformIncomeKind(kind),
                category_id=resolved_category,
                amount=Money(amount=_decimal(amount, field="amount"), currency=currency),
                occurred_on=occurred_on,
                description=description,
                source=source,
                reference=reference,
                clock=self._clock,
                actor_id=actor.user_id,
            )
            uow.income.add(income)
            uow.record_events(income.pull_domain_events())
            await uow.commit()
            return _income_dto(income)

    async def void_income(
        self,
        *,
        income_id: str,
        reason: str | None,
        actor: Principal,
        uow: PlatformFinanceUnitOfWork,
    ) -> PlatformIncomeDTO:
        async with uow:
            income = await uow.income.get(PlatformIncomeId(income_id))
            if income is None:
                raise NotFoundError("Platform income record not found")
            income.void(reason=reason, clock=self._clock, actor_id=actor.user_id)
            uow.record_events(income.pull_domain_events())
            await uow.commit()
            return _income_dto(income)

    # ---- Reporting -------------------------------------------------------------------------

    async def get_platform_pnl(
        self, *, start: date, end: date, uow: PlatformFinanceUnitOfWork
    ) -> PlatformPnlDTO:
        async with uow:
            # Every figure here is a plain SUM labelled with one reporting currency, so a row in
            # any other currency would be added in silently at the wrong value (finance P0.5).
            # Subscription revenue from `billing` is not covered by this check yet.
            ledger_currencies = (
                await uow.income.currencies_between(start=start, end=end)
            ) | (await uow.expenses.currencies_between(start=start, end=end))
            foreign = ledger_currencies - {self.DEFAULT_CURRENCY}
            if foreign:
                raise ConflictError(
                    "The platform P&L cannot be calculated: RAAD's ledger has entries in "
                    f"{', '.join(sorted(foreign))} in this window, but its books are kept in "
                    f"{self.DEFAULT_CURRENCY} and amounts in different currencies cannot be "
                    "added together."
                )
            other_income = await uow.income.sum_between(start=start, end=end)
            total_expenses = await uow.expenses.sum_between(start=start, end=end)
            expenses_by_kind = await uow.expenses.sum_by_kind_between(start=start, end=end)
            income_by_kind = await uow.income.sum_by_kind_between(start=start, end=end)

        subscription_revenue = _ZERO
        subscription_invoiced = _ZERO
        subscription_receivables = _ZERO
        if self._subscription_revenue is not None:
            subscription_revenue = await self._subscription_revenue.collected_between(
                start=start, end=end
            )
            subscription_invoiced = await self._subscription_revenue.invoiced_between(
                start=start, end=end
            )
            subscription_receivables = await self._subscription_revenue.receivables_asof(
                as_of=end
            )

        total_revenue = subscription_revenue + other_income
        return PlatformPnlDTO(
            start=start,
            end=end,
            subscription_revenue=_money(subscription_revenue),
            subscription_invoiced=_money(subscription_invoiced),
            subscription_receivables=_money(subscription_receivables),
            other_income=_money(other_income),
            total_revenue=_money(total_revenue),
            total_expenses=_money(total_expenses),
            net_profit=_money(total_revenue - total_expenses),
            expenses_by_kind={k: _money(v) for k, v in expenses_by_kind.items()},
            income_by_kind={k: _money(v) for k, v in income_by_kind.items()},
            currency=self.DEFAULT_CURRENCY,
        )

    # ---- Internals -------------------------------------------------------------------------

    async def _validate_category(
        self,
        uow: PlatformFinanceUnitOfWork,
        category_id: str | None,
        *,
        expected: PlatformCategoryKind,
    ) -> PlatformCategoryId | None:
        if not category_id:
            return None
        category = await uow.categories.get(PlatformCategoryId(category_id))
        if category is None:
            raise NotFoundError("Platform financial category not found")
        if category.kind is not expected:
            raise DomainError(
                f"Category {category.name!r} is an {category.kind.value} category, "
                f"not an {expected.value} category"
            )
        return category.id
