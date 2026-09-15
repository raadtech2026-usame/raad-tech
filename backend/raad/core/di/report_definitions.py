"""Report catalogue registration (ADR-0040 §6).

Lives in `core/di/` — the composition root — for the same reason `erp_adapters.py` does: it is
the one place allowed to know about several modules at once. Each builder below reaches its data
through the owning module's **application service**, never its repositories or domain types
(`.claude/rules/backend.md` #3), so `reporting` itself stays free of every other module's domain
while still rendering their reports.

**Every figure in every report comes from a real read.** No builder computes a projection, an
estimate or a trend; they format rows that already exist. Where a report would need data no
endpoint provides, the report is not registered rather than filled with a plausible number.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from dataclasses import dataclass
from typing import Any

from raad.core.di.container import Container
from raad.core.pagination import MAX_PAGE_SIZE, FilterCondition, OffsetPageRequest
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.domain.value_objects import VehicleId
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.platform_audit.application.ports import PlatformAuditUnitOfWork
from raad.modules.platform_finance.application.ports import PlatformFinanceUnitOfWork
from raad.modules.platform_finance.application.services import (
    PlatformFinanceApplicationService,
)
from raad.modules.reporting.application.catalog import (
    ReportCatalog,
    ReportDefinition,
    ReportRequest,
)
from raad.modules.reporting.application.report_table import ReportTable
from raad.modules.school_erp.application.ports import SchoolErpUnitOfWork
from raad.modules.school_erp.application.services import (
    ParentFinanceApplicationService,
    SchoolErpApplicationService,
)
from raad.modules.school_erp.domain.value_objects import BillingPeriod
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import ListStudentAssignmentsQuery
from raad.modules.transport_ops.application.services import (
    ParentApplicationService,
    StudentApplicationService,
    StudentAssignmentApplicationService,
    StudentParentApplicationService,
)

_PLATFORM_ROLES = (
    Role.FOUNDER,
    Role.REGIONAL_MANAGER,
    Role.SUPPORT_STAFF,
    Role.FINANCE_STAFF,
)
_FINANCE_ROLES = (Role.FOUNDER, Role.FINANCE_STAFF)
_ORG_ROLES = (Role.ORG_ADMIN, *_PLATFORM_ROLES)
#: `admin.audit.read` is not held by `finance_staff` (CLAUDE.md's own Notifications-era note,
#: reused verbatim here) — the Audit Logs report mirrors that grant set exactly rather than the
#: broader `_PLATFORM_ROLES`, so a role that would 403 reading `/admin/audit` directly cannot
#: reach the identical data through the report catalogue instead.
_AUDIT_ROLES = (Role.FOUNDER, Role.REGIONAL_MANAGER, Role.SUPPORT_STAFF)

#: Report pages are capped rather than unbounded. A synchronous export streams its bytes in the
#: request (ADR-0040 §6 — there is no object store to stage a large artifact in), so an
#: unbounded query is how a report becomes a timeout. 1000 rows covers a full school's monthly
#: roster with room to spare; beyond that the async `ReportRun` path is the right answer.
_MAX_ROWS = 1000


@dataclass(frozen=True)
class _Rows:
    """What a builder gets back from `_collect`: the rows it may render, and the true total.

    `total` is the repository's own pre-cap count, so a report that hit the cap can say how much
    it left out instead of presenting a truncated list as if it were complete.
    """

    data: list[Any]
    total: int

    @property
    def is_truncated(self) -> bool:
        return self.total > len(self.data)


async def _collect(
    repository, *, filters: list[FilterCondition] | None = None, limit: int = _MAX_ROWS
) -> _Rows:
    """Reads up to `limit` rows through a repository's `list_page`, one allowed page at a time.

    **Why not simply ask for `page_size=limit`.** `OffsetPageRequest` rejects any page size above
    `MAX_PAGE_SIZE` (100) — it is a `ValidationError`, raised in the constructor, so a builder
    that asked for 1000 rows did not return a short report: it returned `422` and rendered
    nothing at all. That is what every list-backed report did before this helper existed, live
    against the running API, while every test still passed because no test exercised a builder.

    Paging keeps the documented 1000-row cap real rather than quietly reducing it to 100.

    `filters` (ADR-0041 §3, defaults to none — every pre-existing call site is unaffected) lets a
    builder narrow the collected rows at the query layer, the same `FilterCondition` mechanism
    `school_erp.application.services._collect` already uses — e.g. the Payment Collection report
    filtering by `method`.
    """
    collected: list[Any] = []
    page_number = 1
    total = 0
    while len(collected) < limit:
        page_size = min(MAX_PAGE_SIZE, limit - len(collected))
        page = await repository.list_page(
            OffsetPageRequest(page=page_number, page_size=page_size),
            filters=filters or [],
            sort=[],
            search=None,
        )
        total = page.total
        collected.extend(page.data)
        if len(page.data) < page_size:
            break
        page_number += 1
    return _Rows(data=collected[:limit], total=total)


def _scoped(container: Container, uow_type, request: ReportRequest):
    """Resolves a Unit of Work already carrying the caller's tenant scope.

    A report builder must never see an unscoped UoW: ADR-0021's `_apply_scope` is what keeps one
    school's invoices out of another school's report, and it reads the scope off the UoW.

    The scope comes from `ReportRequest.scope` — the value the real `ScopeResolver` (ADR-0005)
    produced for this request — never re-derived here from `principal.org_id`. A Regional Manager
    and a Support Staff both have `org_id is None` while being restricted to a *subset* of
    organizations, so re-deriving would widen them to unrestricted. Falling back to the
    single-organization scope when no resolved scope was supplied keeps a directly-constructed
    request (a test, a future worker) fail-closed rather than accidentally global.
    """
    uow = container.resolve(uow_type)
    if request.scope is not None:
        uow.scope = request.scope
    elif request.principal.org_id:
        uow.scope = TenantRegionScope(organization_ids=frozenset({request.principal.org_id}))
    else:
        uow.scope = TenantRegionScope(organization_ids=frozenset())
    return uow


def _metadata(page: _Rows, label: str, **extra: str) -> dict[str, str]:
    """Report metadata carrying the true total, plus an explicit note when the cap bit.

    A report that silently rendered its first 1000 rows and said "Invoices: 4200" would read as
    a complete document. Naming the cut is the same honesty this codebase already applies to the
    Fleet Overview's own `total_online` cap.
    """
    metadata = {label: str(page.total), **extra}
    if page.is_truncated:
        metadata["Note"] = (
            f"Showing the first {len(page.data)} of {page.total}. "
            "Narrow the period, or use the per-bus report, for a complete list."
        )
    return metadata


def _period_label(request: ReportRequest) -> str:
    return request.period or "All time"


def _group_status_for_report(due: Decimal, paid: Decimal) -> str:
    """Derives one family-level status from a summed due/paid across every period in scope —
    used by `parent_payment_status_report`. Returns `unpaid`/`partial`/`paid`, the exact
    `ParentInvoiceStatus` vocabulary (ADR-0042/Report Center re-design, 2026-09-11) — not the
    pre-ADR-0042 `partially_paid` this helper originally returned, which would have rendered
    "Partially Paid" beside every other report's own "Partial" and read as a second, competing
    status vocabulary for the identical concept."""
    if due <= 0 or paid >= due:
        return "paid"
    if paid <= 0:
        return "unpaid"
    return "partial"


async def _vehicle_names(
    container: Container, request: ReportRequest, vehicle_ids: set[str]
) -> dict[str, str]:
    """Resolves a set of `vehicle_id`s to their human-readable `label or plate_no` (Report
    Center re-design — Section 29 of the directive: no raw id may reach the rendered table, and
    a `ReportTable` cell is plain text, not a structured value the frontend could re-resolve
    against an id->name map after the fact, so the resolution has to happen here).

    Tenant-scoped via the caller's own resolved scope, mirroring every other cross-module read
    in this file (`_scoped`) — a vehicle id outside the caller's own organization resolves to
    nothing and falls back to the raw id, never another tenant's vehicle name.
    """
    if not vehicle_ids:
        return {}
    uow = _scoped(container, FleetDeviceUnitOfWork, request)
    async with uow:
        vehicles = await uow.vehicles.list_by_ids([VehicleId(v) for v in vehicle_ids])
    return {str(v.id): (v.label or v.plate_no) for v in vehicles}


def _vehicle_label(names: dict[str, str], vehicle_id: str | None) -> str:
    if not vehicle_id:
        return "Unassigned"
    return names.get(vehicle_id, vehicle_id)


def _window(request: ReportRequest) -> tuple[date, date]:
    """Defaults to the trailing 12 months when the caller supplies no range — a report with no
    dates should still render something meaningful rather than erroring."""
    end = request.end or date.today()
    start = request.start or (end - timedelta(days=365))
    return start, end


def register_report_definitions(catalog: ReportCatalog, container: Container) -> None:
    """Registers every report both catalogues offer. Called once from `build_container`."""

    # ==========================================================================================
    # Organization reports (school_erp)
    # ==========================================================================================

    async def legacy_student_billing(request: ReportRequest) -> ReportTable:
        """The pre-Report-Center-redesign per-student invoice scan — kept, unregistered from the
        catalogue (ADR-0042 decision 2: "do not delete existing functionality"), not deleted.
        Unregistered because its own title/columns are exactly the forbidden legacy vocabulary
        the Report Center directive names outright ("Student Billing", raw `student_id`/
        `vehicle_id` cells) — `org.parent_invoices` (`parent_invoices_report`) is the real
        replacement: the same underlying money, rendered at the Parent grain the new business
        model actually bills at."""
        service: SchoolErpApplicationService = container.resolve(SchoolErpApplicationService)
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        async with uow:
            page = await _collect(uow.student_invoices)
        rows = [
            [
                str(inv.period),
                str(inv.student_id),
                str(inv.vehicle_id or "—"),
                str(inv.route_id or "—"),
                f"{inv.net_amount:.2f}",
                f"{inv.amount_paid:.2f}",
                f"{inv.balance_due:.2f}",
                inv.status.value.replace("_", " ").title(),
                inv.due_date.isoformat(),
            ]
            for inv in page.data
        ]
        billed = sum(i.net_amount for i in page.data)
        paid = sum(i.amount_paid for i in page.data)
        outstanding = sum(i.balance_due for i in page.data)
        return ReportTable(
            title="Student Billing",
            subtitle="Every student invoice, with what has been paid against it",
            headers=[
                "Period", "Student", "Vehicle", "Route", "Net", "Paid", "Balance",
                "Status", "Due",
            ],
            rows=rows,
            metadata=_metadata(page, "Invoices", Period=_period_label(request)),
            numeric_columns=[4, 5, 6],
            total_row=[
                "TOTAL", "", "", "", f"{billed:.2f}", f"{paid:.2f}",
                f"{outstanding:.2f}", "", "",
            ],
        )

    async def vehicle_revenue(request: ReportRequest) -> ReportTable:
        """"How much business/revenue is associated with each vehicle?" (Section 16). Reuses
        `get_vehicle_financial_overview` unchanged — the identical grouped query the Finance
        page's own Vehicle Financial Overview already renders, never a second calculation of the
        same per-bus figures."""
        service: SchoolErpApplicationService = container.resolve(SchoolErpApplicationService)
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        summaries = await service.get_vehicle_financial_overview(
            period=request.period, uow=uow
        )
        names = await _vehicle_names(
            container, request, {s.vehicle_id for s in summaries if s.vehicle_id}
        )
        rows = [
            [
                _vehicle_label(names, s.vehicle_id),
                str(s.student_count),
                str(s.paid_student_count),
                str(s.unpaid_student_count),
                s.billed_amount,
                s.collected_amount,
                s.outstanding_amount,
                s.expense_amount,
                s.net_amount,
            ]
            for s in summaries
        ]
        return ReportTable(
            title="Vehicle Revenue",
            subtitle="Expected billing, collections, receivables and attributed cost per bus",
            headers=[
                "Vehicle", "Students", "Paid", "Unpaid", "Expected", "Collected",
                "Receivables", "Cost", "Net",
            ],
            rows=rows,
            metadata={"Period": _period_label(request), "Vehicles": str(len(rows))},
            numeric_columns=[1, 2, 3, 4, 5, 6, 7, 8],
        )

    async def legacy_student_bus_roster(request: ReportRequest) -> ReportTable:
        """The pre-ADR-0042 printable per-bus report, reading the frozen historical
        `StudentInvoice` table — kept, unregistered from the primary catalogue (ADR-0042
        decision 2: "do not delete existing functionality"), not deleted. Not a duplicate
        calculation of `bus_report` below: this one is deliberately a different, historical data
        source, the source `org.student_billing` itself keeps reading."""
        service: SchoolErpApplicationService = container.resolve(SchoolErpApplicationService)
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        if not request.vehicle_id:
            return ReportTable(
                title="Bus Report (legacy)",
                subtitle="Select a vehicle to generate this report",
                headers=["Vehicle"],
                rows=[],
                metadata={},
            )
        invoices = await service.list_invoices_for_vehicle(
            vehicle_id=request.vehicle_id, period=request.period, uow=uow
        )
        rows = [
            [
                inv.student_id,
                inv.period,
                inv.route_id or "—",
                inv.amount,
                inv.discount_amount,
                inv.net_amount,
                inv.amount_paid,
                inv.balance_due,
                inv.status.replace("_", " ").title(),
            ]
            for inv in invoices
        ]
        total_net = sum(float(i.net_amount) for i in invoices)
        total_paid = sum(float(i.amount_paid) for i in invoices)
        total_due = sum(float(i.balance_due) for i in invoices)
        return ReportTable(
            title="Bus Report (legacy)",
            subtitle="Historical per-student fees and balances for one vehicle",
            headers=[
                "Student", "Period", "Route", "Fee", "Discount", "Net", "Paid",
                "Balance", "Status",
            ],
            rows=rows,
            metadata={
                "Vehicle": request.vehicle_id,
                "Period": _period_label(request),
                "Students": str(len({i.student_id for i in invoices})),
            },
            numeric_columns=[3, 4, 5, 6, 7],
            total_row=[
                "TOTAL", "", "", "", "", f"{total_net:.2f}", f"{total_paid:.2f}",
                f"{total_due:.2f}", "",
            ],
        )

    async def bus_report(request: ReportRequest) -> ReportTable:
        """The directive's business-oriented "Bus Report" (Section 18) — vehicle info, assigned
        families, expected revenue, collected, receivables and attributed cost for one vehicle.
        Reuses `get_vehicle_financial_overview` (the same figures `vehicle_revenue` above
        renders) for the financial summary, and `ParentFinanceApplicationService.
        list_parent_invoices`'s own `vehicle_id` filter for the family roster — no new
        calculation, no new repository method, both already exist for exactly this purpose.

        **Disclosed limitation**: each roster row's own "Children" count is the *family's* total
        child count (`ParentInvoiceSummaryDTO.children_count`), not only the children on this
        bus — `ParentInvoice` has no per-line roster read exposed at this grain. A family with
        children split across two buses will show its full child count on each bus's report.
        """
        if not request.vehicle_id:
            return ReportTable(
                title="Bus Report",
                subtitle="Select a vehicle to generate this report",
                headers=["Vehicle"],
                rows=[],
                metadata={},
            )
        finance_service: SchoolErpApplicationService = container.resolve(
            SchoolErpApplicationService
        )
        finance_uow = _scoped(container, SchoolErpUnitOfWork, request)
        summaries = await finance_service.get_vehicle_financial_overview(
            period=request.period, uow=finance_uow
        )
        summary = next(
            (s for s in summaries if s.vehicle_id == request.vehicle_id), None
        )
        names = await _vehicle_names(container, request, {request.vehicle_id})
        vehicle_label = _vehicle_label(names, request.vehicle_id)

        parent_service: ParentFinanceApplicationService = container.resolve(
            ParentFinanceApplicationService
        )
        school_erp_uow = _scoped(container, SchoolErpUnitOfWork, request)
        transport_ops_uow = _scoped(container, TransportOpsUnitOfWork, request)
        roster_page = await parent_service.list_parent_invoices(
            page=1,
            page_size=_MAX_ROWS,
            period=request.period,
            status=request.status,
            parent_id=None,
            vehicle_id=request.vehicle_id,
            school_erp_uow=school_erp_uow,
            transport_ops_uow=transport_ops_uow,
        )
        rows = [
            [
                row.parent_name,
                str(row.children_count),
                row.period,
                row.amount,
                row.amount_paid,
                row.balance_due,
                row.status.replace("_", " ").title(),
            ]
            for row in roster_page.data
        ]
        metadata = {
            "Vehicle": vehicle_label,
            "Period": _period_label(request),
            "Families billed": str(len(roster_page.data)),
        }
        if summary is not None:
            metadata.update(
                {
                    "Expected revenue": f"{summary.billed_amount:.2f}",
                    "Collected": f"{summary.collected_amount:.2f}",
                    "Receivables": f"{summary.outstanding_amount:.2f}",
                    "Attributed cost": f"{summary.expense_amount:.2f}",
                    "Net": f"{summary.net_amount:.2f}",
                }
            )
        return ReportTable(
            title="Bus Report",
            subtitle=f"{vehicle_label} — families, billing and receivables",
            headers=["Parent", "Children", "Period", "Amount", "Paid", "Receivable", "Status"],
            rows=rows,
            metadata=metadata,
            numeric_columns=[3, 4, 5],
        )

    def _month_bounds(period: str) -> tuple[date, date]:
        """Mirrors `SchoolErpApplicationService._period_bounds` exactly (a private method this
        file cannot import) — "first of next month minus one day" rather than a hardcoded
        month-length table, so February and leap years need no special case."""
        year, month = (int(part) for part in period.split("-"))
        start = date(year, month, 1)
        next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        return start, date.fromordinal(next_month.toordinal() - 1)

    async def _monthly_snapshot(
        request: ReportRequest, period: str
    ) -> dict[str, Decimal]:
        """The shared calculation behind both Monthly and Yearly Financial Summary — one period,
        every figure both reports render, computed once here rather than twice across two
        builders (Section 27's own "no duplicate report calculation logic")."""
        finance_service: SchoolErpApplicationService = container.resolve(
            SchoolErpApplicationService
        )
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        start, end = _month_bounds(period)
        pnl = await finance_service.get_profit_and_loss(start=start, end=end, uow=uow)
        async with uow:
            totals = await uow.parent_invoices.summarise_totals(period=BillingPeriod(period))
        return {
            "expected": totals.billed_amount,
            "collected": totals.collected_amount,
            "receivables": totals.outstanding_amount,
            "other_income": Decimal(pnl.other_income),
            "expenses": Decimal(pnl.total_expenses),
            "net_result": Decimal(pnl.net_profit),
        }

    async def monthly_financial_summary(request: ReportRequest) -> ReportTable:
        """The directive's "Monthly Financial Summary" (Section 21) — billing position (Expected/
        Collected/Receivables) and actual financial result (Income/Expenses/Net Result) in one
        snapshot, plus the Paid/Partial/Unpaid parent counts `parent_payment_status_report`
        already computes, scoped to this one period."""
        period = request.period or date.today().strftime("%Y-%m")
        snapshot = await _monthly_snapshot(request, period)

        status_page = await parent_payment_status_report(
            ReportRequest(
                principal=request.principal,
                organization_id=request.organization_id,
                period=period,
                scope=request.scope,
            )
        )
        counts = status_page.metadata

        rows = [
            ["Parent Transportation Collections", f"{snapshot['collected']:.2f}"],
            ["Other Income", f"{snapshot['other_income']:.2f}"],
            ["Total Income", f"{(snapshot['collected'] + snapshot['other_income']):.2f}"],
            ["Total Expenses", f"{snapshot['expenses']:.2f}"],
        ]
        return ReportTable(
            title=f"Monthly Financial Summary — {period}",
            subtitle="Billing position and actual financial result for the month",
            headers=["Line", "Amount"],
            rows=rows,
            metadata={
                "Period": period,
                "Expected Billing": f"{snapshot['expected']:.2f}",
                "Collected": f"{snapshot['collected']:.2f}",
                "Receivables": f"{snapshot['receivables']:.2f}",
                "Paid Parents": counts.get("Paid Parents", "0"),
                "Partial Parents": counts.get("Partial Parents", "0"),
                "Unpaid Parents": counts.get("Unpaid Parents", "0"),
            },
            numeric_columns=[1],
            total_row=["NET RESULT", f"{snapshot['net_result']:.2f}"],
        )

    async def yearly_financial_summary(request: ReportRequest) -> ReportTable:
        """The directive's "Yearly Financial Summary" (Section 22) — a real month-by-month
        breakdown, not a single annual total. `vehicle_id`, when given, swaps Expenses for that
        vehicle's own attributed cost (`sum_by_vehicle_between`) and Expected/Collected/
        Receivables for that vehicle's own row from `get_vehicle_financial_overview` — Other
        Income is organization-wide by nature and is disclosed as such rather than fabricated
        onto one bus."""
        year = (request.start or date.today()).year
        finance_service: SchoolErpApplicationService = container.resolve(
            SchoolErpApplicationService
        )
        uow = _scoped(container, SchoolErpUnitOfWork, request)

        rows = []
        totals = {"expected": Decimal("0.00"), "collected": Decimal("0.00"), "receivables": Decimal("0.00"), "other_income": Decimal("0.00"), "expenses": Decimal("0.00"), "net_result": Decimal("0.00")}
        for month in range(1, 13):
            period = f"{year:04d}-{month:02d}"
            snapshot = await _monthly_snapshot(request, period)
            expected, collected, receivables = (
                snapshot["expected"], snapshot["collected"], snapshot["receivables"]
            )
            other_income = snapshot["other_income"]
            expenses = snapshot["expenses"]
            if request.vehicle_id:
                start, end = _month_bounds(period)
                vehicle_summaries = await finance_service.get_vehicle_financial_overview(
                    period=period, uow=uow
                )
                v = next((s for s in vehicle_summaries if s.vehicle_id == request.vehicle_id), None)
                expected = v.billed_amount if v else Decimal("0.00")
                collected = v.collected_amount if v else Decimal("0.00")
                receivables = v.outstanding_amount if v else Decimal("0.00")
                other_income = Decimal("0.00")
                async with uow:
                    by_vehicle = await uow.expenses.sum_by_vehicle_between(start=start, end=end)
                expenses = by_vehicle.get(request.vehicle_id, Decimal("0.00"))
            net_result = collected + other_income - expenses
            for key, value in (
                ("expected", expected), ("collected", collected), ("receivables", receivables),
                ("other_income", other_income), ("expenses", expenses), ("net_result", net_result),
            ):
                totals[key] += value
            rows.append(
                [
                    date(year, month, 1).strftime("%b"),
                    f"{expected:.2f}", f"{collected:.2f}", f"{receivables:.2f}",
                    f"{other_income:.2f}", f"{expenses:.2f}", f"{net_result:.2f}",
                ]
            )

        names = await _vehicle_names(container, request, {request.vehicle_id} if request.vehicle_id else set())
        subtitle = (
            f"Month-by-month breakdown for {_vehicle_label(names, request.vehicle_id)}"
            if request.vehicle_id
            else "Month-by-month breakdown, all vehicles"
        )
        metadata = {"Year": str(year)}
        if request.vehicle_id:
            metadata["Note"] = "Other Income is organization-wide and is not attributed to one vehicle."
        return ReportTable(
            title=f"Yearly Financial Summary — {year}",
            subtitle=subtitle,
            headers=["Month", "Expected Billing", "Collected", "Receivables", "Other Income", "Expenses", "Net Result"],
            rows=rows,
            metadata=metadata,
            numeric_columns=[1, 2, 3, 4, 5, 6],
            total_row=[
                "ANNUAL TOTAL",
                f"{totals['expected']:.2f}", f"{totals['collected']:.2f}", f"{totals['receivables']:.2f}",
                f"{totals['other_income']:.2f}", f"{totals['expenses']:.2f}", f"{totals['net_result']:.2f}",
            ],
        )

    async def student_transportation_report(request: ReportRequest) -> ReportTable:
        """The directive's "Student Transportation Report" (Section 19) — a transportation
        roster, not an academic one: Student, Parent, Vehicle, transportation status. Sourced
        from `StudentAssignment` (`transport_ops`'s own CR-1 access gate), never from billing
        data — a family not yet billed can still have an active transportation assignment, and
        representing billing rows as "assignment" would misrepresent what the report is showing.
        Composes three already-existing bulk-lookup application-service calls, mirroring the
        exact "resolve ids to names in one call, never one per row" discipline
        `ParentFinanceApplicationService` already establishes — no new N+1.
        """
        assignment_service: StudentAssignmentApplicationService = container.resolve(
            StudentAssignmentApplicationService
        )
        student_service: StudentApplicationService = container.resolve(StudentApplicationService)
        student_parent_service: StudentParentApplicationService = container.resolve(
            StudentParentApplicationService
        )
        parent_service: ParentApplicationService = container.resolve(ParentApplicationService)
        uow = _scoped(container, TransportOpsUnitOfWork, request)

        assignments: list = []
        page_number = 1
        total = 0
        while len(assignments) < _MAX_ROWS:
            page_size = min(MAX_PAGE_SIZE, _MAX_ROWS - len(assignments))
            page = await assignment_service.list_student_assignments(
                ListStudentAssignmentsQuery(
                    page_request=OffsetPageRequest(page=page_number, page_size=page_size),
                    filters=[FilterCondition(field="status", op="eq", value="active")],
                ),
                uow=uow,
            )
            total = page.total
            assignments.extend(page.data)
            if len(page.data) < page_size:
                break
            page_number += 1
        if request.vehicle_id:
            assignments = [a for a in assignments if a.vehicle_id == request.vehicle_id]

        student_ids = [a.student_id for a in assignments]
        students = await student_service.list_students_by_ids(student_ids, uow=uow)
        student_names = {s.id: s.full_name for s in students}

        links = await student_parent_service.list_links_for_students(student_ids, uow=uow)
        primary_parent_by_student: dict[str, str] = {}
        for link in links:
            if link.student_id not in primary_parent_by_student or link.is_primary:
                primary_parent_by_student[link.student_id] = link.parent_id
        parent_ids = sorted(set(primary_parent_by_student.values()))
        parents = await parent_service.list_parents_by_ids(parent_ids, uow=uow)
        parent_names = {p.id: p.full_name for p in parents}
        vehicle_names = await _vehicle_names(
            container, request, {a.vehicle_id for a in assignments if a.vehicle_id}
        )

        rows = [
            [
                student_names.get(a.student_id, a.student_id),
                parent_names.get(
                    primary_parent_by_student.get(a.student_id, ""), "No linked parent"
                ),
                _vehicle_label(vehicle_names, a.vehicle_id),
                a.status.replace("_", " ").title(),
            ]
            for a in assignments
        ]
        rows.sort(key=lambda r: r[0])
        metadata = {"Students": str(len(rows))}
        if total > len(assignments):
            metadata["Note"] = (
                f"Showing the first {len(assignments)} of {total} active assignments. "
                "Narrow by vehicle for a complete list."
            )
        return ReportTable(
            title="Student Transportation Report",
            subtitle="Which student rides which bus, and with which parent",
            headers=["Student", "Parent", "Vehicle", "Status"],
            rows=rows,
            metadata=metadata,
        )

    async def vehicle_cost_report(request: ReportRequest) -> ReportTable:
        """"Show vehicle-specific costs where the expense is actually attributable to a
        vehicle" (Section 17). One vehicle selected: cost broken down by category, with a Total
        Vehicle Cost line. "All Vehicles": one total per vehicle, organization-wide expenses
        (`vehicle_id IS NULL`) deliberately excluded — never invented onto a bus, the identical
        NULL-exclusion Permanent Lesson `sum_by_vehicle_between` already established."""
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        start, end = _window(request)

        if request.vehicle_id:
            # `occurred_on` has no `value_type=date` on `ExpenseRepository.filterable_fields`
            # (only `eq`-style client filters have ever used it) — binding `gte`/`lte` through
            # the generic mechanism would compare a raw string against a `DATE` column and raise
            # `asyncpg.exceptions.DataError`. Filtering the date window in Python after a single
            # `vehicle_id`-filtered fetch avoids that, at the cost of one extra in-memory pass
            # over an already-bounded (`_collect`'s own 1000-row cap) result set.
            filters = [FilterCondition(field="vehicle_id", op="eq", value=request.vehicle_id)]
            async with uow:
                page = await _collect(uow.expenses, filters=filters)
                categories = await uow.financial_categories.list_all()
            category_names = {str(c.id): c.name for c in categories}
            by_category: dict[str, Decimal] = {}
            for expense in page.data:
                if expense.is_voided or not (start <= expense.occurred_on <= end):
                    continue
                key = (
                    category_names.get(str(expense.category_id), "Uncategorised")
                    if expense.category_id
                    else "Uncategorised"
                )
                by_category[key] = by_category.get(key, Decimal("0.00")) + expense.amount.amount
            names = await _vehicle_names(container, request, {request.vehicle_id})
            vehicle_label = _vehicle_label(names, request.vehicle_id)
            rows = sorted(
                [[category, f"{amount:.2f}"] for category, amount in by_category.items()]
            )
            total = sum(by_category.values(), Decimal("0.00"))
            return ReportTable(
                title="Vehicle Cost Report",
                subtitle=f"{vehicle_label} — costs by category",
                headers=["Category", "Amount"],
                rows=rows,
                metadata={"Vehicle": vehicle_label, "From": start.isoformat(), "To": end.isoformat()},
                numeric_columns=[1],
                total_row=["TOTAL VEHICLE COST", f"{total:.2f}"],
            )

        async with uow:
            by_vehicle = await uow.expenses.sum_by_vehicle_between(start=start, end=end)
        names = await _vehicle_names(container, request, set(by_vehicle.keys()))
        ordered = sorted(by_vehicle.items(), key=lambda item: item[1], reverse=True)
        rows = [[_vehicle_label(names, vehicle_id), f"{amount:.2f}"] for vehicle_id, amount in ordered]
        total = sum(by_vehicle.values(), Decimal("0.00"))
        return ReportTable(
            title="Vehicle Cost Report",
            subtitle="Attributable cost per bus — organization-wide overhead excluded",
            headers=["Vehicle", "Amount"],
            rows=rows,
            metadata={"From": start.isoformat(), "To": end.isoformat(), "Vehicles": str(len(rows))},
            numeric_columns=[1],
            total_row=["TOTAL", f"{total:.2f}"],
        )

    async def receivables_report(request: ReportRequest) -> ReportTable:
        """The directive's "Receivables Report" (Part 34, renamed from "Outstanding Balances") —
        every real `ParentInvoice` with money still owed (ADR-0042), never a `StudentInvoice`
        scan. "Who still owes the organization money?" answered at the family grain, the grain
        the family actually pays at."""
        service: ParentFinanceApplicationService = container.resolve(
            ParentFinanceApplicationService
        )
        school_erp_uow = _scoped(container, SchoolErpUnitOfWork, request)
        transport_ops_uow = _scoped(container, TransportOpsUnitOfWork, request)
        page = await service.list_parent_invoices(
            page=1,
            page_size=_MAX_ROWS,
            period=request.period,
            status=request.status,
            parent_id=request.parent_id,
            vehicle_id=request.vehicle_id,
            school_erp_uow=school_erp_uow,
            transport_ops_uow=transport_ops_uow,
        )
        # "Who still owes the organization money?" (Section 12) — receivable > 0 is the report's
        # own defining filter, applied on top of whatever `status` the caller narrowed to (a
        # `status=paid` selection here correctly yields nothing, honestly, rather than showing
        # settled invoices under a "money still owed" title).
        unpaid = [row for row in page.data if Decimal(row.balance_due) > 0]
        rows = [
            [
                row.parent_name,
                str(row.children_count),
                row.period,
                row.amount,
                row.amount_paid,
                row.balance_due,
                row.status.replace("_", " ").title(),
            ]
            for row in unpaid
        ]
        total = sum((Decimal(row.balance_due) for row in unpaid), Decimal("0.00"))
        return ReportTable(
            title="Receivables",
            subtitle="Money currently owed to the organization by Parents",
            headers=["Parent", "Children", "Period", "Amount", "Paid", "Receivable", "Status"],
            rows=rows,
            metadata={"Unpaid invoices": str(len(unpaid))},
            numeric_columns=[3, 4, 5],
            total_row=["TOTAL RECEIVABLES", "", "", "", "", f"{total:.2f}", ""],
        )

    async def income_report(request: ReportRequest) -> ReportTable:
        """The directive's "Income Report" (Section 13) — separates Parent Transportation
        Collections from Other Income, never double-counted (`sum_collected_between` and
        `uow.income` are two disjoint sources by construction — a student payment never becomes
        an `Income` row, ADR-0040's own automatic-accounting rule). The table itself lists only
        the `Income` ledger (donations, sponsorships, grants); the Parent collections figure is a
        summary line, not a fabricated ledger row standing in for real transactions."""
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        start, end = _window(request)
        async with uow:
            collections = await uow.parent_invoices.sum_collected_between(start=start, end=end)
            page = await _collect(uow.income)
            categories = await uow.financial_categories.list_all()
        category_names = {str(c.id): c.name for c in categories}
        live = [i for i in page.data if not i.is_voided and start <= i.occurred_on <= end]
        rows = [
            [
                i.occurred_on.isoformat(),
                category_names.get(str(i.category_id), "Uncategorised") if i.category_id else "Uncategorised",
                i.description or "—",
                f"{i.amount.amount:.2f}",
            ]
            for i in live
        ]
        other_income = sum((i.amount.amount for i in live), Decimal("0.00"))
        total_income = collections + other_income
        return ReportTable(
            title="Income Report",
            subtitle="Parent transportation collections shown separately from other income",
            headers=["Date", "Category", "Description", "Amount"],
            rows=rows,
            metadata={
                "Parent Transportation Collections": f"{collections:.2f}",
                "Other Income": f"{other_income:.2f}",
                "Total Income": f"{total_income:.2f}",
                "From": start.isoformat(),
                "To": end.isoformat(),
            },
            numeric_columns=[3],
            total_row=["TOTAL OTHER INCOME", "", "", f"{other_income:.2f}"],
        )

    async def expense_report(request: ReportRequest) -> ReportTable:
        """The directive's "Expense Report" (Section 14). Recurring-vs-variable classification
        (Section 14's own "where supported") is deliberately **not** attempted: no
        `FinancialCategory`/`Expense` field records that distinction, and inferring it from a
        category's own name would be exactly the kind of invented business rule this codebase's
        own "do not invent" posture (Vehicle Revenue's identical discipline) rules out."""
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        start, end = _window(request)
        filters = (
            [FilterCondition(field="vehicle_id", op="eq", value=request.vehicle_id)]
            if request.vehicle_id
            else []
        )
        async with uow:
            page = await _collect(uow.expenses, filters=filters)
            categories = await uow.financial_categories.list_all()
        category_names = {str(c.id): c.name for c in categories}
        names = await _vehicle_names(
            container, request, {str(e.vehicle_id) for e in page.data if e.vehicle_id}
        )
        live = [e for e in page.data if not e.is_voided and start <= e.occurred_on <= end]
        rows = [
            [
                e.occurred_on.isoformat(),
                category_names.get(str(e.category_id), "Uncategorised") if e.category_id else "Uncategorised",
                e.description or "—",
                _vehicle_label(names, str(e.vehicle_id) if e.vehicle_id else None) if e.vehicle_id else "—",
                f"{e.amount.amount:.2f}",
            ]
            for e in live
        ]
        total = sum((e.amount.amount for e in live), Decimal("0.00"))
        return ReportTable(
            title="Expense Report",
            subtitle="Every recorded organization expense",
            headers=["Date", "Category", "Description", "Vehicle", "Amount"],
            rows=rows,
            metadata={"From": start.isoformat(), "To": end.isoformat(), "Total Expenses": f"{total:.2f}"},
            numeric_columns=[4],
            total_row=["TOTAL EXPENSES", "", "", "", f"{total:.2f}"],
        )

    async def org_profit_and_loss(request: ReportRequest) -> ReportTable:
        """The directive's professional P&L (Section 15) — income lines, expense lines broken
        down by category (`ProfitAndLossDTO.expenses_by_category`, already computed by
        `get_profit_and_loss` and, until now, never rendered by this report), then Net Result.
        No vehicle filter: a per-vehicle P&L would recompute exactly what `vehicle_revenue`'s own
        Net column already shows (collected revenue minus attributed cost) — Section 27's own
        "do not create duplicate report calculation logic" rules out building it twice."""
        service: SchoolErpApplicationService = container.resolve(SchoolErpApplicationService)
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        start, end = _window(request)
        pnl = await service.get_profit_and_loss(start=start, end=end, uow=uow)
        async with uow:
            categories = await uow.financial_categories.list_all()
        category_names = {str(c.id): c.name for c in categories}

        rows = [
            ["INCOME", ""],
            ["Parent Transportation Collections", pnl.student_revenue],
            ["Other Income", pnl.other_income],
            ["Total Income", pnl.total_income],
            ["", ""],
            ["EXPENSES", ""],
        ]
        for category_id, amount in sorted(
            pnl.expenses_by_category.items(), key=lambda item: Decimal(item[1]), reverse=True
        ):
            label = category_names.get(category_id, "Uncategorised") if category_id else "Uncategorised"
            rows.append([label, amount])
        rows.append(["Total Expenses", pnl.total_expenses])
        return ReportTable(
            title="Profit & Loss",
            subtitle="Derived from actual recorded transactions only — no unpaid invoice counted as cash",
            headers=["Line", f"Amount ({pnl.currency})"],
            rows=rows,
            metadata={"From": start.isoformat(), "To": end.isoformat()},
            numeric_columns=[1],
            total_row=["NET RESULT", pnl.net_profit],
        )

    async def legacy_student_payment_ledger(request: ReportRequest) -> ReportTable:
        """The pre-Report-Center-redesign raw payment ledger — kept, unregistered from the
        catalogue (ADR-0042 decision 2), not deleted. Unregistered because it duplicates
        `org.parent_payment_report` (`parent_payment_report`, Section 11) with legacy semantics
        the directive explicitly rules out for that report: a raw `student_id` row and a payment
        method/reference column ("this is a business payment-status report, not a banking
        ledger"). Both read the same underlying `StudentPayment`/`ParentInvoice` money; this one
        is simply the wrong grain and the wrong columns for the new business model."""
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        filters = (
            [FilterCondition(field="method", op="eq", value=request.payment_method)]
            if request.payment_method
            else []
        )
        async with uow:
            page = await _collect(uow.student_payments, filters=filters)
        rows = [
            [
                p.received_on.isoformat(),
                str(p.student_id),
                f"{p.amount.amount:.2f}",
                p.amount.currency,
                p.method.value.replace("_", " ").title(),
                p.reference or "—",
                "Voided" if p.is_voided else "Recorded",
            ]
            for p in page.data
        ]
        collected = sum(p.amount.amount for p in page.data if not p.is_voided)
        return ReportTable(
            title="Parent Payments (legacy ledger)",
            subtitle="Payments received from families, voided entries included and marked",
            headers=["Received", "Student", "Amount", "Currency", "Method", "Reference", "State"],
            rows=rows,
            metadata=_metadata(page, "Payments"),
            numeric_columns=[2],
            total_row=["TOTAL COLLECTED", "", f"{collected:.2f}", "", "", "", ""],
        )

    async def parent_invoices_report(request: ReportRequest) -> ReportTable:
        """The directive's "Parent Invoice Report" (Section 10) — every real `ParentInvoice` in
        scope (ADR-0042), never a grouping of per-student rows. Reuses `ParentFinanceApplication
        Service.list_parent_invoices` — the exact same call `GET /school-finance/parent-invoices`
        makes — one source of truth for what a "Parent Invoice" is."""
        service: ParentFinanceApplicationService = container.resolve(
            ParentFinanceApplicationService
        )
        school_erp_uow = _scoped(container, SchoolErpUnitOfWork, request)
        transport_ops_uow = _scoped(container, TransportOpsUnitOfWork, request)
        page = await service.list_parent_invoices(
            page=1,
            page_size=_MAX_ROWS,
            period=request.period,
            vehicle_id=request.vehicle_id,
            status=request.status,
            parent_id=request.parent_id,
            school_erp_uow=school_erp_uow,
            transport_ops_uow=transport_ops_uow,
        )
        rows = [
            [
                row.parent_name,
                str(row.children_count),
                row.period,
                row.invoice_number,
                row.amount,
                row.amount_paid,
                row.balance_due,
                row.status.replace("_", " ").title(),
            ]
            for row in page.data
        ]
        billed = sum(Decimal(row.amount) for row in page.data)
        paid = sum(Decimal(row.amount_paid) for row in page.data)
        outstanding = sum(Decimal(row.balance_due) for row in page.data)
        metadata = {
            "Total Parents": str(len({row.parent_id for row in page.data})),
            "Total Invoiced": f"{billed:.2f}",
            "Collected": f"{paid:.2f}",
            "Receivables": f"{outstanding:.2f}",
        }
        if page.total > len(page.data):
            metadata["Note"] = (
                f"Showing the first {len(page.data)} of {page.total}. Narrow the period for a "
                "complete list."
            )
        return ReportTable(
            title="Parent Invoice Report",
            subtitle="Every real Parent Invoice in scope",
            headers=["Parent", "Children", "Period", "Invoice", "Amount", "Paid", "Receivable", "Status"],
            rows=rows,
            metadata=metadata,
            numeric_columns=[4, 5, 6],
            total_row=[
                "TOTAL", "", "", "", f"{billed:.2f}", f"{paid:.2f}", f"{outstanding:.2f}", "",
            ],
        )

    async def parent_payment_report(request: ReportRequest) -> ReportTable:
        """The directive's "Parent Payment Report" (Section 11) — "how much Parent billing has
        actually been collected?", one simpler row per invoice than `parent_invoices_report`
        (no invoice number, no children count): Parent, Billing Period, Invoice Amount, Paid,
        Status. Deliberately no payment method/reference/void history — this is a business
        payment-status report, not a banking ledger (Section 11's own instruction), and this
        model keeps no such ledger to report from regardless (ADR-0042 decision 4). Same
        `list_parent_invoices` source `parent_invoices_report` uses — one calculation, two
        column projections."""
        service: ParentFinanceApplicationService = container.resolve(
            ParentFinanceApplicationService
        )
        school_erp_uow = _scoped(container, SchoolErpUnitOfWork, request)
        transport_ops_uow = _scoped(container, TransportOpsUnitOfWork, request)
        page = await service.list_parent_invoices(
            page=1,
            page_size=_MAX_ROWS,
            period=request.period,
            vehicle_id=request.vehicle_id,
            status=request.status,
            parent_id=request.parent_id,
            school_erp_uow=school_erp_uow,
            transport_ops_uow=transport_ops_uow,
        )
        rows = [
            [row.parent_name, row.period, row.amount, row.amount_paid, row.status.replace("_", " ").title()]
            for row in page.data
        ]
        billed = sum(Decimal(row.amount) for row in page.data)
        paid = sum(Decimal(row.amount_paid) for row in page.data)
        outstanding = sum(Decimal(row.balance_due) for row in page.data)
        return ReportTable(
            title="Parent Payment Report",
            subtitle="How much Parent billing has actually been collected",
            headers=["Parent", "Billing Period", "Invoice Amount", "Paid", "Status"],
            rows=rows,
            metadata={
                "Total Invoiced": f"{billed:.2f}",
                "Total Collected": f"{paid:.2f}",
                "Total Receivables": f"{outstanding:.2f}",
            },
            numeric_columns=[2, 3],
            total_row=["TOTAL", "", f"{billed:.2f}", f"{paid:.2f}", ""],
        )

    async def parent_payment_status_report(request: ReportRequest) -> ReportTable:
        """The directive's "Parent Payment Status Report" (Section 20) — one row per family,
        summing every Parent Invoice in scope into a single Paid/Partial/Unpaid line. One of the
        most useful reports for an Org Admin: it answers "who owes, who's paid, who's partial"
        at a glance, without opening a single invoice."""
        service: ParentFinanceApplicationService = container.resolve(
            ParentFinanceApplicationService
        )
        school_erp_uow = _scoped(container, SchoolErpUnitOfWork, request)
        transport_ops_uow = _scoped(container, TransportOpsUnitOfWork, request)
        page = await service.list_parent_invoices(
            page=1,
            page_size=_MAX_ROWS,
            period=request.period,
            vehicle_id=request.vehicle_id,
            status=None,
            parent_id=request.parent_id,
            school_erp_uow=school_erp_uow,
            transport_ops_uow=transport_ops_uow,
        )
        by_parent: dict[str, dict] = {}
        for row in page.data:
            bucket = by_parent.setdefault(
                row.parent_id,
                {
                    "name": row.parent_name,
                    "children": 0,
                    "due": Decimal("0.00"),
                    "paid": Decimal("0.00"),
                    "outstanding": Decimal("0.00"),
                },
            )
            # A family's child count is stable across periods — `max` rather than summing across
            # every period-row avoids inflating it when a family appears more than once (one row
            # per period in scope).
            bucket["children"] = max(bucket["children"], row.children_count)
            bucket["due"] += Decimal(row.amount)
            bucket["paid"] += Decimal(row.amount_paid)
            bucket["outstanding"] += Decimal(row.balance_due)

        status_counts = {"paid": 0, "partial": 0, "unpaid": 0}
        # Each row is carried alongside its own `group_status` (not re-derived from
        # `by_parent.values()` after sorting) — a dict's values() has no stable relationship to
        # `rows`' post-sort order, and zipping the two back together would silently pair a sorted
        # row with an unrelated bucket's status.
        entries: list[tuple[list[str], str]] = []
        for bucket in by_parent.values():
            group_status = _group_status_for_report(bucket["due"], bucket["paid"])
            status_counts[group_status] += 1
            entries.append(
                (
                    [
                        bucket["name"],
                        str(bucket["children"]),
                        f"{bucket['due']:.2f}",
                        f"{bucket['paid']:.2f}",
                        f"{bucket['outstanding']:.2f}",
                        group_status.title(),
                    ],
                    group_status,
                )
            )
        entries.sort(key=lambda e: e[0][0])
        # `status` (Section 8) narrows the *rendered* rows only, after the summary counts above
        # are already computed from the full in-scope set — a Paid-filtered view still reports
        # accurate Partial/Unpaid counts in its own summary, rather than the counts silently
        # collapsing to match whatever the row filter happened to leave visible.
        if request.status:
            entries = [e for e in entries if e[1] == request.status]
        rows = [row for row, _ in entries]
        total_billed = sum((b["due"] for b in by_parent.values()), Decimal("0.00"))
        total_paid = sum((b["paid"] for b in by_parent.values()), Decimal("0.00"))
        total_outstanding = sum((b["outstanding"] for b in by_parent.values()), Decimal("0.00"))
        return ReportTable(
            title="Parent Payment Status Report",
            subtitle="Every family's overall billed/paid/receivable position, in scope",
            headers=["Parent", "Children", "Billed", "Paid", "Receivable", "Status"],
            rows=rows,
            metadata={
                "Total Parents": str(len(by_parent)),
                "Paid Parents": str(status_counts["paid"]),
                "Partial Parents": str(status_counts["partial"]),
                "Unpaid Parents": str(status_counts["unpaid"]),
                "Total Billed": f"{total_billed:.2f}",
                "Total Collected": f"{total_paid:.2f}",
                "Total Receivables": f"{total_outstanding:.2f}",
            },
            numeric_columns=[2, 3, 4],
            total_row=["TOTAL", "", f"{total_billed:.2f}", f"{total_paid:.2f}", f"{total_outstanding:.2f}", ""],
        )

    # ==========================================================================================
    # Platform reports (billing + platform_finance)
    # ==========================================================================================

    async def subscriptions_report(request: ReportRequest) -> ReportTable:
        uow: BillingUnitOfWork = container.resolve(BillingUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        filters = []
        if request.organization_filter_id:
            filters.append(
                FilterCondition(field="organization_id", op="eq", value=request.organization_filter_id)
            )
        if request.subscription_status:
            filters.append(
                FilterCondition(field="status", op="eq", value=request.subscription_status)
            )
        async with uow:
            page = await _collect(uow.subscriptions, filters=filters)
            # `billing_cycle` lives on `Plan`, not `Subscription` — no column to filter through
            # `_collect`'s server-side `filters`, so this joins and filters client-side, the same
            # technique `revenue_by_plan_report` already uses for its own cross-collection join.
            plan_by_id = {}
            if request.billing_cycle:
                plans = await _collect(uow.plans)
                plan_by_id = {str(p.id): p for p in plans.data}
        rows_data = page.data
        if request.billing_cycle:
            rows_data = [
                s
                for s in rows_data
                if (plan := plan_by_id.get(str(s.plan_id))) is not None
                and plan.billing_cycle.value == request.billing_cycle
            ]
        rows = [
            [
                str(s.organization_id),
                str(s.plan_id),
                s.status.value.replace("_", " ").title(),
                s.current_period_start.date().isoformat() if s.current_period_start else "—",
                s.current_period_end.date().isoformat() if s.current_period_end else "—",
                "Yes" if s.auto_renew else "No",
            ]
            for s in rows_data
        ]
        return ReportTable(
            title="Subscriptions",
            subtitle="Every organization subscription and its lifecycle state",
            headers=["Organization", "Plan", "Status", "Period start", "Period end", "Auto-renew"],
            rows=rows,
            metadata=_metadata(page, "Subscriptions") if not request.billing_cycle else {
                **_metadata(page, "Subscriptions"),
                "Billing cycle": request.billing_cycle.title(),
            },
        )

    async def invoices_report(request: ReportRequest) -> ReportTable:
        uow: BillingUnitOfWork = container.resolve(BillingUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        filters = []
        if request.organization_filter_id:
            filters.append(
                FilterCondition(field="organization_id", op="eq", value=request.organization_filter_id)
            )
        async with uow:
            page = await _collect(uow.invoices, filters=filters)
        rows = [
            [
                i.number,
                str(i.organization_id),
                f"{i.amount.amount:.2f}",
                i.amount.currency,
                i.status.value.title(),
                i.period_start.isoformat(),
                i.period_end.isoformat(),
            ]
            for i in page.data
        ]
        total = sum(i.amount.amount for i in page.data)
        return ReportTable(
            title="Invoices",
            subtitle="RAAD invoices issued to organizations",
            headers=["Number", "Organization", "Amount", "Currency", "Status", "From", "To"],
            rows=rows,
            metadata=_metadata(page, "Invoices"),
            numeric_columns=[2],
            total_row=["TOTAL", "", f"{total:.2f}", "", "", "", ""],
        )

    async def payments_report(request: ReportRequest) -> ReportTable:
        uow: BillingUnitOfWork = container.resolve(BillingUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        filters = []
        if request.organization_filter_id:
            filters.append(
                FilterCondition(field="organization_id", op="eq", value=request.organization_filter_id)
            )
        async with uow:
            page = await _collect(uow.payments, filters=filters)
        rows = [
            [
                p.created_at.date().isoformat(),
                str(p.organization_id),
                f"{p.amount.amount:.2f}",
                p.amount.currency,
                p.provider,
                p.status.value.title(),
            ]
            for p in page.data
        ]
        collected = sum(
            p.amount.amount for p in page.data if p.status.value == "paid"
        )
        return ReportTable(
            title="Payments",
            subtitle="Payment attempts against RAAD invoices",
            headers=["Date", "Organization", "Amount", "Currency", "Provider", "Status"],
            rows=rows,
            metadata=_metadata(page, "Attempts"),
            numeric_columns=[2],
            total_row=["TOTAL PAID", "", f"{collected:.2f}", "", "", ""],
        )

    async def platform_pnl(request: ReportRequest) -> ReportTable:
        service: PlatformFinanceApplicationService = container.resolve(
            PlatformFinanceApplicationService
        )
        uow: PlatformFinanceUnitOfWork = container.resolve(PlatformFinanceUnitOfWork)
        start, end = _window(request)
        pnl = await service.get_platform_pnl(start=start, end=end, uow=uow)
        rows = [
            ["Subscription revenue (collected)", pnl.subscription_revenue],
            ["Other platform income", pnl.other_income],
            ["Total revenue", pnl.total_revenue],
            ["Total operating expenses", pnl.total_expenses],
        ]
        rows.extend(
            [f"  · {kind.replace('_', ' ').title()}", amount]
            for kind, amount in sorted(pnl.expenses_by_kind.items())
        )
        return ReportTable(
            title="Platform Profit & Loss",
            subtitle="RAAD's own revenue against its operating costs",
            headers=["Line", f"Amount ({pnl.currency})"],
            rows=rows,
            metadata={"From": start.isoformat(), "To": end.isoformat()},
            numeric_columns=[1],
            total_row=["NET PROFIT", pnl.net_profit],
        )

    async def platform_receivables(request: ReportRequest) -> ReportTable:
        """Organization Management phase — Invoiced/Collected/Receivables as their own report,
        distinct from the P&L's own line items above. Reuses `get_platform_pnl` verbatim (zero
        new application-layer code, the same "never record a fact `billing` already owns" rule
        `platform_pnl`'s own docstring states) — `subscription_receivables` is a point-in-time
        balance as of `end`, not a sum over the window, so it is called out as such rather than
        implying it is itself windowed like the other two rows."""
        service: PlatformFinanceApplicationService = container.resolve(
            PlatformFinanceApplicationService
        )
        uow: PlatformFinanceUnitOfWork = container.resolve(PlatformFinanceUnitOfWork)
        start, end = _window(request)
        pnl = await service.get_platform_pnl(start=start, end=end, uow=uow)
        rows = [
            ["Invoiced", pnl.subscription_invoiced],
            ["Collected", pnl.subscription_revenue],
            [f"Receivables (as of {end.isoformat()})", pnl.subscription_receivables],
        ]
        return ReportTable(
            title="Receivables",
            subtitle="What RAAD billed organizations, collected, and is still owed",
            headers=["Line", f"Amount ({pnl.currency})"],
            rows=rows,
            metadata={"From": start.isoformat(), "To": end.isoformat()},
            numeric_columns=[1],
            total_row=None,
        )

    async def platform_expenses(request: ReportRequest) -> ReportTable:
        uow: PlatformFinanceUnitOfWork = container.resolve(PlatformFinanceUnitOfWork)
        async with uow:
            page = await _collect(uow.expenses)
        rows = [
            [
                e.occurred_on.isoformat(),
                e.kind.value.replace("_", " ").title(),
                e.vendor or "—",
                f"{e.amount.amount:.2f}",
                e.amount.currency,
                e.description or "—",
            ]
            for e in page.data
        ]
        total = sum(e.amount.amount for e in page.data if not e.is_voided)
        return ReportTable(
            title="Platform Expenses",
            subtitle="RAAD operating costs by heading",
            headers=["Date", "Kind", "Vendor", "Amount", "Currency", "Description"],
            rows=rows,
            metadata=_metadata(page, "Entries"),
            numeric_columns=[3],
            total_row=["TOTAL", "", "", f"{total:.2f}", "", ""],
        )

    # ==========================================================================================
    # Platform reports, continued — Founder catalog expansion (2026-09-09).
    #
    # Every builder below follows the identical shape the five reports above already
    # established: resolve an already-DI-bound `UnitOfWork` for the owning module, set it
    # `organization_ids=None` (platform-wide, matching `subscriptions_report`/`invoices_report`
    # above), collect through `_collect`, format rows the module itself already produces. No new
    # repository query, no new application-service method, no schema change — every figure comes
    # from a read this codebase already had.
    # ==========================================================================================

    async def organizations_report(request: ReportRequest) -> ReportTable:
        uow: OrganizationUnitOfWork = container.resolve(OrganizationUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        async with uow:
            page = await _collect(uow.organizations)
        rows = [
            [
                o.name,
                o.org_type.value.title(),
                o.status.value.title(),
                str(o.region_id),
                str(o.parent_org_id) if o.parent_org_id else "None — top level",
                o.created_at.date().isoformat(),
            ]
            for o in page.data
        ]
        return ReportTable(
            title="Organizations",
            subtitle="Every organization RAAD has onboarded",
            headers=["Name", "Type", "Status", "Region", "Parent organization", "Onboarded"],
            rows=rows,
            metadata=_metadata(page, "Organizations"),
        )

    async def regions_report(request: ReportRequest) -> ReportTable:
        uow: OrganizationUnitOfWork = container.resolve(OrganizationUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        async with uow:
            page = await _collect(uow.regions)
        rows = [
            [r.name, r.geographic_scope or "—", r.status.value.title(), r.created_at.date().isoformat()]
            for r in page.data
        ]
        return ReportTable(
            title="Regions",
            subtitle="RAAD-internal region scoping — every customer organization belongs to one",
            headers=["Name", "Geographic scope", "Status", "Created"],
            rows=rows,
            metadata=_metadata(page, "Regions"),
        )

    async def plans_report(request: ReportRequest) -> ReportTable:
        uow: BillingUnitOfWork = container.resolve(BillingUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        async with uow:
            page = await _collect(uow.plans)
        rows = [
            [
                p.name,
                p.billing_cycle.value.title(),
                f"{p.price.amount:.2f}",
                p.price.currency,
                str(p.vehicle_limit) if p.vehicle_limit is not None else "Unlimited",
                str(p.device_limit) if p.device_limit is not None else "Unlimited",
                str(p.user_limit) if p.user_limit is not None else "Unlimited",
                p.status.value.title(),
            ]
            for p in page.data
        ]
        return ReportTable(
            title="Plans",
            subtitle="The RAAD subscription plan catalogue",
            headers=[
                "Plan", "Cycle", "Amount", "Currency", "Vehicles", "Devices", "Users", "Status",
            ],
            rows=rows,
            metadata=_metadata(page, "Plans"),
            numeric_columns=[2],
        )

    async def vehicles_report(request: ReportRequest) -> ReportTable:
        uow: FleetDeviceUnitOfWork = container.resolve(FleetDeviceUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        async with uow:
            page = await _collect(uow.vehicles)
        rows = [
            [
                v.plate_no,
                v.label or "—",
                str(v.organization_id),
                str(v.capacity) if v.capacity is not None else "—",
                v.status.value.title(),
                v.created_at.date().isoformat(),
            ]
            for v in page.data
        ]
        return ReportTable(
            title="Vehicles",
            subtitle="Every bus registered, across every organization",
            headers=["Plate", "Label", "Organization", "Capacity", "Status", "Registered"],
            rows=rows,
            metadata=_metadata(page, "Vehicles"),
        )

    async def drivers_report(request: ReportRequest) -> ReportTable:
        uow: TransportOpsUnitOfWork = container.resolve(TransportOpsUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        async with uow:
            page = await _collect(uow.drivers)
        rows = [
            [str(d.organization_id), d.license_no, d.status.value.title(), d.created_at.date().isoformat()]
            for d in page.data
        ]
        return ReportTable(
            title="Drivers",
            subtitle="Every driver profile, across every organization",
            headers=["Organization", "Licence", "Status", "Registered"],
            rows=rows,
            metadata=_metadata(page, "Drivers"),
        )

    async def devices_report(request: ReportRequest) -> ReportTable:
        uow: FleetDeviceUnitOfWork = container.resolve(FleetDeviceUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        async with uow:
            page = await _collect(uow.devices)
        rows = [
            [
                str(d.terminal_id),
                d.model or "—",
                str(d.organization_id),
                d.lifecycle_state.value.replace("_", " ").title(),
                "Online" if d.is_online else "Offline",
                d.last_seen_at.isoformat() if d.last_seen_at else "Never",
            ]
            for d in page.data
        ]
        return ReportTable(
            title="Devices",
            subtitle="GPS/MDVR hardware RAAD has allocated, across every organization",
            headers=["Terminal", "Model", "Organization", "Lifecycle", "Connectivity", "Last seen"],
            rows=rows,
            metadata=_metadata(page, "Devices"),
        )

    async def audit_logs_report(request: ReportRequest) -> ReportTable:
        uow: PlatformAuditUnitOfWork = container.resolve(PlatformAuditUnitOfWork)
        async with uow:
            page = await _collect(uow.audit_entries)
        entries = page.data
        if request.start or request.end:
            start = request.start or date.min
            end = request.end or date.today()
            entries = [e for e in entries if start <= e.created_at.date() <= end]
        rows = [
            [
                e.created_at.isoformat(),
                e.action,
                e.entity_type or "—",
                e.entity_id or "—",
                str(e.organization_id) if e.organization_id else "Platform",
                str(e.actor_user_id) if e.actor_user_id else "system",
            ]
            for e in entries
        ]
        return ReportTable(
            title="Audit Logs",
            subtitle="Every recorded platform action — append-only, tamper-evident",
            headers=["When", "Action", "Entity type", "Entity id", "Organization", "Actor"],
            rows=rows,
            metadata=_metadata(page, "Entries"),
        )

    async def _paid_revenue_rows(request: ReportRequest):
        """Shared collection behind the three revenue reports below: every paid `Payment` in the
        requested window, resolved back to its `Plan` (via `Invoice.subscription_id` ->
        `Subscription.plan_id`). One fetch, reused by `revenue_report`/`revenue_by_plan_report`/
        `revenue_by_region_report` — each still calls it independently (a fresh export request
        each), but none re-derives the join logic itself."""
        uow: BillingUnitOfWork = container.resolve(BillingUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        payment_filters = []
        if request.organization_filter_id:
            payment_filters.append(
                FilterCondition(field="organization_id", op="eq", value=request.organization_filter_id)
            )
        async with uow:
            payments_page = await _collect(uow.payments, filters=payment_filters)
            invoices_page = await _collect(uow.invoices)
            subscriptions_page = await _collect(uow.subscriptions)
            plans_page = await _collect(uow.plans)

        plan_by_id = {str(p.id): p for p in plans_page.data}
        plan_id_by_subscription_id = {str(s.id): str(s.plan_id) for s in subscriptions_page.data}
        subscription_id_by_invoice_id = {
            str(i.id): str(i.subscription_id) for i in invoices_page.data
        }

        start, end = _window(request)
        paid = [
            p
            for p in payments_page.data
            if p.status.value == "paid" and start <= p.created_at.date() <= end
        ]
        resolved = []
        for payment in paid:
            subscription_id = subscription_id_by_invoice_id.get(str(payment.invoice_id))
            plan_id = plan_id_by_subscription_id.get(subscription_id) if subscription_id else None
            resolved.append((payment, plan_by_id.get(plan_id) if plan_id else None))
        return resolved

    async def revenue_report(request: ReportRequest) -> ReportTable:
        resolved = await _paid_revenue_rows(request)
        start, end = _window(request)
        rows = [
            [
                p.created_at.date().isoformat(),
                str(p.organization_id),
                plan.name if plan else "—",
                f"{p.amount.amount:.2f}",
                p.amount.currency,
                p.provider,
            ]
            for p, plan in resolved
        ]
        total = sum(p.amount.amount for p, _ in resolved)
        return ReportTable(
            title="Revenue",
            subtitle="Collected subscription revenue — paid payments only, unlike the Payments report",
            headers=["Date", "Organization", "Plan", "Amount", "Currency", "Provider"],
            rows=rows,
            metadata={"From": start.isoformat(), "To": end.isoformat(), "Payments": str(len(rows))},
            numeric_columns=[3],
            total_row=["TOTAL COLLECTED", "", "", f"{total:.2f}", "", ""],
        )

    async def revenue_by_plan_report(request: ReportRequest) -> ReportTable:
        resolved = await _paid_revenue_rows(request)
        start, end = _window(request)
        totals: dict[str, float] = {}
        counts: dict[str, int] = {}
        for payment, plan in resolved:
            key = plan.name if plan else "Unknown plan"
            totals[key] = totals.get(key, 0.0) + float(payment.amount.amount)
            counts[key] = counts.get(key, 0) + 1
        ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        rows = [[name, str(counts[name]), f"{amount:.2f}"] for name, amount in ordered]
        grand_total = sum(totals.values())
        return ReportTable(
            title="Revenue by Plan",
            subtitle="Collected subscription revenue grouped by plan",
            headers=["Plan", "Payments", "Amount"],
            rows=rows,
            metadata={"From": start.isoformat(), "To": end.isoformat()},
            numeric_columns=[1, 2],
            total_row=["TOTAL", "", f"{grand_total:.2f}"],
        )

    async def revenue_by_region_report(request: ReportRequest) -> ReportTable:
        resolved = await _paid_revenue_rows(request)
        start, end = _window(request)

        org_uow: OrganizationUnitOfWork = container.resolve(OrganizationUnitOfWork)
        org_uow.scope = TenantRegionScope(organization_ids=None)
        async with org_uow:
            orgs_page = await _collect(org_uow.organizations)
            regions_page = await _collect(org_uow.regions)
        region_name_by_id = {str(r.id): r.name for r in regions_page.data}
        region_id_by_org_id = {str(o.id): str(o.region_id) for o in orgs_page.data}

        totals: dict[str, float] = {}
        counts: dict[str, int] = {}
        for payment, _plan in resolved:
            region_id = region_id_by_org_id.get(str(payment.organization_id))
            name = region_name_by_id.get(region_id, "Unknown region") if region_id else "Unknown region"
            totals[name] = totals.get(name, 0.0) + float(payment.amount.amount)
            counts[name] = counts.get(name, 0) + 1
        ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        rows = [[name, str(counts[name]), f"{amount:.2f}"] for name, amount in ordered]
        grand_total = sum(totals.values())
        return ReportTable(
            title="Revenue by Region",
            subtitle="Collected subscription revenue grouped by region",
            headers=["Region", "Payments", "Amount"],
            rows=rows,
            metadata={"From": start.isoformat(), "To": end.isoformat()},
            numeric_columns=[1, 2],
            total_row=["TOTAL", "", f"{grand_total:.2f}"],
        )

    definitions = [
        # -- Organization: Financial (Report Center re-design, 2026-09-11) ----------------------
        #
        # `org.student_billing`/`org.parent_payments` (the pre-redesign "Student Billing"/
        # "Parent Payments" definitions, `legacy_student_billing`/`legacy_student_payment_ledger`
        # above) are deliberately **not** registered below — both are superseded by a directive-
        # named report reading the identical underlying money at the correct Parent grain, and
        # both carried either forbidden terminology or columns (raw `student_id`, payment
        # method/reference) the directive rules out for the new business model. The two builders
        # are kept, not deleted, per ADR-0042 decision 2.
        #
        # Category assignment: Financial = the organization's own books (invoices, payments,
        # receivables, income, expense, P&L); Transportation = vehicle/bus rosters. Not literally
        # dictated by any one document field — a deliberate, disclosed grouping decision
        # consistent with how each report is actually used, matching `ReportDefinition.category`'s
        # own "backend-owned grouping" rationale.
        #
        # Report Center catalog cleanup (2026-09-13, explicit user directive): `org.
        # parent_payment_report`, `org.vehicle_revenue` and `org.student_transportation` are
        # deliberately **not** registered below, and the entire "Management" category
        # (`org.parent_payment_status`/`org.monthly_financial_summary`/`org.
        # yearly_financial_summary`) is removed outright — Parent Payment Report is superseded by
        # Parent Invoice Report's own payment/status columns, and the rest are simply out of the
        # current RAAD Reports scope. Same precedent as `org.student_billing`/`org.parent_payments`
        # above: every builder is kept, not deleted — this is a catalog *visibility* change only,
        # no calculation, filter, permission, or schema change.
        ReportDefinition(
            key="org.parent_invoices",
            title="Parent Invoice Report",
            description="Every real Parent Invoice, grouped by parent and billing period.",
            scope="organization",
            build=parent_invoices_report,
            roles=_ORG_ROLES,
            accepts=("period", "vehicle_id", "parent_id", "status"),
            category="financial",
        ),
        ReportDefinition(
            key="org.receivables",
            title="Receivables Report",
            description="Every Parent Invoice with money still owed to the organization.",
            scope="organization",
            build=receivables_report,
            roles=_ORG_ROLES,
            accepts=("period", "vehicle_id", "parent_id", "status"),
            category="financial",
        ),
        ReportDefinition(
            key="org.income",
            title="Income Report",
            description="Parent transportation collections shown separately from other income.",
            scope="organization",
            build=income_report,
            roles=_ORG_ROLES,
            accepts=("start", "end"),
            category="financial",
        ),
        ReportDefinition(
            key="org.expense",
            title="Expense Report",
            description="Every recorded organization expense, optionally by vehicle.",
            scope="organization",
            build=expense_report,
            roles=_ORG_ROLES,
            accepts=("start", "end", "vehicle_id"),
            category="financial",
        ),
        ReportDefinition(
            key="org.profit_and_loss",
            title="Profit & Loss",
            description="School income against expenses for a date range.",
            scope="organization",
            build=org_profit_and_loss,
            roles=_ORG_ROLES,
            accepts=("start", "end"),
            category="financial",
        ),
        # -- Organization: Transportation ---------------------------------------------------------
        ReportDefinition(
            key="org.vehicle_cost",
            title="Vehicle Cost Report",
            description="Attributable cost per bus, or by category for one selected bus.",
            scope="organization",
            build=vehicle_cost_report,
            roles=_ORG_ROLES,
            accepts=("start", "end", "vehicle_id"),
            category="transportation",
        ),
        ReportDefinition(
            key="org.bus_report",
            title="Bus Report",
            description="One bus: assigned families, expected revenue, collected and receivables.",
            scope="organization",
            build=bus_report,
            roles=_ORG_ROLES,
            accepts=("vehicle_id", "period", "status"),
            category="transportation",
        ),
        # -- Platform ----------------------------------------------------------------------------
        # Organization Management phase: every platform-scope definition below now sets an
        # explicit `category` (previously all silently defaulted to "financial") so the redesigned
        # Platform Report Center can group them the same way the Organization Report Center groups
        # its own two categories — "subscriptions" is a genuinely new category value, and
        # "platform" (already a legal `ReportCategory` value on the frontend, previously unused by
        # any definition) is repurposed as the directory/operational catch-all for the seven
        # reports that are neither financial nor subscription-lifecycle facts, so none of them
        # loses its existing reachability.
        ReportDefinition(
            key="platform.subscriptions",
            title="Subscriptions",
            description="Every organization subscription and its lifecycle state.",
            scope="platform",
            build=subscriptions_report,
            roles=_PLATFORM_ROLES,
            accepts=("organization_id", "subscription_status", "billing_cycle"),
            category="subscriptions",
        ),
        ReportDefinition(
            key="platform.invoices",
            title="Invoices",
            description="RAAD invoices issued to organizations.",
            scope="platform",
            build=invoices_report,
            roles=_PLATFORM_ROLES,
            accepts=("organization_id",),
            category="financial",
        ),
        ReportDefinition(
            key="platform.payments",
            title="Payments",
            description="Payment attempts against RAAD invoices.",
            scope="platform",
            build=payments_report,
            roles=_PLATFORM_ROLES,
            accepts=("organization_id",),
            category="financial",
        ),
        ReportDefinition(
            key="platform.profit_and_loss",
            title="Platform Profit & Loss",
            description="RAAD revenue against operating costs.",
            scope="platform",
            build=platform_pnl,
            roles=_FINANCE_ROLES,
            accepts=("start", "end"),
            category="financial",
        ),
        ReportDefinition(
            key="platform.receivables",
            title="Receivables",
            description="What RAAD billed organizations, collected, and is still owed.",
            scope="platform",
            build=platform_receivables,
            roles=_FINANCE_ROLES,
            accepts=("start", "end"),
            category="financial",
        ),
        ReportDefinition(
            key="platform.expenses",
            title="Platform Expenses",
            description="RAAD operating costs by heading.",
            scope="platform",
            build=platform_expenses,
            roles=_FINANCE_ROLES,
            category="financial",
        ),
        # -- Platform catalog expansion (2026-09-09) --------------------------------------------
        ReportDefinition(
            key="platform.organizations",
            title="Organizations",
            description="Every organization RAAD has onboarded, with type, status and region.",
            scope="platform",
            build=organizations_report,
            roles=_PLATFORM_ROLES,
            category="platform",
        ),
        ReportDefinition(
            key="platform.regions",
            title="Regions",
            description="RAAD-internal region scoping.",
            scope="platform",
            build=regions_report,
            roles=_PLATFORM_ROLES,
            category="platform",
        ),
        ReportDefinition(
            key="platform.plans",
            title="Plans",
            description="The RAAD subscription plan catalogue.",
            scope="platform",
            build=plans_report,
            roles=_PLATFORM_ROLES,
            category="platform",
        ),
        ReportDefinition(
            key="platform.vehicles",
            title="Vehicles",
            description="Every bus registered, across every organization.",
            scope="platform",
            build=vehicles_report,
            roles=_PLATFORM_ROLES,
            category="platform",
        ),
        ReportDefinition(
            key="platform.drivers",
            title="Drivers",
            description="Every driver profile, across every organization.",
            scope="platform",
            build=drivers_report,
            roles=_PLATFORM_ROLES,
            category="platform",
        ),
        ReportDefinition(
            key="platform.devices",
            title="Devices",
            description="GPS/MDVR hardware RAAD has allocated, across every organization.",
            scope="platform",
            build=devices_report,
            roles=_PLATFORM_ROLES,
            category="platform",
        ),
        ReportDefinition(
            key="platform.audit_logs",
            title="Audit Logs",
            description="Every recorded platform action — append-only, tamper-evident.",
            scope="platform",
            build=audit_logs_report,
            roles=_AUDIT_ROLES,
            accepts=("start", "end"),
            category="platform",
        ),
        ReportDefinition(
            key="platform.revenue",
            title="Revenue",
            description="Collected subscription revenue — paid payments only.",
            scope="platform",
            build=revenue_report,
            roles=_FINANCE_ROLES,
            accepts=("start", "end", "organization_id"),
            category="financial",
        ),
        ReportDefinition(
            key="platform.revenue_by_plan",
            title="Revenue by Plan",
            description="Collected subscription revenue grouped by plan.",
            scope="platform",
            build=revenue_by_plan_report,
            roles=_FINANCE_ROLES,
            accepts=("start", "end"),
            category="financial",
        ),
        ReportDefinition(
            key="platform.revenue_by_region",
            title="Revenue by Region",
            description="Collected subscription revenue grouped by region.",
            scope="platform",
            build=revenue_by_region_report,
            roles=_FINANCE_ROLES,
            accepts=("start", "end"),
            category="financial",
        ),
    ]

    for definition in definitions:
        catalog.register(definition)
