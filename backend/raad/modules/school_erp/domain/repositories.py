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
        """Per-bus operating cost, so the Vehicle Financial Overview can show cost against the
        revenue `StudentInvoiceRepository.summarise_by_vehicle` returns."""
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


class ParentInvoiceRepository(ABC):
    @abstractmethod
    async def get(self, invoice_id: ParentInvoiceId) -> ParentInvoice | None:
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
    async def summarise_by_vehicle(
        self, *, period: BillingPeriod | None = None
    ) -> list[VehicleFinancialSummary]:
        """The Vehicle Financial Overview, grouped over `erp_parent_invoice_lines.vehicle_id` —
        the disclosed pro-rata allocation ADR-0042 decision 1 documents: a line's own collected
        share is `line.amount * invoice.amount_paid / invoice.amount`, since payment is recorded
        against the whole family invoice, never per child."""
        raise NotImplementedError

    @abstractmethod
    async def sum_collected_between(self, *, start: date, end: date) -> Decimal:
        """Parent transportation revenue for Profit & Loss, filtered by each invoice's own
        `invoice_date` (when it was generated) — a disclosed, deliberate choice, not an
        approximation of something more precise. This module keeps no per-transaction payment
        history (ADR-0042 decision 4: the directive explicitly forbids building one), so there is
        no payment-*date* to filter by; `invoice_date` is the one real, stored date this
        aggregate has. `amount_paid` is each invoice's *current* collected total, so a payment
        recorded weeks after the invoice was issued still counts, attributed to the invoice's own
        billing period rather than to whatever day the payment happened to be recorded — the same
        "attribute to the bill, not the receipt" basis `Income`/`Expense` already use via their
        own `occurred_on` filtering, for consistency across every P&L line."""
        raise NotImplementedError
