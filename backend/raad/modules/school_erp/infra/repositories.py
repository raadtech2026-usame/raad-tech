"""SQLAlchemy repository implementations for `school_erp` (ADR-0038, ADR-0040).

Composes `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query mechanics; every ORM
<-> domain conversion goes through `mappers.py` (§7.1's "aggregate-in/aggregate-out" rule).
Mirrors `billing.infra.repositories`'s identity-map / `flush_tracked_changes` pattern exactly —
a handler mutating a `get()`-returned domain object needs that bridge, since SQLAlchemy only
dirty-tracks its own ORM rows, not detached domain objects.

**Tenant-scoping (ADR-0021) is automatic and unconditional here.** Every table in this module
carries `organization_id`, so `SqlAlchemyRepositoryBase._apply_scope` applies the caller's
resolved `TenantRegionScope` inside `get_by_id` and every `list_*` — unlike `billing.plans`,
where the guard is inert for want of the column. The hand-written aggregate queries below
(`summarise_by_vehicle`, `sum_between`, ...) do **not** go through the base class's helpers, so
each one applies `_apply_scope` explicitly. That is the single most important line in each of
them: a grouped financial total that forgot it would leak one school's revenue into another's
dashboard.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Select, case, func, select
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
from raad.modules.school_erp.application.ports import SchoolErpUnitOfWork
from raad.modules.school_erp.domain.entities import (
    Expense,
    FeePlan,
    FinancialCategory,
    Income,
    ParentBillingProfile,
    ParentInvoice,
    StudentInvoice,
    StudentPayment,
)
from raad.modules.school_erp.domain.repositories import (
    ExpenseRepository,
    FeePlanRepository,
    FinanceTotals,
    FinancialCategoryRepository,
    IncomeRepository,
    ParentBillingProfileRepository,
    ParentInvoiceRepository,
    StudentInvoiceRepository,
    StudentPaymentRepository,
    VehicleFinancialSummary,
)
from raad.modules.school_erp.domain.value_objects import (
    BillingPeriod,
    ExpenseId,
    FeePlanId,
    FinancialCategoryId,
    IncomeId,
    ParentBillingProfileId,
    ParentId,
    ParentInvoiceId,
    StudentId,
    StudentInvoiceId,
    StudentPaymentId,
    VehicleId,
)
from raad.modules.school_erp.infra.mappers import (
    expense_to_model,
    fee_plan_to_model,
    financial_category_to_model,
    income_to_model,
    model_to_expense,
    model_to_fee_plan,
    model_to_financial_category,
    model_to_income,
    model_to_parent_billing_profile,
    model_to_parent_invoice,
    model_to_student_invoice,
    model_to_student_payment,
    parent_billing_profile_to_model,
    parent_invoice_to_model,
    student_invoice_to_model,
    student_payment_to_model,
)
from raad.modules.school_erp.infra.models import (
    ExpenseModel,
    FeePlanModel,
    FinancialCategoryModel,
    IncomeModel,
    ParentBillingProfileModel,
    ParentInvoiceLineModel,
    ParentInvoiceModel,
    StudentInvoiceModel,
    StudentPaymentModel,
)

_ZERO = Decimal("0.00")
#: Reporting falls back to this when a scope genuinely holds no rows, so a KPI card renders
#: "0.00 USD" rather than crashing on a missing currency. Never used to *invent* an amount.
_DEFAULT_CURRENCY = "USD"


def _char(value: str | None) -> str | None:
    """Strips PostgreSQL `CHAR(n)` blank padding on raw row reads.

    The hand-written aggregate queries below return `vehicle_id`, `category_id` and `currency`
    straight off the row, bypassing `mappers.py` entirely — so they need this independently.
    Without it a padded `vehicle_id` becomes a *different dict key* from the same id read
    through a mapper, and the invoice-revenue-to-expense join in
    `SchoolErpApplicationService.get_vehicle_financial_overview` silently matches nothing.
    """
    return value.rstrip() if value is not None else None


def _dec(value: object) -> Decimal:
    if value is None:
        return _ZERO
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))


# ============================================================================================
# FinancialCategory
# ============================================================================================


class SqlAlchemyFinancialCategoryRepository(
    SqlAlchemyRepositoryBase[FinancialCategoryModel], FinancialCategoryRepository
):
    model = FinancialCategoryModel

    filterable_fields = {
        # ADR-0021 keeps this honest: `_apply_scope` still narrows every query to the
        # caller's own scope, so this filter can only narrow *within* what the caller may
        # already see. It exists so a Founder can focus one organization.
        "organization_id": FilterField(column="organization_id"),
        "kind": FilterField(column="kind"),
        "status": FilterField(column="status"),
        "parent_category_id": FilterField(column="parent_category_id"),
    }
    sortable_fields = {
        "name": "name",
        "kind": "kind",
        "status": "status",
        "created_at": "created_at",
    }
    searchable_fields = ("name",)

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[FinancialCategory, FinancialCategoryModel]] = {}

    async def get(self, category_id: FinancialCategoryId) -> FinancialCategory | None:
        return self._track(await self.get_by_id(str(category_id)))

    def add(self, category: FinancialCategory) -> None:
        model = financial_category_to_model(category)
        super().add(model)
        self._tracked[str(category.id)] = (category, model)

    async def list_all(self) -> list[FinancialCategory]:
        rows = await self.list_scoped()
        return [model_to_financial_category(row) for row in rows]

    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[FinancialCategory]:
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
        for category, model in self._tracked.values():
            financial_category_to_model(category, existing=model)

    def _track(self, row: FinancialCategoryModel | None) -> FinancialCategory | None:
        if row is None:
            return None
        category = model_to_financial_category(row)
        self._tracked[row.id] = (category, row)
        return category


# ============================================================================================
# FeePlan
# ============================================================================================


class SqlAlchemyFeePlanRepository(SqlAlchemyRepositoryBase[FeePlanModel], FeePlanRepository):
    model = FeePlanModel

    filterable_fields = {
        # ADR-0021 keeps this honest: `_apply_scope` still narrows every query to the
        # caller's own scope, so this filter can only narrow *within* what the caller may
        # already see. It exists so a Founder can focus one organization.
        "organization_id": FilterField(column="organization_id"),
        "status": FilterField(column="status"),
        "currency": FilterField(column="currency"),
    }
    sortable_fields = {
        "name": "name",
        "amount": "amount",
        "status": "status",
        "created_at": "created_at",
    }
    searchable_fields = ("name",)

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[FeePlan, FeePlanModel]] = {}

    async def get(self, fee_plan_id: FeePlanId) -> FeePlan | None:
        return self._track(await self.get_by_id(str(fee_plan_id)))

    def add(self, fee_plan: FeePlan) -> None:
        model = fee_plan_to_model(fee_plan)
        super().add(model)
        self._tracked[str(fee_plan.id)] = (fee_plan, model)

    async def list_all(self) -> list[FeePlan]:
        rows = await self.list_scoped()
        return [model_to_fee_plan(row) for row in rows]

    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[FeePlan]:
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
        for fee_plan, model in self._tracked.values():
            fee_plan_to_model(fee_plan, existing=model)

    def _track(self, row: FeePlanModel | None) -> FeePlan | None:
        if row is None:
            return None
        fee_plan = model_to_fee_plan(row)
        self._tracked[row.id] = (fee_plan, row)
        return fee_plan


# ============================================================================================
# StudentInvoice
# ============================================================================================


class SqlAlchemyStudentInvoiceRepository(
    SqlAlchemyRepositoryBase[StudentInvoiceModel], StudentInvoiceRepository
):
    model = StudentInvoiceModel

    filterable_fields = {
        # ADR-0021 keeps this honest: `_apply_scope` still narrows every query to the
        # caller's own scope, so this filter can only narrow *within* what the caller may
        # already see. It exists so a Founder can focus one organization.
        "organization_id": FilterField(column="organization_id"),
        "status": FilterField(column="status"),
        "period": FilterField(column="period"),
        "student_id": FilterField(column="student_id"),
        "vehicle_id": FilterField(column="vehicle_id"),
        "route_id": FilterField(column="route_id"),
        "fee_plan_id": FilterField(column="fee_plan_id"),
        "currency": FilterField(column="currency"),
    }
    sortable_fields = {
        "period": "period",
        "amount": "amount",
        "amount_paid": "amount_paid",
        "due_date": "due_date",
        "status": "status",
        "issued_at": "issued_at",
        "created_at": "created_at",
    }
    searchable_fields = ()

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[StudentInvoice, StudentInvoiceModel]] = {}

    async def get(self, invoice_id: StudentInvoiceId) -> StudentInvoice | None:
        return self._track(await self.get_by_id(str(invoice_id)))

    def add(self, invoice: StudentInvoice) -> None:
        model = student_invoice_to_model(invoice)
        super().add(model)
        self._tracked[str(invoice.id)] = (invoice, model)

    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[StudentInvoice]:
        raw = await super().list_page(
            request, sort=sort or [], filters=filters or [], search=search
        )
        return OffsetPage(
            data=[self._track(row) for row in raw.data],  # type: ignore[misc]
            total=raw.total,
            page=raw.page,
            page_size=raw.page_size,
        )

    def _live(self) -> Select:
        """Base statement for every hand-written query below: scoped, and soft-delete aware.

        Factored out precisely so no aggregate query can forget either. `_apply_scope` here is
        what stops one organization's grouped revenue totals from including another's rows.
        """
        return self._apply_scope(
            select(self.model).where(self.model.deleted_at.is_(None))
        )

    async def exists_for_student_period(
        self, *, student_id: StudentId, period: BillingPeriod
    ) -> bool:
        statement = self._apply_scope(
            select(func.count())
            .select_from(self.model)
            .where(
                self.model.student_id == str(student_id),
                self.model.period == str(period),
                self.model.deleted_at.is_(None),
            )
        )
        result = await self._session.execute(statement)
        return (result.scalar() or 0) > 0

    async def list_for_student(self, student_id: StudentId) -> list[StudentInvoice]:
        statement = self._live().where(self.model.student_id == str(student_id))
        statement = statement.order_by(self.model.period.desc())
        rows = (await self._session.execute(statement)).scalars().all()
        return [model_to_student_invoice(row) for row in rows]

    async def list_for_vehicle_period(
        self, *, vehicle_id: VehicleId, period: BillingPeriod | None = None
    ) -> list[StudentInvoice]:
        statement = self._live().where(self.model.vehicle_id == str(vehicle_id))
        if period is not None:
            statement = statement.where(self.model.period == str(period))
        statement = statement.order_by(self.model.period.desc(), self.model.student_id)
        rows = (await self._session.execute(statement)).scalars().all()
        return [model_to_student_invoice(row) for row in rows]

    async def summarise_by_vehicle(
        self, *, period: BillingPeriod | None = None
    ) -> list[VehicleFinancialSummary]:
        """The whole Vehicle Financial Overview in one grouped query.

        `net = amount - discount_amount` is computed in SQL rather than in Python so the database
        does the aggregation over what may be thousands of invoices, and so "outstanding" is
        `GREATEST(net - paid, 0)` — clamped per row, exactly as `StudentInvoice.balance_due`
        clamps it, so one overpaid student can never mask another student's real debt inside a
        bus total.

        Cancelled invoices are excluded: a waived fee is not billed revenue and must not appear
        in a bus's expected income.
        """
        net = self.model.amount - self.model.discount_amount
        outstanding = func.greatest(net - self.model.amount_paid, 0)
        is_settled = case((self.model.amount_paid >= net, 1), else_=0)

        statement = self._apply_scope(
            select(
                self.model.vehicle_id,
                func.count(func.distinct(self.model.student_id)).label("student_count"),
                func.count(self.model.id).label("invoice_count"),
                func.coalesce(func.sum(net), 0).label("billed_amount"),
                func.coalesce(func.sum(self.model.amount_paid), 0).label("collected_amount"),
                func.coalesce(func.sum(outstanding), 0).label("outstanding_amount"),
                func.coalesce(
                    func.sum(case((is_settled == 1, 1), else_=0)), 0
                ).label("paid_invoice_count"),
                func.coalesce(
                    func.sum(case((is_settled == 0, 1), else_=0)), 0
                ).label("unpaid_invoice_count"),
                func.min(self.model.currency).label("currency"),
            )
            .where(
                self.model.deleted_at.is_(None),
                self.model.status != "cancelled",
            )
            .group_by(self.model.vehicle_id)
        )
        if period is not None:
            statement = statement.where(self.model.period == str(period))

        rows = (await self._session.execute(statement)).all()
        return [
            VehicleFinancialSummary(
                vehicle_id=_char(row.vehicle_id),
                student_count=int(row.student_count or 0),
                invoice_count=int(row.invoice_count or 0),
                billed_amount=_dec(row.billed_amount),
                collected_amount=_dec(row.collected_amount),
                outstanding_amount=_dec(row.outstanding_amount),
                paid_student_count=int(row.paid_invoice_count or 0),
                unpaid_student_count=int(row.unpaid_invoice_count or 0),
                currency=_char(row.currency) or _DEFAULT_CURRENCY,
            )
            for row in rows
        ]

    async def summarise_totals(
        self, *, period: BillingPeriod | None = None
    ) -> FinanceTotals:
        net = self.model.amount - self.model.discount_amount
        outstanding = func.greatest(net - self.model.amount_paid, 0)

        statement = self._apply_scope(
            select(
                func.coalesce(func.sum(net), 0).label("billed_amount"),
                func.coalesce(func.sum(self.model.amount_paid), 0).label("collected_amount"),
                func.coalesce(func.sum(outstanding), 0).label("outstanding_amount"),
                func.count(self.model.id).label("invoice_count"),
                func.coalesce(
                    func.sum(case((self.model.status == "paid", 1), else_=0)), 0
                ).label("paid_invoice_count"),
                func.coalesce(
                    func.sum(case((self.model.status == "overdue", 1), else_=0)), 0
                ).label("overdue_invoice_count"),
                func.min(self.model.currency).label("currency"),
            ).where(
                self.model.deleted_at.is_(None),
                self.model.status != "cancelled",
            )
        )
        if period is not None:
            statement = statement.where(self.model.period == str(period))

        row = (await self._session.execute(statement)).one()
        return FinanceTotals(
            billed_amount=_dec(row.billed_amount),
            collected_amount=_dec(row.collected_amount),
            outstanding_amount=_dec(row.outstanding_amount),
            invoice_count=int(row.invoice_count or 0),
            paid_invoice_count=int(row.paid_invoice_count or 0),
            overdue_invoice_count=int(row.overdue_invoice_count or 0),
            currency=_char(row.currency) or _DEFAULT_CURRENCY,
        )

    async def list_overdue_candidates(self, *, as_of: date) -> list[StudentInvoice]:
        statement = self._live().where(
            self.model.due_date < as_of,
            self.model.status.in_(("issued", "partially_paid")),
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._track(row) for row in rows]  # type: ignore[misc]

    def flush_tracked_changes(self) -> None:
        for invoice, model in self._tracked.values():
            student_invoice_to_model(invoice, existing=model)

    def _track(self, row: StudentInvoiceModel | None) -> StudentInvoice | None:
        if row is None:
            return None
        invoice = model_to_student_invoice(row)
        self._tracked[row.id] = (invoice, row)
        return invoice


# ============================================================================================
# StudentPayment
# ============================================================================================


class SqlAlchemyStudentPaymentRepository(
    SqlAlchemyRepositoryBase[StudentPaymentModel], StudentPaymentRepository
):
    model = StudentPaymentModel

    filterable_fields = {
        # ADR-0021 keeps this honest: `_apply_scope` still narrows every query to the
        # caller's own scope, so this filter can only narrow *within* what the caller may
        # already see. It exists so a Founder can focus one organization.
        "organization_id": FilterField(column="organization_id"),
        "invoice_id": FilterField(column="invoice_id"),
        "student_id": FilterField(column="student_id"),
        "method": FilterField(column="method"),
        "currency": FilterField(column="currency"),
    }
    sortable_fields = {
        "amount": "amount",
        "received_on": "received_on",
        "created_at": "created_at",
    }
    searchable_fields = ("reference",)

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[StudentPayment, StudentPaymentModel]] = {}

    async def get(self, payment_id: StudentPaymentId) -> StudentPayment | None:
        return self._track(await self.get_by_id(str(payment_id)))

    def add(self, payment: StudentPayment) -> None:
        model = student_payment_to_model(payment)
        super().add(model)
        self._tracked[str(payment.id)] = (payment, model)

    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[StudentPayment]:
        raw = await super().list_page(
            request, sort=sort or [], filters=filters or [], search=search
        )
        return OffsetPage(
            data=[self._track(row) for row in raw.data],  # type: ignore[misc]
            total=raw.total,
            page=raw.page,
            page_size=raw.page_size,
        )

    async def list_for_invoice(
        self, invoice_id: StudentInvoiceId
    ) -> list[StudentPayment]:
        statement = self._apply_scope(
            select(self.model).where(
                self.model.invoice_id == str(invoice_id),
                self.model.deleted_at.is_(None),
            )
        ).order_by(self.model.received_on.desc())
        rows = (await self._session.execute(statement)).scalars().all()
        return [model_to_student_payment(row) for row in rows]

    async def sum_between(self, *, start: date, end: date) -> Decimal:
        """Voided payments are excluded — money that was reversed was never collected."""
        statement = self._apply_scope(
            select(func.coalesce(func.sum(self.model.amount), 0)).where(
                self.model.received_on >= start,
                self.model.received_on <= end,
                self.model.is_voided.is_(False),
                self.model.deleted_at.is_(None),
            )
        )
        return _dec((await self._session.execute(statement)).scalar())

    def flush_tracked_changes(self) -> None:
        for payment, model in self._tracked.values():
            student_payment_to_model(payment, existing=model)

    def _track(self, row: StudentPaymentModel | None) -> StudentPayment | None:
        if row is None:
            return None
        payment = model_to_student_payment(row)
        self._tracked[row.id] = (payment, row)
        return payment


# ============================================================================================
# Income / Expense
# ============================================================================================


class _LedgerRepositoryMixin:
    """Shared aggregate queries for the two structurally identical ledger tables.

    `Income` and `Expense` differ only in which side of the ledger they sit on and in `Expense`'s
    extra `vehicle_id`. Their `sum_between`/`sum_by_category_between` bodies would otherwise be
    byte-identical, and a divergence between them would silently mis-state Profit & Loss — so
    they are written once here rather than twice.
    """

    async def sum_between(self, *, start: date, end: date) -> Decimal:
        statement = self._apply_scope(  # type: ignore[attr-defined]
            select(func.coalesce(func.sum(self.model.amount), 0)).where(  # type: ignore[attr-defined]
                self.model.occurred_on >= start,  # type: ignore[attr-defined]
                self.model.occurred_on <= end,  # type: ignore[attr-defined]
                self.model.is_voided.is_(False),  # type: ignore[attr-defined]
                self.model.deleted_at.is_(None),  # type: ignore[attr-defined]
            )
        )
        return _dec((await self._session.execute(statement)).scalar())  # type: ignore[attr-defined]

    async def sum_by_category_between(
        self, *, start: date, end: date
    ) -> dict[str, Decimal]:
        """Uncategorised rows are keyed `""` rather than dropped — a real school will have some,
        and silently omitting them would make the category breakdown fail to add up to the
        total sitting next to it."""
        statement = self._apply_scope(  # type: ignore[attr-defined]
            select(
                self.model.category_id,  # type: ignore[attr-defined]
                func.coalesce(func.sum(self.model.amount), 0).label("total"),  # type: ignore[attr-defined]
            )
            .where(
                self.model.occurred_on >= start,  # type: ignore[attr-defined]
                self.model.occurred_on <= end,  # type: ignore[attr-defined]
                self.model.is_voided.is_(False),  # type: ignore[attr-defined]
                self.model.deleted_at.is_(None),  # type: ignore[attr-defined]
            )
            .group_by(self.model.category_id)  # type: ignore[attr-defined]
        )
        rows = (await self._session.execute(statement)).all()  # type: ignore[attr-defined]
        return {(_char(row.category_id) or ""): _dec(row.total) for row in rows}

    async def currencies_between(self, *, start: date, end: date) -> set[str]:
        """Same filters as `sum_between`, so the check covers exactly the rows it adds up."""
        statement = self._apply_scope(  # type: ignore[attr-defined]
            select(self.model.currency)  # type: ignore[attr-defined]
            .where(
                self.model.occurred_on >= start,  # type: ignore[attr-defined]
                self.model.occurred_on <= end,  # type: ignore[attr-defined]
                self.model.is_voided.is_(False),  # type: ignore[attr-defined]
                self.model.deleted_at.is_(None),  # type: ignore[attr-defined]
            )
            .distinct()
        )
        rows = (await self._session.execute(statement)).scalars().all()  # type: ignore[attr-defined]
        return {_char(currency) for currency in rows}


class SqlAlchemyIncomeRepository(
    _LedgerRepositoryMixin, SqlAlchemyRepositoryBase[IncomeModel], IncomeRepository
):
    model = IncomeModel

    filterable_fields = {
        # ADR-0021 keeps this honest: `_apply_scope` still narrows every query to the
        # caller's own scope, so this filter can only narrow *within* what the caller may
        # already see. It exists so a Founder can focus one organization.
        "organization_id": FilterField(column="organization_id"),
        "category_id": FilterField(column="category_id"),
        "currency": FilterField(column="currency"),
        "occurred_on": FilterField(column="occurred_on"),
    }
    sortable_fields = {
        "amount": "amount",
        "occurred_on": "occurred_on",
        "created_at": "created_at",
    }
    searchable_fields = ("description", "reference")

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[Income, IncomeModel]] = {}

    async def get(self, income_id: IncomeId) -> Income | None:
        return self._track(await self.get_by_id(str(income_id)))

    def add(self, income: Income) -> None:
        model = income_to_model(income)
        super().add(model)
        self._tracked[str(income.id)] = (income, model)

    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[Income]:
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
            income_to_model(income, existing=model)

    def _track(self, row: IncomeModel | None) -> Income | None:
        if row is None:
            return None
        income = model_to_income(row)
        self._tracked[row.id] = (income, row)
        return income


class SqlAlchemyExpenseRepository(
    _LedgerRepositoryMixin, SqlAlchemyRepositoryBase[ExpenseModel], ExpenseRepository
):
    model = ExpenseModel

    filterable_fields = {
        # ADR-0021 keeps this honest: `_apply_scope` still narrows every query to the
        # caller's own scope, so this filter can only narrow *within* what the caller may
        # already see. It exists so a Founder can focus one organization.
        "organization_id": FilterField(column="organization_id"),
        "category_id": FilterField(column="category_id"),
        "vehicle_id": FilterField(column="vehicle_id"),
        "currency": FilterField(column="currency"),
        "occurred_on": FilterField(column="occurred_on"),
    }
    sortable_fields = {
        "amount": "amount",
        "occurred_on": "occurred_on",
        "created_at": "created_at",
    }
    searchable_fields = ("description", "reference")

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[Expense, ExpenseModel]] = {}

    async def get(self, expense_id: ExpenseId) -> Expense | None:
        return self._track(await self.get_by_id(str(expense_id)))

    def add(self, expense: Expense) -> None:
        model = expense_to_model(expense)
        super().add(model)
        self._tracked[str(expense.id)] = (expense, model)

    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[Expense]:
        raw = await super().list_page(
            request, sort=sort or [], filters=filters or [], search=search
        )
        return OffsetPage(
            data=[self._track(row) for row in raw.data],  # type: ignore[misc]
            total=raw.total,
            page=raw.page,
            page_size=raw.page_size,
        )

    async def sum_by_vehicle_between(
        self, *, start: date, end: date
    ) -> dict[str, Decimal]:
        statement = self._apply_scope(
            select(
                self.model.vehicle_id,
                func.coalesce(func.sum(self.model.amount), 0).label("total"),
            )
            .where(
                self.model.occurred_on >= start,
                self.model.occurred_on <= end,
                self.model.is_voided.is_(False),
                self.model.deleted_at.is_(None),
                # Only expenses that actually name a bus. Without this, `GROUP BY vehicle_id`
                # produces a NULL bucket holding every unattributed cost — rent, salaries, office
                # supplies — and the caller, which keys this map by `vehicle_id or ""`, charged
                # that entire organization-wide pool to the "Unassigned" row of the Vehicle
                # Financial Overview. Live-reproduced: a 30.00 expense with no `vehicle_id` at all
                # appeared as that row's attributed cost. General overhead belongs in Profit &
                # Loss, never against a bus.
                self.model.vehicle_id.is_not(None),
            )
            .group_by(self.model.vehicle_id)
        )
        rows = (await self._session.execute(statement)).all()
        return {_char(row.vehicle_id): _dec(row.total) for row in rows}

    def flush_tracked_changes(self) -> None:
        for expense, model in self._tracked.values():
            expense_to_model(expense, existing=model)

    def _track(self, row: ExpenseModel | None) -> Expense | None:
        if row is None:
            return None
        expense = model_to_expense(row)
        self._tracked[row.id] = (expense, row)
        return expense


# ============================================================================================
# ParentBillingProfile / ParentInvoice (ADR-0042)
# ============================================================================================


class SqlAlchemyParentBillingProfileRepository(
    SqlAlchemyRepositoryBase[ParentBillingProfileModel], ParentBillingProfileRepository
):
    model = ParentBillingProfileModel

    filterable_fields = {
        "organization_id": FilterField(column="organization_id"),
        "parent_id": FilterField(column="parent_id"),
        "status": FilterField(column="status"),
    }
    sortable_fields = {
        "created_at": "created_at",
        "monthly_fee": "monthly_fee",
    }
    searchable_fields = ()

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[ParentBillingProfile, ParentBillingProfileModel]] = {}

    async def get(self, profile_id: ParentBillingProfileId) -> ParentBillingProfile | None:
        return self._track(await self.get_by_id(str(profile_id)))

    async def get_by_parent(self, parent_id: ParentId) -> ParentBillingProfile | None:
        statement = self._apply_scope(
            select(self.model).where(
                self.model.parent_id == str(parent_id),
                self.model.deleted_at.is_(None),
            )
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return self._track(row)

    def add(self, profile: ParentBillingProfile) -> None:
        model = parent_billing_profile_to_model(profile)
        super().add(model)
        self._tracked[str(profile.id)] = (profile, model)

    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[ParentBillingProfile]:
        raw = await super().list_page(
            request, sort=sort or [], filters=filters or [], search=search
        )
        return OffsetPage(
            data=[self._track(row) for row in raw.data],  # type: ignore[misc]
            total=raw.total,
            page=raw.page,
            page_size=raw.page_size,
        )

    async def list_active_for_billing(
        self, *, as_of_period: BillingPeriod
    ) -> list[ParentBillingProfile]:
        statement = self._apply_scope(
            select(self.model).where(
                self.model.status == "active",
                self.model.billing_start_period <= str(as_of_period),
                self.model.deleted_at.is_(None),
            )
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._track(row) for row in rows]  # type: ignore[misc]

    def flush_tracked_changes(self) -> None:
        for profile, model in self._tracked.values():
            parent_billing_profile_to_model(profile, existing=model)

    def _track(
        self, row: ParentBillingProfileModel | None
    ) -> ParentBillingProfile | None:
        if row is None:
            return None
        profile = model_to_parent_billing_profile(row)
        self._tracked[row.id] = (profile, row)
        return profile


class SqlAlchemyParentInvoiceRepository(
    SqlAlchemyRepositoryBase[ParentInvoiceModel], ParentInvoiceRepository
):
    model = ParentInvoiceModel

    filterable_fields = {
        "organization_id": FilterField(column="organization_id"),
        "parent_id": FilterField(column="parent_id"),
        "period": FilterField(column="period"),
        "status": FilterField(column="status"),
    }
    sortable_fields = {
        "period": "period",
        "amount": "amount",
        "amount_paid": "amount_paid",
        "due_date": "due_date",
        "status": "status",
        "created_at": "created_at",
    }
    searchable_fields = ()

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[ParentInvoice, ParentInvoiceModel]] = {}

    async def get(self, invoice_id: ParentInvoiceId) -> ParentInvoice | None:
        return self._track(await self.get_by_id(str(invoice_id)))

    async def get_by_parent_period(
        self, *, parent_id: ParentId, period: BillingPeriod
    ) -> ParentInvoice | None:
        statement = self._apply_scope(
            select(self.model).where(
                self.model.parent_id == str(parent_id),
                self.model.period == str(period),
                self.model.deleted_at.is_(None),
            )
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return self._track(row)

    async def exists_for_parent_period(
        self, *, parent_id: ParentId, period: BillingPeriod
    ) -> bool:
        statement = self._apply_scope(
            select(func.count())
            .select_from(self.model)
            .where(
                self.model.parent_id == str(parent_id),
                self.model.period == str(period),
                self.model.status != "cancelled",
                self.model.deleted_at.is_(None),
            )
        )
        result = await self._session.execute(statement)
        return (result.scalar() or 0) > 0

    def add(self, invoice: ParentInvoice) -> None:
        model = parent_invoice_to_model(invoice)
        super().add(model)
        self._tracked[str(invoice.id)] = (invoice, model)

    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[ParentInvoice]:
        raw = await super().list_page(
            request, sort=sort or [], filters=filters or [], search=search
        )
        return OffsetPage(
            data=[self._track(row) for row in raw.data],  # type: ignore[misc]
            total=raw.total,
            page=raw.page,
            page_size=raw.page_size,
        )

    async def list_for_parent(self, parent_id: ParentId) -> list[ParentInvoice]:
        statement = self._apply_scope(
            select(self.model).where(
                self.model.parent_id == str(parent_id),
                self.model.deleted_at.is_(None),
            )
        ).order_by(self.model.period.desc())
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._track(row) for row in rows]  # type: ignore[misc]

    async def summarise_totals(
        self, *, period: BillingPeriod | None = None
    ) -> FinanceTotals:
        outstanding = func.greatest(self.model.amount - self.model.amount_paid, 0)
        statement = self._apply_scope(
            select(
                func.coalesce(func.sum(self.model.amount), 0).label("expected_amount"),
                func.coalesce(func.sum(self.model.amount_paid), 0).label(
                    "collected_amount"
                ),
                func.coalesce(func.sum(outstanding), 0).label("receivable_amount"),
                func.count(self.model.id).label("invoice_count"),
                func.coalesce(
                    func.sum(case((self.model.status == "paid", 1), else_=0)), 0
                ).label("paid_invoice_count"),
                func.min(self.model.currency).label("currency"),
            ).where(
                self.model.deleted_at.is_(None),
                self.model.status != "cancelled",
            )
        )
        if period is not None:
            statement = statement.where(self.model.period == str(period))

        row = (await self._session.execute(statement)).one()
        return FinanceTotals(
            billed_amount=_dec(row.expected_amount),
            collected_amount=_dec(row.collected_amount),
            outstanding_amount=_dec(row.receivable_amount),
            invoice_count=int(row.invoice_count or 0),
            paid_invoice_count=int(row.paid_invoice_count or 0),
            # ParentInvoiceStatus has no `overdue` state (the directive's own three-status
            # list) — always 0, never derived from `due_date`, so a report never implies an
            # overdue concept this aggregate does not track.
            overdue_invoice_count=0,
            currency=_char(row.currency) or _DEFAULT_CURRENCY,
        )

    async def summarise_by_vehicle(
        self, *, period: BillingPeriod | None = None
    ) -> list[VehicleFinancialSummary]:
        """Grouped over `erp_parent_invoice_lines.vehicle_id`, joined back to the owning
        invoice for `amount`/`amount_paid` — the pro-rata collected-share allocation ADR-0042
        decision 1 documents (`line.amount * invoice.amount_paid / invoice.amount`), since
        payment is only ever recorded against the whole family invoice, never per child."""
        line = ParentInvoiceLineModel
        invoice = self.model

        collected_share = func.coalesce(
            line.amount * invoice.amount_paid / func.nullif(invoice.amount, 0), 0
        )
        outstanding_share = func.greatest(line.amount - collected_share, 0)
        is_settled = case((invoice.amount_paid >= invoice.amount, 1), else_=0)

        statement = self._apply_scope(
            select(
                line.vehicle_id,
                func.count(func.distinct(line.student_id)).label("student_count"),
                func.count(func.distinct(line.parent_invoice_id)).label("invoice_count"),
                func.coalesce(func.sum(line.amount), 0).label("billed_amount"),
                func.coalesce(func.sum(collected_share), 0).label("collected_amount"),
                func.coalesce(func.sum(outstanding_share), 0).label(
                    "outstanding_amount"
                ),
                func.coalesce(
                    func.sum(case((is_settled == 1, 1), else_=0)), 0
                ).label("paid_invoice_count"),
                func.coalesce(
                    func.sum(case((is_settled == 0, 1), else_=0)), 0
                ).label("unpaid_invoice_count"),
                func.min(invoice.currency).label("currency"),
            )
            .select_from(line)
            .join(invoice, invoice.id == line.parent_invoice_id)
            .where(
                invoice.deleted_at.is_(None),
                invoice.status != "cancelled",
                line.deleted_at.is_(None),
            )
            .group_by(line.vehicle_id)
        )
        if period is not None:
            statement = statement.where(invoice.period == str(period))

        rows = (await self._session.execute(statement)).all()
        return [
            VehicleFinancialSummary(
                vehicle_id=_char(row.vehicle_id),
                student_count=int(row.student_count or 0),
                invoice_count=int(row.invoice_count or 0),
                billed_amount=_dec(row.billed_amount),
                collected_amount=_dec(row.collected_amount),
                outstanding_amount=_dec(row.outstanding_amount),
                paid_student_count=int(row.paid_invoice_count or 0),
                unpaid_student_count=int(row.unpaid_invoice_count or 0),
                currency=_char(row.currency) or _DEFAULT_CURRENCY,
            )
            for row in rows
        ]

    async def sum_collected_between(self, *, start: date, end: date) -> Decimal:
        statement = self._apply_scope(
            select(func.coalesce(func.sum(self.model.amount_paid), 0)).where(
                self.model.invoice_date >= start,
                self.model.invoice_date <= end,
                self.model.status != "cancelled",
                self.model.deleted_at.is_(None),
            )
        )
        return _dec((await self._session.execute(statement)).scalar())

    async def currencies_for_period(self, *, period: BillingPeriod | None = None) -> set[str]:
        statement = self._apply_scope(
            select(self.model.currency)
            .where(
                self.model.deleted_at.is_(None),
                self.model.status != "cancelled",
            )
            .distinct()
        )
        if period is not None:
            statement = statement.where(self.model.period == str(period))
        rows = (await self._session.execute(statement)).scalars().all()
        return {_char(currency) for currency in rows}

    async def currencies_invoiced_between(self, *, start: date, end: date) -> set[str]:
        statement = self._apply_scope(
            select(self.model.currency)
            .where(
                self.model.invoice_date >= start,
                self.model.invoice_date <= end,
                self.model.status != "cancelled",
                self.model.deleted_at.is_(None),
            )
            .distinct()
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return {_char(currency) for currency in rows}

    def flush_tracked_changes(self) -> None:
        for invoice, model in self._tracked.values():
            parent_invoice_to_model(invoice, existing=model)

    def _track(self, row: ParentInvoiceModel | None) -> ParentInvoice | None:
        if row is None:
            return None
        invoice = model_to_parent_invoice(row)
        self._tracked[row.id] = (invoice, row)
        return invoice


# ============================================================================================
# Unit of Work
# ============================================================================================


class SqlAlchemySchoolErpUnitOfWork(SqlAlchemyUnitOfWork, SchoolErpUnitOfWork):
    """Concrete `SchoolErpUnitOfWork` (Backend LLD §8.2/§6.2). Constructs this module's six
    repositories once the session is open, and re-syncs every tracked aggregate's in-place
    mutations onto its ORM row immediately before delegating to `SqlAlchemyUnitOfWork.commit()`
    — identical shape to `SqlAlchemyBillingUnitOfWork`.

    Recording a student payment mutates two aggregates (`StudentPayment` created, `StudentInvoice`
    advanced) and both are flushed here, in one transaction — which is exactly why they share a
    Unit of Work rather than each owning their own.
    """

    financial_categories: SqlAlchemyFinancialCategoryRepository
    fee_plans: SqlAlchemyFeePlanRepository
    student_invoices: SqlAlchemyStudentInvoiceRepository
    student_payments: SqlAlchemyStudentPaymentRepository
    income: SqlAlchemyIncomeRepository
    expenses: SqlAlchemyExpenseRepository
    parent_billing_profiles: SqlAlchemyParentBillingProfileRepository
    parent_invoices: SqlAlchemyParentInvoiceRepository

    async def __aenter__(self) -> "SqlAlchemySchoolErpUnitOfWork":
        await super().__aenter__()
        self.financial_categories = SqlAlchemyFinancialCategoryRepository(
            self.session, scope=self.scope
        )
        self.fee_plans = SqlAlchemyFeePlanRepository(self.session, scope=self.scope)
        self.student_invoices = SqlAlchemyStudentInvoiceRepository(
            self.session, scope=self.scope
        )
        self.student_payments = SqlAlchemyStudentPaymentRepository(
            self.session, scope=self.scope
        )
        self.income = SqlAlchemyIncomeRepository(self.session, scope=self.scope)
        self.expenses = SqlAlchemyExpenseRepository(self.session, scope=self.scope)
        self.parent_billing_profiles = SqlAlchemyParentBillingProfileRepository(
            self.session, scope=self.scope
        )
        self.parent_invoices = SqlAlchemyParentInvoiceRepository(
            self.session, scope=self.scope
        )
        return self

    async def commit(self) -> None:
        self.financial_categories.flush_tracked_changes()
        self.fee_plans.flush_tracked_changes()
        self.student_invoices.flush_tracked_changes()
        self.student_payments.flush_tracked_changes()
        self.income.flush_tracked_changes()
        self.expenses.flush_tracked_changes()
        self.parent_billing_profiles.flush_tracked_changes()
        self.parent_invoices.flush_tracked_changes()
        await super().commit()
