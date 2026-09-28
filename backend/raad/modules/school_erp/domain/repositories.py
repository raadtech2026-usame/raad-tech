"""Repository interfaces for the `school_erp` module (Backend LLD §5.1/§7.1/§7.2). Framework-free
— no SQLAlchemy/FastAPI/Pydantic.

Each mirrors the minimal `get`/`add`/`list_all`/`list_page` shape `billing`'s own five
repositories establish, plus the aggregate-specific finders the ERP's own read requirements
genuinely need. Every finder below exists because a named requirement asks for it, not
speculatively:

- `StudentInvoiceRepository.exists_for_student_period` — enforces "one invoice per student per
  period", the invariant that makes a re-run of monthly generation idempotent.
- `.summarise_by_vehicle` — backs the Vehicle Financial Overview ("students per bus, revenue per
  bus, outstanding per bus, paid/unpaid counts") as a single grouped query rather than N per-bus
  round trips.
- `.list_for_vehicle_period` — backs the printable per-bus report.
- `.list_overdue_candidates` — backs the scheduled overdue sweep.
- `.summarise_totals` — backs the organization finance KPI row.
- `IncomeRepository`/`ExpenseRepository.sum_between` — back Profit & Loss over a date range.

Tenant scoping is **not** a parameter on any of these: ADR-0021 binds the caller's
`TenantRegionScope` at repository construction, and `SqlAlchemyRepositoryBase._apply_scope`
applies it inside every read. A call site cannot forget it, and none of these signatures invites
it to try.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.modules.school_erp.domain.entities import (
    Expense,
    FeePlan,
    FinancialCategory,
    Income,
    ParentBillingProfile,
    ParentInvoice,
    ParentPayment,
    StudentBillingProfile,
    StudentInvoice,
    StudentPayment,
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
    ParentPaymentId,
    StudentId,
    StudentInvoiceId,
    StudentPaymentId,
    VehicleId,
)


@dataclass(frozen=True)
class VehicleFinancialSummary:
    """One row of the Vehicle Financial Overview. Produced by a single grouped query over
    `erp_student_invoices`, never by iterating vehicles.

    `vehicle_id` is `None` for invoices issued with no vehicle attributed — a real case (a
    student billed before assignment), surfaced as its own "Unassigned" row rather than silently
    dropped from the totals.
    """

    vehicle_id: str | None
    student_count: int
    invoice_count: int
    billed_amount: Decimal
    collected_amount: Decimal
    outstanding_amount: Decimal
    paid_student_count: int
    unpaid_student_count: int
    currency: str


@dataclass(frozen=True)
class VehicleBillingSummary:
    """What was billed to one bus's students in a window, and what is still owed on it —
    grouped over `erp_parent_invoice_lines.vehicle_id`, the vehicle captured on each line at
    generation time (ADR-0047 §5). `vehicle_id` is `None` for lines generated before the student
    had a bus: an "Unassigned" row, never re-attributed from today's assignment.

    Collected money is deliberately **not** here: it comes from payment allocations by receipt
    date (`ParentPaymentRepository.student_income_by_vehicle_between`), not from the invoice.
    """

    vehicle_id: str | None
    student_count: int
    billed_amount: Decimal
    outstanding_amount: Decimal


@dataclass(frozen=True)
class StudentIncomeRow:
    """Student income one student/parent pair brought in during a window — the per-student and
    per-parent breakdown of a vehicle's student income."""

    student_id: str
    parent_id: str
    amount: Decimal


@dataclass(frozen=True)
class FinanceTotals:
    """Organization-level finance KPIs for a period window."""

    billed_amount: Decimal
    collected_amount: Decimal
    outstanding_amount: Decimal
    invoice_count: int
    paid_invoice_count: int
    overdue_invoice_count: int
    currency: str


class FinancialCategoryRepository(ABC):
    @abstractmethod
    async def get(self, category_id: FinancialCategoryId) -> FinancialCategory | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, category: FinancialCategory) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[FinancialCategory]:
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[FinancialCategory]:
        raise NotImplementedError


class FeePlanRepository(ABC):
    @abstractmethod
    async def get(self, fee_plan_id: FeePlanId) -> FeePlan | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, fee_plan: FeePlan) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[FeePlan]:
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[FeePlan]:
        raise NotImplementedError


