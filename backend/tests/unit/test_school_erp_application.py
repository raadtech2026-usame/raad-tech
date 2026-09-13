"""Application-layer tests for `SchoolErpApplicationService` (ADR-0038, ADR-0040).

Stdlib `unittest` with in-memory fakes for all six repositories on one fake
`SchoolErpUnitOfWork` — no SQLAlchemy, no FastAPI, no database. Mirrors
`test_billing_application.py`'s exact structure.

**The invariant this file exists to protect** is the one the automatic-accounting requirement
turns on: *student transport revenue reaches Profit & Loss, the dashboard and per-bus revenue
through the payment itself, and never through a manually created `Income` row.* Three tests
assert it from different directions —

  * `ProfitAndLossTests.test_student_revenue_comes_from_payments_with_no_income_row` — a full
    fee-plan -> invoice -> payment run produces real `student_revenue` while `erp_income` stays
    empty,
  * `..._manual_income_is_a_separate_line_and_is_not_double_counted` — a donation lands in
    `other_income` only, so a school that receives both does not count either twice,
  * `VehicleFinancialOverviewTests` — per-bus collections move on the payment alone.

Also covered: the tenant guard on every write, batch-generation idempotency, payment/void
round-tripping through the invoice, and the ledger-kind guard that stops an expense being filed
under an income heading.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from raad.core.errors.exceptions import (
    AuthorizationError,
    ConflictError,
    DomainError,
    NotFoundError,
)
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.school_erp.application.commands import (
    ArchiveFeePlanCommand,
    CreateFeePlanCommand,
    CreateFinancialCategoryCommand,
    GenerateStudentInvoicesCommand,
    IssueStudentInvoiceCommand,
    RecordExpenseCommand,
    RecordIncomeCommand,
    RecordStudentPaymentCommand,
    VoidStudentPaymentCommand,
)
from raad.modules.school_erp.application.ports import (
    SchoolErpUnitOfWork,
    StudentTransportContext,
    StudentTransportContextPort,
)
from raad.modules.school_erp.application.services import SchoolErpApplicationService
from raad.modules.school_erp.domain.entities import (
    BilledChild,
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
    Money,
    OrganizationId,
    ParentBillingProfileId,
    ParentBillingProfileStatus,
    ParentId,
    ParentInvoiceId,
    ParentInvoiceStatus,
    StudentId,
    StudentInvoiceId,
    StudentInvoiceStatus,
    StudentPaymentId,
    VehicleId,
)

ORG = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG = "01J8Z3K9G6X8YV5T4N2R7QW3ZT"
STUDENT_A = "01J8Z3K9G6X8YV5T4N2R7QSTDA"
STUDENT_B = "01J8Z3K9G6X8YV5T4N2R7QSTDB"
BUS_1 = "01J8Z3K9G6X8YV5T4N2R7QBS01"
BUS_2 = "01J8Z3K9G6X8YV5T4N2R7QBS02"
#: ADR-0042 — the Parent-facing tests below seed one parent per (student, bus) pair, mirroring
#: the pre-ADR-0042 tests' own "two independent $50 StudentInvoices" shape as two independent
#: $50 ParentInvoices, since `ParentInvoice.generate` splits one family's total evenly across
#: *its own* children rather than accepting a custom amount per line.
PARENT_A = "01J8Z3K9G6X8YV5T4N2R7QPRTA"
PARENT_B = "01J8Z3K9G6X8YV5T4N2R7QPRTB"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 9, 5, 8, 0, 0, tzinfo=timezone.utc))


class SequentialIdGenerator(IdGenerator):
    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"  # 20 chars; 6 more make a 26-char ULID shape

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


def _field_text(item: object, field_name: str) -> str:
    value = getattr(item, field_name)
    value = getattr(value, "value", value)
    return "" if value is None else str(value)


def _paginate(items: list, page_request: OffsetPageRequest) -> OffsetPage:
    items = sorted(items, key=lambda item: str(item.id))
    total = len(items)
    start = page_request.offset
    return OffsetPage(
        data=items[start : start + page_request.page_size],
        total=total,
        page=page_request.page,
        page_size=page_request.page_size,
    )


# --- Fakes -----------------------------------------------------------------------------------


class InMemoryFinancialCategoryRepository(FinancialCategoryRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, FinancialCategory] = {}

    async def get(self, category_id: FinancialCategoryId) -> FinancialCategory | None:
        return self.by_id.get(str(category_id))

    def add(self, category: FinancialCategory) -> None:
        self.by_id[str(category.id)] = category

    async def list_all(self) -> list[FinancialCategory]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[FinancialCategory]:
        return _paginate(list(self.by_id.values()), page_request)


class InMemoryFeePlanRepository(FeePlanRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, FeePlan] = {}

    async def get(self, fee_plan_id: FeePlanId) -> FeePlan | None:
        return self.by_id.get(str(fee_plan_id))

    def add(self, fee_plan: FeePlan) -> None:
        self.by_id[str(fee_plan.id)] = fee_plan

    async def list_all(self) -> list[FeePlan]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[FeePlan]:
        return _paginate(list(self.by_id.values()), page_request)


class InMemoryStudentInvoiceRepository(StudentInvoiceRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, StudentInvoice] = {}

    async def get(self, invoice_id: StudentInvoiceId) -> StudentInvoice | None:
        return self.by_id.get(str(invoice_id))

    def add(self, invoice: StudentInvoice) -> None:
        self.by_id[str(invoice.id)] = invoice

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[StudentInvoice]:
        return _paginate(list(self.by_id.values()), page_request)

    async def exists_for_student_period(
        self, *, student_id: StudentId, period: BillingPeriod
    ) -> bool:
        return any(
            str(i.student_id) == str(student_id) and str(i.period) == str(period)
            for i in self.by_id.values()
        )

    async def list_for_student(self, student_id: StudentId) -> list[StudentInvoice]:
        return [i for i in self.by_id.values() if str(i.student_id) == str(student_id)]

    async def list_for_vehicle_period(
        self, *, vehicle_id: VehicleId, period: BillingPeriod | None
    ) -> list[StudentInvoice]:
        return [
            i
            for i in self.by_id.values()
            if str(i.vehicle_id) == str(vehicle_id)
            and (period is None or str(i.period) == str(period))
        ]

    async def summarise_by_vehicle(
        self, *, period: BillingPeriod | None
    ) -> list[VehicleFinancialSummary]:
        """Mirrors the real grouped query closely enough to test the service that consumes it:
        one row per `vehicle_id`, cancelled invoices excluded, balance clamped at zero."""
        buckets: dict[str | None, list[StudentInvoice]] = {}
        for invoice in self.by_id.values():
            if invoice.status is StudentInvoiceStatus.CANCELLED:
                continue
            if period is not None and str(invoice.period) != str(period):
                continue
            key = str(invoice.vehicle_id) if invoice.vehicle_id else None
            buckets.setdefault(key, []).append(invoice)
        summaries = []
        for vehicle_id, invoices in sorted(buckets.items(), key=lambda kv: kv[0] or ""):
            paid = [i for i in invoices if i.status is StudentInvoiceStatus.PAID]
            summaries.append(
                VehicleFinancialSummary(
                    vehicle_id=vehicle_id,
                    student_count=len({str(i.student_id) for i in invoices}),
                    invoice_count=len(invoices),
                    billed_amount=sum((i.net_amount for i in invoices), Decimal("0.00")),
                    collected_amount=sum(
                        (i.amount_paid for i in invoices), Decimal("0.00")
                    ),
                    outstanding_amount=sum(
                        (i.balance_due for i in invoices), Decimal("0.00")
                    ),
                    paid_student_count=len({str(i.student_id) for i in paid}),
                    unpaid_student_count=len(
                        {str(i.student_id) for i in invoices if i not in paid}
                    ),
                    currency=invoices[0].amount.currency,
                )
            )
        return summaries

    async def summarise_totals(self, *, period: BillingPeriod | None) -> FinanceTotals:
        invoices = [
            i
            for i in self.by_id.values()
            if i.status is not StudentInvoiceStatus.CANCELLED
            and (period is None or str(i.period) == str(period))
        ]
        return FinanceTotals(
            billed_amount=sum((i.net_amount for i in invoices), Decimal("0.00")),
            collected_amount=sum((i.amount_paid for i in invoices), Decimal("0.00")),
            outstanding_amount=sum((i.balance_due for i in invoices), Decimal("0.00")),
            invoice_count=len(invoices),
            paid_invoice_count=len(
                [i for i in invoices if i.status is StudentInvoiceStatus.PAID]
            ),
            overdue_invoice_count=len(
                [i for i in invoices if i.status is StudentInvoiceStatus.OVERDUE]
            ),
            currency=invoices[0].amount.currency if invoices else "USD",
        )

    async def list_overdue_candidates(self, *, as_of: date) -> list[StudentInvoice]:
        return [
            i
            for i in self.by_id.values()
            if i.due_date < as_of
            and i.status
            in (StudentInvoiceStatus.ISSUED, StudentInvoiceStatus.PARTIALLY_PAID)
        ]


class InMemoryStudentPaymentRepository(StudentPaymentRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, StudentPayment] = {}

    async def get(self, payment_id: StudentPaymentId) -> StudentPayment | None:
        return self.by_id.get(str(payment_id))

    def add(self, payment: StudentPayment) -> None:
        self.by_id[str(payment.id)] = payment

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[StudentPayment]:
        return _paginate(list(self.by_id.values()), page_request)

    async def list_for_invoice(
        self, invoice_id: StudentInvoiceId
    ) -> list[StudentPayment]:
        return [
            p for p in self.by_id.values() if str(p.invoice_id) == str(invoice_id)
        ]

    async def sum_between(self, *, start: date, end: date) -> Decimal:
        return sum(
            (
                p.amount.amount
                for p in self.by_id.values()
                if not p.is_voided and start <= p.received_on <= end
            ),
            Decimal("0.00"),
        )


class InMemoryIncomeRepository(IncomeRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Income] = {}

    async def get(self, income_id: IncomeId) -> Income | None:
        return self.by_id.get(str(income_id))

    def add(self, income: Income) -> None:
        self.by_id[str(income.id)] = income

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Income]:
        return _paginate(list(self.by_id.values()), page_request)

    async def sum_between(self, *, start: date, end: date) -> Decimal:
        return sum(
            (
                i.amount.amount
                for i in self.by_id.values()
                if not i.is_voided and start <= i.occurred_on <= end
            ),
            Decimal("0.00"),
        )

    async def sum_by_category_between(
        self, *, start: date, end: date
    ) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for income in self.by_id.values():
            if income.is_voided or not (start <= income.occurred_on <= end):
                continue
            key = str(income.category_id) if income.category_id else "uncategorised"
            totals[key] = totals.get(key, Decimal("0.00")) + income.amount.amount
        return totals


class InMemoryExpenseRepository(ExpenseRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Expense] = {}

    async def get(self, expense_id: ExpenseId) -> Expense | None:
        return self.by_id.get(str(expense_id))

    def add(self, expense: Expense) -> None:
        self.by_id[str(expense.id)] = expense

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Expense]:
        return _paginate(list(self.by_id.values()), page_request)

    def _live(self, start: date, end: date) -> list[Expense]:
        return [
            e
            for e in self.by_id.values()
            if not e.is_voided and start <= e.occurred_on <= end
        ]

    async def sum_between(self, *, start: date, end: date) -> Decimal:
        return sum((e.amount.amount for e in self._live(start, end)), Decimal("0.00"))

    async def sum_by_category_between(
        self, *, start: date, end: date
    ) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for expense in self._live(start, end):
            key = str(expense.category_id) if expense.category_id else "uncategorised"
            totals[key] = totals.get(key, Decimal("0.00")) + expense.amount.amount
        return totals

    async def sum_by_vehicle_between(
        self, *, start: date, end: date
    ) -> dict[str, Decimal]:
        """Mirrors the corrected SQL: expenses with no `vehicle_id` are excluded entirely.

        The real query used to `GROUP BY vehicle_id` including NULL and hand the caller a `""`
        bucket, which the service then charged to the "Unassigned" row.
        """
        totals: dict[str, Decimal] = {}
        for expense in self._live(start, end):
            if expense.vehicle_id is None:
                continue
            key = str(expense.vehicle_id)
            totals[key] = totals.get(key, Decimal("0.00")) + expense.amount.amount
        return totals


class InMemoryParentBillingProfileRepository(ParentBillingProfileRepository):
    """ADR-0042. Not exercised by the P&L/Finance-Summary/Vehicle-Overview tests below (they
    seed `ParentInvoice` rows directly), but the fake `SchoolErpUnitOfWork` must implement the
    full port regardless."""

    def __init__(self) -> None:
        self.by_id: dict[str, ParentBillingProfile] = {}

    async def get(self, profile_id: ParentBillingProfileId) -> ParentBillingProfile | None:
        return self.by_id.get(str(profile_id))

    async def get_by_parent(self, parent_id: ParentId) -> ParentBillingProfile | None:
        return next(
            (p for p in self.by_id.values() if str(p.parent_id) == str(parent_id)), None
        )

    def add(self, profile: ParentBillingProfile) -> None:
        self.by_id[str(profile.id)] = profile

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[ParentBillingProfile]:
        return _paginate(list(self.by_id.values()), page_request)

    async def list_active_for_billing(
        self, *, as_of_period: BillingPeriod
    ) -> list[ParentBillingProfile]:
        return [
            p
            for p in self.by_id.values()
            if p.status is ParentBillingProfileStatus.ACTIVE
            and str(p.billing_start_period) <= str(as_of_period)
        ]


class InMemoryParentInvoiceRepository(ParentInvoiceRepository):
    """ADR-0042 — mirrors `SqlAlchemyParentInvoiceRepository`'s own grouped-query semantics
    closely enough to test the service/reports that consume them: cancelled invoices excluded,
    balances clamped at zero, and `summarise_by_vehicle`'s pro-rata collected-share allocation
    (`line.amount * invoice.amount_paid / invoice.amount`) reproduced exactly."""

    def __init__(self) -> None:
        self.by_id: dict[str, ParentInvoice] = {}

    async def get(self, invoice_id: ParentInvoiceId) -> ParentInvoice | None:
        return self.by_id.get(str(invoice_id))

    async def get_by_parent_period(
        self, *, parent_id: ParentId, period: BillingPeriod
    ) -> ParentInvoice | None:
        return next(
            (
                i
                for i in self.by_id.values()
                if str(i.parent_id) == str(parent_id) and str(i.period) == str(period)
            ),
            None,
        )

    async def exists_for_parent_period(
        self, *, parent_id: ParentId, period: BillingPeriod
    ) -> bool:
        return any(
            str(i.parent_id) == str(parent_id)
            and str(i.period) == str(period)
            and i.status is not ParentInvoiceStatus.CANCELLED
            for i in self.by_id.values()
        )

    def add(self, invoice: ParentInvoice) -> None:
        self.by_id[str(invoice.id)] = invoice

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[ParentInvoice]:
        return _paginate(list(self.by_id.values()), page_request)

    async def list_for_parent(self, parent_id: ParentId) -> list[ParentInvoice]:
        return [i for i in self.by_id.values() if str(i.parent_id) == str(parent_id)]

    def _live(self, *, period: BillingPeriod | None) -> list[ParentInvoice]:
        return [
            i
            for i in self.by_id.values()
            if i.status is not ParentInvoiceStatus.CANCELLED
            and (period is None or str(i.period) == str(period))
        ]

    async def summarise_totals(self, *, period: BillingPeriod | None = None) -> FinanceTotals:
        invoices = self._live(period=period)
        return FinanceTotals(
            billed_amount=sum((i.amount.amount for i in invoices), Decimal("0.00")),
            collected_amount=sum((i.amount_paid for i in invoices), Decimal("0.00")),
            outstanding_amount=sum((i.balance_due for i in invoices), Decimal("0.00")),
            invoice_count=len(invoices),
            paid_invoice_count=len(
                [i for i in invoices if i.status is ParentInvoiceStatus.PAID]
            ),
            overdue_invoice_count=0,
            currency=invoices[0].amount.currency if invoices else "USD",
        )

    async def summarise_by_vehicle(
        self, *, period: BillingPeriod | None = None
    ) -> list[VehicleFinancialSummary]:
        buckets: dict[str | None, list[tuple]] = {}
        for invoice in self._live(period=period):
            share_ratio = (
                invoice.amount_paid / invoice.amount.amount
                if invoice.amount.amount > Decimal("0.00")
                else Decimal("0.00")
            )
            is_settled = invoice.amount_paid >= invoice.amount.amount
            for line in invoice.lines:
                key = str(line.vehicle_id) if line.vehicle_id else None
                collected_share = (line.amount.amount * share_ratio).quantize(Decimal("0.01"))
                buckets.setdefault(key, []).append(
                    (line, invoice, collected_share, is_settled)
                )

        summaries = []
        for vehicle_id, rows in sorted(buckets.items(), key=lambda kv: kv[0] or ""):
            billed = sum((line.amount.amount for line, _, _, _ in rows), Decimal("0.00"))
            collected = sum((share for _, _, share, _ in rows), Decimal("0.00"))
            outstanding = max(billed - collected, Decimal("0.00"))
            settled_students = {
                str(line.student_id) for line, _, _, settled in rows if settled
            }
            all_students = {str(line.student_id) for line, _, _, _ in rows}
            summaries.append(
                VehicleFinancialSummary(
                    vehicle_id=vehicle_id,
                    student_count=len(all_students),
                    invoice_count=len({str(inv.id) for _, inv, _, _ in rows}),
                    billed_amount=billed,
                    collected_amount=collected,
                    outstanding_amount=outstanding,
                    paid_student_count=len(settled_students),
                    unpaid_student_count=len(all_students - settled_students),
                    currency=rows[0][1].amount.currency,
                )
            )
        return summaries

    async def sum_collected_between(self, *, start: date, end: date) -> Decimal:
        return sum(
            (
                i.amount_paid
                for i in self.by_id.values()
                if i.status is not ParentInvoiceStatus.CANCELLED
                and start <= i.invoice_date <= end
            ),
            Decimal("0.00"),
        )


class FakeSchoolErpUnitOfWork(SchoolErpUnitOfWork):
    def __init__(self) -> None:
        self.financial_categories = InMemoryFinancialCategoryRepository()
        self.fee_plans = InMemoryFeePlanRepository()
        self.student_invoices = InMemoryStudentInvoiceRepository()
        self.student_payments = InMemoryStudentPaymentRepository()
        self.income = InMemoryIncomeRepository()
        self.expenses = InMemoryExpenseRepository()
        self.parent_billing_profiles = InMemoryParentBillingProfileRepository()
        self.parent_invoices = InMemoryParentInvoiceRepository()
        self.recorded_events: list = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeTransportContextPort(StudentTransportContextPort):
    def __init__(self, mapping: dict[str, StudentTransportContext] | None = None) -> None:
        self.mapping = mapping or {}
        self.resolve_many_calls = 0

    async def resolve(self, *, student_id: str) -> StudentTransportContext:
        return self.mapping.get(student_id, StudentTransportContext())

    async def resolve_many(
        self, *, student_ids: list[str]
    ) -> dict[str, StudentTransportContext]:
        self.resolve_many_calls += 1
        return {sid: self.mapping[sid] for sid in student_ids if sid in self.mapping}


def org_admin(org_id: str = ORG) -> Principal:
    return Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=org_id)


def make_service(
    transport: StudentTransportContextPort | None = None,
) -> SchoolErpApplicationService:
    return SchoolErpApplicationService(
        clock=CLOCK, id_generator=SequentialIdGenerator(), transport_context=transport
    )


class _Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.uow = FakeSchoolErpUnitOfWork()
        self.transport = FakeTransportContextPort(
            {
                STUDENT_A: StudentTransportContext(vehicle_id=BUS_1, route_id="route-1"),
                STUDENT_B: StudentTransportContext(vehicle_id=BUS_2),
            }
        )
        self.service = make_service(self.transport)
        self.actor = org_admin()
        #: A dedicated id generator for `_seed_parent_invoice` — independent of whatever
        #: `SequentialIdGenerator` `make_service` constructs internally for the service under
        #: test, so seeded fixture ids can never collide with ids the service itself mints.
        self.ids = SequentialIdGenerator()

    async def _fee_plan(self, amount: str = "50.00", discount: str = "0.00") -> str:
        plan = await self.service.create_fee_plan(
            CreateFeePlanCommand(
                organization_id=ORG,
                name="Monthly transport",
                amount=amount,
                currency="USD",
                default_discount_amount=discount,
                description=None,
                actor=self.actor,
            ),
            uow=self.uow,
        )
        return plan.id

    async def _generate(
        self, fee_plan_id: str, students: list[str], period: str = "2026-09"
    ):
        return await self.service.generate_student_invoices(
            GenerateStudentInvoicesCommand(
                organization_id=ORG,
                period=period,
                due_date=date(2026, 9, 30),
                fee_plan_id=fee_plan_id,
                student_ids=students,
                actor=self.actor,
            ),
            uow=self.uow,
        )

    async def _pay(self, invoice_id: str, amount: str, on: date = date(2026, 9, 10)):
        return await self.service.record_student_payment(
            RecordStudentPaymentCommand(
                invoice_id=invoice_id,
                amount=amount,
                currency="USD",
                method="cash",
                received_on=on,
                reference=None,
                notes=None,
                actor=self.actor,
            ),
            uow=self.uow,
        )

    async def _income_category(self) -> str:
        category = await self.service.create_financial_category(
            CreateFinancialCategoryCommand(
                organization_id=ORG,
                name="Donations",
                kind="income",
                parent_category_id=None,
                description=None,
                actor=self.actor,
            ),
            uow=self.uow,
        )
        return category.id

    async def _expense_category(self) -> str:
        category = await self.service.create_financial_category(
            CreateFinancialCategoryCommand(
                organization_id=ORG,
                name="Fuel",
                kind="expense",
                parent_category_id=None,
                description=None,
                actor=self.actor,
            ),
            uow=self.uow,
        )
        return category.id

    def _seed_parent_invoice(
        self,
        parent_id: str,
        *,
        student_id: str,
        vehicle_id: str | None,
        amount: str,
        period: str = "2026-09",
        amount_paid: str | None = None,
    ) -> ParentInvoice:
        """ADR-0042 — seeds one real `ParentInvoice` directly onto the fake `parent_invoices`
        repository, the same way the real `generate_parent_invoices` use case would produce one
        for a single-child family. `amount_paid`, when given, is applied via the identical
        `set_payment_status` domain method the real payment-status endpoint calls."""
        invoice = ParentInvoice.generate(
            id=ParentInvoiceId(f"{self.ids.new_id()}"),
            organization_id=OrganizationId(ORG),
            parent_id=ParentId(parent_id),
            period=BillingPeriod(period),
            amount=Money(amount=Decimal(amount), currency="USD"),
            due_date=date(2026, 9, 30),
            children=[
                BilledChild(
                    line_id=self.ids.new_id(), student_id=student_id, vehicle_id=vehicle_id
                )
            ],
            clock=CLOCK,
            actor_id=self.actor.user_id,
        )
        if amount_paid is not None:
            paid = Decimal(amount_paid)
            total = Decimal(amount)
            if paid >= total:
                status = ParentInvoiceStatus.PAID
            elif paid <= Decimal("0.00"):
                status = ParentInvoiceStatus.UNPAID
            else:
                status = ParentInvoiceStatus.PARTIAL
            invoice.set_payment_status(status=status, amount_paid=paid, clock=CLOCK)
        self.uow.parent_invoices.add(invoice)
        return invoice


# --- The billing run -------------------------------------------------------------------------


class MonthlyBillingRunTests(_Base):
    async def test_generates_one_invoice_per_student_carrying_transport_context(
        self,
    ) -> None:
        plan_id = await self._fee_plan("50.00")
        issued = await self._generate(plan_id, [STUDENT_A, STUDENT_B])

        self.assertEqual(len(issued), 2)
        by_student = {i.student_id: i for i in issued}
        self.assertEqual(by_student[STUDENT_A].vehicle_id, BUS_1)
        self.assertEqual(by_student[STUDENT_A].route_id, "route-1")
        self.assertEqual(by_student[STUDENT_B].vehicle_id, BUS_2)
        self.assertEqual(by_student[STUDENT_A].status, "issued")
        self.assertEqual(by_student[STUDENT_A].net_amount, "50.00")

    async def test_resolves_transport_context_once_for_the_whole_cohort(self) -> None:
        plan_id = await self._fee_plan()
        await self._generate(plan_id, [STUDENT_A, STUDENT_B])
        self.assertEqual(self.transport.resolve_many_calls, 1)

    async def test_rerunning_the_same_period_is_idempotent(self) -> None:
        plan_id = await self._fee_plan()
        await self._generate(plan_id, [STUDENT_A, STUDENT_B])
        second = await self._generate(plan_id, [STUDENT_A, STUDENT_B])

        self.assertEqual(second, [])
        self.assertEqual(len(self.uow.student_invoices.by_id), 2)

    async def test_single_issue_rejects_a_duplicate_period(self) -> None:
        await self.service.issue_student_invoice(
            IssueStudentInvoiceCommand(
                organization_id=ORG,
                student_id=STUDENT_A,
                period="2026-09",
                due_date=date(2026, 9, 30),
                fee_plan_id=None,
                amount="80.00",
                currency="USD",
                discount_amount=None,
                notes=None,
                actor=self.actor,
            ),
            uow=self.uow,
        )
        with self.assertRaises(ConflictError):
            await self.service.issue_student_invoice(
                IssueStudentInvoiceCommand(
                    organization_id=ORG,
                    student_id=STUDENT_A,
                    period="2026-09",
                    due_date=date(2026, 9, 30),
                    fee_plan_id=None,
                    amount="80.00",
                    currency="USD",
                    discount_amount=None,
                    notes=None,
                    actor=self.actor,
                ),
                uow=self.uow,
            )

    async def test_an_org_admin_cannot_bill_another_organizations_students(self) -> None:
        plan_id = await self._fee_plan()
        with self.assertRaises(AuthorizationError):
            await self.service.generate_student_invoices(
                GenerateStudentInvoicesCommand(
                    organization_id=OTHER_ORG,
                    period="2026-09",
                    due_date=date(2026, 9, 30),
                    fee_plan_id=plan_id,
                    student_ids=[STUDENT_A],
                    actor=self.actor,
                ),
                uow=self.uow,
            )

    async def test_generation_rejects_a_fee_plan_from_another_organization(self) -> None:
        foreign = FeePlan.create(
            id=FeePlanId("01J8Z3K9G6X8YV5T4N2R7QFRN1"),
            organization_id=OrganizationId(OTHER_ORG),
            name="Foreign plan",
            amount=Money(amount=Decimal("10.00"), currency="USD"),
            default_discount_amount=Decimal("0.00"),
            description=None,
            clock=CLOCK,
        )
        self.uow.fee_plans.add(foreign)
        with self.assertRaises(DomainError):
            await self._generate(str(foreign.id), [STUDENT_A])


# --- Payment -> invoice ------------------------------------------------------------------------


class StudentPaymentTests(_Base):
    async def test_partial_then_final_payment_walks_the_status_ladder(self) -> None:
        plan_id = await self._fee_plan("50.00")
        (invoice,) = await self._generate(plan_id, [STUDENT_A])

        await self._pay(invoice.id, "20.00")
        stored = self.uow.student_invoices.by_id[invoice.id]
        self.assertEqual(stored.status, StudentInvoiceStatus.PARTIALLY_PAID)
        self.assertEqual(stored.balance_due, Decimal("30.00"))

        await self._pay(invoice.id, "30.00")
        self.assertEqual(stored.status, StudentInvoiceStatus.PAID)
        self.assertEqual(stored.balance_due, Decimal("0.00"))

    async def test_payment_and_invoice_advance_in_one_commit(self) -> None:
        plan_id = await self._fee_plan("50.00")
        (invoice,) = await self._generate(plan_id, [STUDENT_A])
        commits_before = self.uow.commit_count

        await self._pay(invoice.id, "50.00")

        self.assertEqual(self.uow.commit_count, commits_before + 1)
        self.assertEqual(len(self.uow.student_payments.by_id), 1)

    async def test_voiding_a_payment_reverses_the_invoice(self) -> None:
        plan_id = await self._fee_plan("50.00")
        (invoice,) = await self._generate(plan_id, [STUDENT_A])
        payment = await self._pay(invoice.id, "50.00")

        await self.service.void_student_payment(
            VoidStudentPaymentCommand(
                payment_id=payment.id, reason="Bounced cheque", actor=self.actor
            ),
            uow=self.uow,
        )

        stored = self.uow.student_invoices.by_id[invoice.id]
        self.assertEqual(stored.amount_paid, Decimal("0.00"))
        self.assertEqual(stored.status, StudentInvoiceStatus.ISSUED)
        self.assertTrue(self.uow.student_payments.by_id[payment.id].is_voided)

    async def test_voiding_twice_is_a_no_op(self) -> None:
        plan_id = await self._fee_plan("50.00")
        (invoice,) = await self._generate(plan_id, [STUDENT_A])
        payment = await self._pay(invoice.id, "50.00")
        command = VoidStudentPaymentCommand(
            payment_id=payment.id, reason=None, actor=self.actor
        )
        await self.service.void_student_payment(command, uow=self.uow)
        await self.service.void_student_payment(command, uow=self.uow)

        self.assertEqual(
            self.uow.student_invoices.by_id[invoice.id].amount_paid, Decimal("0.00")
        )

    async def test_paying_an_unknown_invoice_raises_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            await self._pay("01J8Z3K9G6X8YV5T4N2R7QZZZ9", "10.00")


# --- Automatic accounting: the rule this module exists to keep ---------------------------------


class ProfitAndLossTests(_Base):
    """ADR-0042: `get_profit_and_loss` now reads `ParentInvoice` (`sum_collected_between`,
    filtered by `invoice_date`), not `StudentPayment` — see that repository method's own
    docstring for why `invoice_date` is the correct, disclosed basis in a model with no separate
    payment-transaction ledger."""

    async def test_student_revenue_comes_from_parent_invoices_with_no_income_row(self) -> None:
        """Parent → Parent Invoice → payment status → P&L, with `erp_income` never written.

        This is the automatic-accounting requirement in one assertion: a school that has billed
        and collected sees the money in `student_revenue` (the DTO's wire field name; every
        consumer's own label reads "Parent Transportation Collections") without anyone creating
        an `Income` record, so there is no manual step to forget and no second entry to
        double-count.
        """
        self._seed_parent_invoice(
            PARENT_A, student_id=STUDENT_A, vehicle_id=BUS_1, amount="50.00",
            amount_paid="50.00",
        )
        self._seed_parent_invoice(
            PARENT_B, student_id=STUDENT_B, vehicle_id=BUS_2, amount="50.00",
            amount_paid="20.00",
        )

        pnl = await self.service.get_profit_and_loss(
            start=date(2026, 9, 1), end=date(2026, 9, 30), uow=self.uow
        )

        self.assertEqual(pnl.student_revenue, "70.00")
        self.assertEqual(pnl.other_income, "0.00")
        self.assertEqual(pnl.total_income, "70.00")
        self.assertEqual(self.uow.income.by_id, {})

    async def test_manual_income_is_a_separate_line_and_is_not_double_counted(
        self,
    ) -> None:
        self._seed_parent_invoice(
            PARENT_A, student_id=STUDENT_A, vehicle_id=BUS_1, amount="50.00",
            amount_paid="50.00",
        )

        category_id = await self._income_category()
        await self.service.record_income(
            RecordIncomeCommand(
                organization_id=ORG,
                category_id=category_id,
                amount="500.00",
                currency="USD",
                occurred_on=date(2026, 9, 12),
                description="Community donation",
                reference=None,
                actor=self.actor,
            ),
            uow=self.uow,
        )

        pnl = await self.service.get_profit_and_loss(
            start=date(2026, 9, 1), end=date(2026, 9, 30), uow=self.uow
        )

        self.assertEqual(pnl.student_revenue, "50.00")
        self.assertEqual(pnl.other_income, "500.00")
        self.assertEqual(pnl.total_income, "550.00")

    async def test_an_unpaid_invoice_contributes_no_revenue(self) -> None:
        self._seed_parent_invoice(
            PARENT_A, student_id=STUDENT_A, vehicle_id=BUS_1, amount="50.00"
        )

        pnl = await self.service.get_profit_and_loss(
            start=date(2026, 9, 1), end=date(2026, 9, 30), uow=self.uow
        )
        self.assertEqual(pnl.student_revenue, "0.00")

    async def test_expenses_reduce_net_profit(self) -> None:
        self._seed_parent_invoice(
            PARENT_A, student_id=STUDENT_A, vehicle_id=BUS_1, amount="50.00",
            amount_paid="50.00",
        )

        category_id = await self._expense_category()
        await self.service.record_expense(
            RecordExpenseCommand(
                organization_id=ORG,
                category_id=category_id,
                amount="30.00",
                currency="USD",
                occurred_on=date(2026, 9, 15),
                description="Diesel",
                reference=None,
                vehicle_id=BUS_1,
                actor=self.actor,
            ),
            uow=self.uow,
        )

        pnl = await self.service.get_profit_and_loss(
            start=date(2026, 9, 1), end=date(2026, 9, 30), uow=self.uow
        )
        self.assertEqual(pnl.total_expenses, "30.00")
        self.assertEqual(pnl.net_profit, "20.00")


class FinanceSummaryTests(_Base):
    async def test_summary_tracks_billed_collected_and_outstanding(self) -> None:
        self._seed_parent_invoice(
            PARENT_A, student_id=STUDENT_A, vehicle_id=BUS_1, amount="50.00",
            amount_paid="50.00",
        )
        self._seed_parent_invoice(
            PARENT_B, student_id=STUDENT_B, vehicle_id=BUS_2, amount="50.00",
            amount_paid="20.00",
        )

        summary = await self.service.get_finance_summary(period="2026-09", uow=self.uow)

        self.assertEqual(summary.billed_amount, "100.00")
        self.assertEqual(summary.collected_amount, "70.00")
        self.assertEqual(summary.outstanding_amount, "30.00")
        self.assertEqual(summary.invoice_count, 2)
        self.assertEqual(summary.paid_invoice_count, 1)


class VehicleFinancialOverviewTests(_Base):
    async def test_per_bus_revenue_moves_on_the_payment_alone(self) -> None:
        self._seed_parent_invoice(
            PARENT_A, student_id=STUDENT_A, vehicle_id=BUS_1, amount="50.00",
            amount_paid="50.00",
        )
        self._seed_parent_invoice(
            PARENT_B, student_id=STUDENT_B, vehicle_id=BUS_2, amount="50.00"
        )

        rows = await self.service.get_vehicle_financial_overview(
            period="2026-09", uow=self.uow
        )
        by_vehicle = {r.vehicle_id: r for r in rows}

        self.assertEqual(by_vehicle[BUS_1].collected_amount, "50.00")
        self.assertEqual(by_vehicle[BUS_1].outstanding_amount, "0.00")
        self.assertEqual(by_vehicle[BUS_2].collected_amount, "0.00")
        self.assertEqual(by_vehicle[BUS_2].outstanding_amount, "50.00")
        self.assertEqual(self.uow.income.by_id, {})

    async def test_a_vehicle_expense_is_attributed_to_that_bus_only(self) -> None:
        self._seed_parent_invoice(
            PARENT_A, student_id=STUDENT_A, vehicle_id=BUS_1, amount="50.00",
            amount_paid="50.00",
        )
        self._seed_parent_invoice(
            PARENT_B, student_id=STUDENT_B, vehicle_id=BUS_2, amount="50.00"
        )
        category_id = await self._expense_category()
        await self.service.record_expense(
            RecordExpenseCommand(
                organization_id=ORG,
                category_id=category_id,
                amount="15.00",
                currency="USD",
                occurred_on=date(2026, 9, 20),
                description="Tyres",
                reference=None,
                vehicle_id=BUS_1,
                actor=self.actor,
            ),
            uow=self.uow,
        )

        rows = await self.service.get_vehicle_financial_overview(
            period="2026-09", uow=self.uow
        )
        by_vehicle = {r.vehicle_id: r for r in rows}

        self.assertEqual(by_vehicle[BUS_1].expense_amount, "15.00")
        self.assertEqual(by_vehicle[BUS_1].net_amount, "35.00")
        self.assertEqual(by_vehicle[BUS_2].expense_amount, "0.00")


# --- Ledger guards -----------------------------------------------------------------------------


class UnattributedExpenseTests(_Base):
    async def test_an_expense_with_no_bus_is_not_charged_to_the_unassigned_row(self) -> None:
        """Organization overhead belongs in Profit & Loss, never against a bus.

        Live-reproduced before the fix: a 30.00 expense recorded with no `vehicle_id` at all
        appeared as the "Unassigned" row's attributed cost, because the grouped query returned a
        NULL bucket and the service keyed the map by `vehicle_id or ""` — collapsing "no bus
        named on the expense" and "no bus on the invoice" onto the same key.
        """
        # A student with no transport assignment — its invoice line lands in the Unassigned row.
        self._seed_parent_invoice(
            PARENT_A, student_id=STUDENT_A, vehicle_id=None, amount="50.00",
            amount_paid="50.00",
        )

        category_id = await self._expense_category()
        await self.service.record_expense(
            RecordExpenseCommand(
                organization_id=ORG,
                category_id=category_id,
                amount="30.00",
                currency="USD",
                occurred_on=date(2026, 9, 15),
                description="School rent — not bus-specific",
                reference=None,
                vehicle_id=None,
                actor=self.actor,
            ),
            uow=self.uow,
        )

        rows = await self.service.get_vehicle_financial_overview(
            period="2026-09", uow=self.uow
        )
        unassigned = next(r for r in rows if r.vehicle_id is None)
        self.assertEqual(unassigned.expense_amount, "0.00")
        self.assertEqual(unassigned.net_amount, "50.00")

        # It still reduces profit — it is a real cost, just not this pseudo-bus's.
        pnl = await self.service.get_profit_and_loss(
            start=date(2026, 9, 1), end=date(2026, 9, 30), uow=self.uow
        )
        self.assertEqual(pnl.total_expenses, "30.00")


class LedgerGuardTests(_Base):
    async def test_income_cannot_be_filed_under_an_expense_category(self) -> None:
        expense_category = await self._expense_category()
        with self.assertRaises(DomainError):
            await self.service.record_income(
                RecordIncomeCommand(
                    organization_id=ORG,
                    category_id=expense_category,
                    amount="10.00",
                    currency="USD",
                    occurred_on=date(2026, 9, 1),
                    description=None,
                    reference=None,
                    actor=self.actor,
                ),
                uow=self.uow,
            )

    async def test_expense_cannot_be_filed_under_an_income_category(self) -> None:
        income_category = await self._income_category()
        with self.assertRaises(DomainError):
            await self.service.record_expense(
                RecordExpenseCommand(
                    organization_id=ORG,
                    category_id=income_category,
                    amount="10.00",
                    currency="USD",
                    occurred_on=date(2026, 9, 1),
                    description=None,
                    reference=None,
                    vehicle_id=None,
                    actor=self.actor,
                ),
                uow=self.uow,
            )

    async def test_recording_income_for_another_organization_is_refused(self) -> None:
        with self.assertRaises(AuthorizationError):
            await self.service.record_income(
                RecordIncomeCommand(
                    organization_id=OTHER_ORG,
                    category_id=None,
                    amount="10.00",
                    currency="USD",
                    occurred_on=date(2026, 9, 1),
                    description=None,
                    reference=None,
                    actor=self.actor,
                ),
                uow=self.uow,
            )


class RoundingTests(_Base):
    async def test_amounts_round_half_up_before_reaching_money(self) -> None:
        """A bursar typing 10.005 expects 10.01, not banker's rounding's 10.00.

        `_decimal` in the application layer quantises before `Money` is constructed, so it has to
        use the same explicit ROUND_HALF_UP the value object documents — otherwise the rule holds
        only where a value happens to bypass this path.
        """
        category_id = await self._income_category()
        income = await self.service.record_income(
            RecordIncomeCommand(
                organization_id=ORG,
                category_id=category_id,
                amount="10.005",
                currency="USD",
                occurred_on=date(2026, 9, 1),
                description=None,
                reference=None,
                actor=self.actor,
            ),
            uow=self.uow,
        )
        self.assertEqual(income.amount, "10.01")


class FeePlanTests(_Base):
    async def test_archiving_a_fee_plan_leaves_issued_invoices_untouched(self) -> None:
        plan_id = await self._fee_plan("50.00")
        (invoice,) = await self._generate(plan_id, [STUDENT_A])

        await self.service.archive_fee_plan(
            ArchiveFeePlanCommand(fee_plan_id=plan_id, actor=self.actor), uow=self.uow
        )

        self.assertEqual(
            self.uow.student_invoices.by_id[invoice.id].net_amount, Decimal("50.00")
        )


class OverdueSweepTests(_Base):
    async def test_sweep_marks_only_past_due_unsettled_invoices(self) -> None:
        service = SchoolErpApplicationService(
            clock=FixedClock(datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)),
            id_generator=SequentialIdGenerator(),
            transport_context=self.transport,
        )
        plan_id = await self._fee_plan("50.00")
        invoices = await self._generate(plan_id, [STUDENT_A, STUDENT_B])
        await self._pay(invoices[0].id, "50.00")  # settled — must not be flagged

        marked = await service.mark_overdue_invoices(uow=self.uow)

        self.assertEqual(marked, 1)
        self.assertEqual(
            self.uow.student_invoices.by_id[invoices[1].id].status,
            StudentInvoiceStatus.OVERDUE,
        )
        self.assertEqual(
            self.uow.student_invoices.by_id[invoices[0].id].status,
            StudentInvoiceStatus.PAID,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