class StudentInvoiceRepository(ABC):
    @abstractmethod
    async def get(self, invoice_id: StudentInvoiceId) -> StudentInvoice | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, invoice: StudentInvoice) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[StudentInvoice]:
        raise NotImplementedError

    @abstractmethod
    async def exists_for_student_period(
        self, *, student_id: StudentId, period: BillingPeriod
    ) -> bool:
        """"One invoice per student per period" — the invariant that makes re-running monthly
        generation a no-op rather than a double charge. Backed by a real unique index too
        (`ux_erp_student_invoices__student_period`), so a race cannot slip past this check."""
        raise NotImplementedError

    @abstractmethod
    async def list_for_student(self, student_id: StudentId) -> list[StudentInvoice]:
        raise NotImplementedError

    @abstractmethod
    async def list_for_vehicle_period(
        self, *, vehicle_id: VehicleId, period: BillingPeriod | None = None
    ) -> list[StudentInvoice]:
        """Backs the printable per-bus report."""
        raise NotImplementedError

    @abstractmethod
    async def summarise_by_vehicle(
        self, *, period: BillingPeriod | None = None
    ) -> list[VehicleFinancialSummary]:
        """One grouped query for the whole Vehicle Financial Overview."""
        raise NotImplementedError

    @abstractmethod
    async def summarise_totals(
        self, *, period: BillingPeriod | None = None
    ) -> FinanceTotals:
        raise NotImplementedError

    @abstractmethod
    async def list_overdue_candidates(self, *, as_of: date) -> list[StudentInvoice]:
        """Issued or partially-paid invoices whose due date has passed."""
        raise NotImplementedError


class StudentPaymentRepository(ABC):
    @abstractmethod
    async def get(self, payment_id: StudentPaymentId) -> StudentPayment | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, payment: StudentPayment) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[StudentPayment]:
        raise NotImplementedError

    @abstractmethod
    async def list_for_invoice(self, invoice_id: StudentInvoiceId) -> list[StudentPayment]:
        raise NotImplementedError

    @abstractmethod
    async def sum_between(self, *, start: date, end: date) -> Decimal:
        """Collected student revenue in a window — the revenue side of Profit & Loss."""
        raise NotImplementedError


class IncomeRepository(ABC):
    @abstractmethod
    async def get(self, income_id: IncomeId) -> Income | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, income: Income) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[Income]:
        raise NotImplementedError

    @abstractmethod
    async def sum_between(self, *, start: date, end: date) -> Decimal:
        raise NotImplementedError

    @abstractmethod
    async def sum_by_category_between(self, *, start: date, end: date) -> dict[str, Decimal]:
        raise NotImplementedError

    @abstractmethod
    async def currencies_between(self, *, start: date, end: date) -> set[str]:
        """The distinct currencies among exactly the rows `sum_between` adds up. Every total in
        this module is a plain `SUM(amount)`, which is only meaningful in one currency — the
        application layer checks this before presenting any total (finance P0.5)."""
        raise NotImplementedError

    @abstractmethod
    async def sum_by_type_between(self, *, start: date, end: date) -> dict[str, Decimal]:
        """Live income in the window keyed by `IncomeType` value (`daily_vehicle`/`other`) —
        the two manual-income lines of Profit & Loss (ADR-0047 §6). Same filters as
        `sum_between`, so the lines always add up to it."""
        raise NotImplementedError

    @abstractmethod
    async def sum_by_vehicle_and_type_between(
        self, *, start: date, end: date
    ) -> dict[tuple[str, str], Decimal]:
        """`(vehicle_id, income_type) -> total` for income that names a bus. Income with no
        `vehicle_id` is organization-wide and is excluded rather than pooled into a pseudo-bus —
        the NULL-bucket lesson `ExpenseRepository.sum_by_vehicle_between` already paid for."""
        raise NotImplementedError

    @abstractmethod
    async def list_for_vehicle_between(
        self, *, vehicle_id: VehicleId, start: date, end: date
    ) -> list[Income]:
        """Live (non-voided) income entries for one bus in the window, oldest first — the
        daily/other income lines of the per-vehicle report."""
        raise NotImplementedError


class ExpenseRepository(ABC):
    @abstractmethod
    async def get(self, expense_id: ExpenseId) -> Expense | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, expense: Expense) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[Expense]:
        raise NotImplementedError

    @abstractmethod
    async def sum_between(self, *, start: date, end: date) -> Decimal:
        raise NotImplementedError

    @abstractmethod
    async def sum_by_category_between(self, *, start: date, end: date) -> dict[str, Decimal]:
        raise NotImplementedError

    @abstractmethod
    async def sum_by_vehicle_between(self, *, start: date, end: date) -> dict[str, Decimal]:
        """Per-bus operating cost for the Vehicle Financial Overview. Expenses with no
        `vehicle_id` are organization overhead and are excluded."""
        raise NotImplementedError

    @abstractmethod
    async def list_for_vehicle_between(
        self, *, vehicle_id: VehicleId, start: date, end: date
    ) -> list[Expense]:
        """Live (non-voided) expenses attributed to one bus in the window, oldest first — the
        expense lines and per-category breakdown of the per-vehicle report."""
        raise NotImplementedError

    @abstractmethod
    async def currencies_between(self, *, start: date, end: date) -> set[str]:
        """The distinct currencies among exactly the rows `sum_between` adds up. Every total in
        this module is a plain `SUM(amount)`, which is only meaningful in one currency — the
        application layer checks this before presenting any total (finance P0.5)."""
        raise NotImplementedError


# ==================================================================================================
# ParentBillingProfile / ParentInvoice (ADR-0042, 2026-09-11 — supersedes ADR-0041 §1)
# ==================================================================================================


class ParentBillingProfileRepository(ABC):
    @abstractmethod
    async def get(self, profile_id: ParentBillingProfileId) -> ParentBillingProfile | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_parent(self, parent_id: ParentId) -> ParentBillingProfile | None:
        """One profile per parent (`ux_erp_parent_billing_profiles__org_parent`) — the source of
        truth `create`/`update` both read before deciding whether to insert or edit in place."""
        raise NotImplementedError

    @abstractmethod
    def add(self, profile: ParentBillingProfile) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[ParentBillingProfile]:
        raise NotImplementedError

    @abstractmethod
    async def list_active_for_billing(
        self, *, as_of_period: BillingPeriod
    ) -> list[ParentBillingProfile]:
        """`active` profiles whose `billing_start_period <= as_of_period` — exactly the cohort
        one monthly `generate_parent_invoices` run picks up."""
        raise NotImplementedError


class StudentBillingProfileRepository(ABC):
    """ADR-0048: each student's own monthly fee, one per `(organization_id, student_id)`."""

    @abstractmethod
    async def get_by_student(self, student_id: StudentId) -> StudentBillingProfile | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_students(
        self, student_ids: list[str]
    ) -> dict[str, StudentBillingProfile]:
        """The fees of these students, keyed by student id; a student with no fee configured is
        simply absent. One query — the monthly run prices a whole organization at once."""
        raise NotImplementedError

    @abstractmethod
    def add(self, profile: StudentBillingProfile) -> None:
        raise NotImplementedError


class ParentInvoiceRepository(ABC):
    @abstractmethod
    async def get(self, invoice_id: ParentInvoiceId) -> ParentInvoice | None:
        raise NotImplementedError

    @abstractmethod
    async def billed_student_ids_for_period(self, *, period: BillingPeriod) -> set[str]:
        """Students already on a live (non-cancelled) invoice for `period`, under any parent.
        The monthly run skips them, so a child linked to two paying guardians is billed once."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_parent_period(
        self, *, parent_id: ParentId, period: BillingPeriod
    ) -> ParentInvoice | None:
        raise NotImplementedError

    @abstractmethod
    async def exists_for_parent_period(
        self, *, parent_id: ParentId, period: BillingPeriod
    ) -> bool:
        """"One invoice per parent per period" — the invariant that makes re-running monthly
        generation a no-op rather than a double charge, backed by a real unique index too
        (`ux_erp_parent_invoices__org_parent_period`), the identical two-layer pattern
        `StudentInvoiceRepository.exists_for_student_period` already establishes."""
        raise NotImplementedError

    @abstractmethod
    def add(self, invoice: ParentInvoice) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        request: OffsetPageRequest,
        *,
        filters: list[FilterCondition] | None = None,
        sort: list[SortSpec] | None = None,
        search: str | None = None,
    ) -> OffsetPage[ParentInvoice]:
        raise NotImplementedError

    @abstractmethod
    async def list_for_parent(self, parent_id: ParentId) -> list[ParentInvoice]:
        raise NotImplementedError

    @abstractmethod
    async def summarise_totals(self, *, period: BillingPeriod | None = None) -> FinanceTotals:
        """Reuses `FinanceTotals` (above) unchanged — same shape `StudentInvoiceRepository`
        already returns, so `application/queries.finance_totals_to_dto` needs no change to read
        a `ParentInvoice`-sourced total instead of a `StudentInvoice`-sourced one. `overdue_
        invoice_count` is always `0`: `ParentInvoiceStatus` has no `overdue` state (the
        directive's own three-status list), so nothing here can ever populate it."""
        raise NotImplementedError

    @abstractmethod
    async def list_for_student(self, student_id: StudentId) -> list[ParentInvoice]:
        """Every invoice carrying a line for this student, newest period first — the student's
        own charge history (ADR-0047 §2)."""
        raise NotImplementedError

    @abstractmethod
    async def summarise_lines_by_vehicle_between(
        self, *, start: date, end: date
    ) -> list[VehicleBillingSummary]:
        """Billed and outstanding per line vehicle, over non-cancelled invoices whose
        `invoice_date` falls in the window."""
        raise NotImplementedError

    @abstractmethod
    async def currencies_for_period(self, *, period: BillingPeriod | None = None) -> set[str]:
        """The distinct currencies among exactly the invoices `summarise_totals`/
        `summarise_by_vehicle` aggregate for `period` (all periods when `None`) — see
        `IncomeRepository.currencies_between` for why (finance P0.5)."""
        raise NotImplementedError

    @abstractmethod
    async def currencies_invoiced_between(self, *, start: date, end: date) -> set[str]:
        """The distinct currencies among exactly the invoices
        `summarise_lines_by_vehicle_between` adds up (non-cancelled, `invoice_date` in the
        window)."""
        raise NotImplementedError


# ==================================================================================================
# ParentPayment (ADR-0047 — amends ADR-0042 §4)
# ==================================================================================================


class ParentPaymentRepository(ABC):
    """Every student-income figure in this module is read here, from allocations of non-voided
    payments filtered by `received_on` — cash basis, so a payment counts in the window it was
    actually received (ADR-0047 §7)."""

    @abstractmethod
    async def get(self, payment_id: ParentPaymentId) -> ParentPayment | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, payment: ParentPayment) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_idempotency_key(self, key: str) -> ParentPayment | None:
        """The payment an earlier submission with the same key already recorded, if any — what
        turns a double-clicked "Record payment" into one payment rather than two."""
        raise NotImplementedError

    @abstractmethod
    async def list_for_invoice(self, invoice_id: ParentInvoiceId) -> list[ParentPayment]:
        raise NotImplementedError

    @abstractmethod
    async def list_for_parent(self, parent_id: ParentId) -> list[ParentPayment]:
        raise NotImplementedError

    @abstractmethod
    async def list_for_student(self, student_id: StudentId) -> list[ParentPayment]:
        """Payments with at least one allocation to this student, voided ones included (the
        student's history shows them, marked)."""
        raise NotImplementedError

    @abstractmethod
    async def sum_student_income_between(self, *, start: date, end: date) -> Decimal:
        raise NotImplementedError

    @abstractmethod
    async def student_income_by_vehicle_between(
        self, *, start: date, end: date
    ) -> dict[str | None, Decimal]:
        """Keyed by each allocation's own `vehicle_id` (copied from its invoice line); `None`
        holds money for lines generated before the student had a bus."""
        raise NotImplementedError

    @abstractmethod
    async def student_income_rows_between(
        self, *, vehicle_id: VehicleId | None, start: date, end: date
    ) -> list[StudentIncomeRow]:
        """Per `(student, parent)` student income in the window for one bus — or, with
        `vehicle_id=None`, for allocations with no bus."""
        raise NotImplementedError

    @abstractmethod
    async def currencies_between(self, *, start: date, end: date) -> set[str]:
        """The distinct currencies among exactly the payments the three sums above add up."""
        raise NotImplementedError
