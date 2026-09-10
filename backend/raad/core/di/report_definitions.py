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

from dataclasses import dataclass
from typing import Any

from raad.core.di.container import Container
from raad.core.pagination import MAX_PAGE_SIZE, OffsetPageRequest
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
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
from raad.modules.school_erp.application.services import SchoolErpApplicationService
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork

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


async def _collect(repository, *, limit: int = _MAX_ROWS) -> _Rows:
    """Reads up to `limit` rows through a repository's `list_page`, one allowed page at a time.

    **Why not simply ask for `page_size=limit`.** `OffsetPageRequest` rejects any page size above
    `MAX_PAGE_SIZE` (100) — it is a `ValidationError`, raised in the constructor, so a builder
    that asked for 1000 rows did not return a short report: it returned `422` and rendered
    nothing at all. That is what every list-backed report did before this helper existed, live
    against the running API, while every test still passed because no test exercised a builder.

    Paging keeps the documented 1000-row cap real rather than quietly reducing it to 100.
    """
    collected: list[Any] = []
    page_number = 1
    total = 0
    while len(collected) < limit:
        page_size = min(MAX_PAGE_SIZE, limit - len(collected))
        page = await repository.list_page(
            OffsetPageRequest(page=page_number, page_size=page_size),
            filters=[],
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

    async def student_billing(request: ReportRequest) -> ReportTable:
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
        service: SchoolErpApplicationService = container.resolve(SchoolErpApplicationService)
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        summaries = await service.get_vehicle_financial_overview(
            period=request.period, uow=uow
        )
        rows = [
            [
                s.vehicle_id or "Unassigned",
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
            subtitle="Revenue, collections, outstanding balance and attributed cost per bus",
            headers=[
                "Vehicle", "Students", "Paid", "Unpaid", "Billed", "Collected",
                "Outstanding", "Cost", "Net",
            ],
            rows=rows,
            metadata={"Period": _period_label(request), "Vehicles": str(len(rows))},
            numeric_columns=[1, 2, 3, 4, 5, 6, 7, 8],
        )

    async def bus_roster(request: ReportRequest) -> ReportTable:
        """The printable per-bus report: who rides this bus, and what they owe."""
        service: SchoolErpApplicationService = container.resolve(SchoolErpApplicationService)
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        if not request.vehicle_id:
            return ReportTable(
                title="Bus Report",
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
            title="Bus Report",
            subtitle="Students, fees and outstanding balances for one vehicle",
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

    async def outstanding_balances(request: ReportRequest) -> ReportTable:
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        async with uow:
            page = await _collect(uow.student_invoices)
        unpaid = [i for i in page.data if i.balance_due > 0]
        rows = [
            [
                str(i.student_id),
                str(i.period),
                str(i.vehicle_id or "—"),
                f"{i.balance_due:.2f}",
                i.due_date.isoformat(),
                i.status.value.replace("_", " ").title(),
            ]
            for i in unpaid
        ]
        total = sum(i.balance_due for i in unpaid)
        return ReportTable(
            title="Outstanding Balances",
            subtitle="Every student invoice with money still owed",
            headers=["Student", "Period", "Vehicle", "Balance", "Due", "Status"],
            rows=rows,
            metadata={"Unpaid invoices": str(len(unpaid))},
            numeric_columns=[3],
            total_row=["TOTAL", "", "", f"{total:.2f}", "", ""],
        )

    async def org_profit_and_loss(request: ReportRequest) -> ReportTable:
        service: SchoolErpApplicationService = container.resolve(SchoolErpApplicationService)
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        start, end = _window(request)
        pnl = await service.get_profit_and_loss(start=start, end=end, uow=uow)
        rows = [
            ["Student fee revenue (collected)", pnl.student_revenue],
            ["Other income", pnl.other_income],
            ["Total income", pnl.total_income],
            ["Total expenses", pnl.total_expenses],
        ]
        return ReportTable(
            title="Profit & Loss",
            subtitle="Derived from actual recorded transactions only",
            headers=["Line", f"Amount ({pnl.currency})"],
            rows=rows,
            metadata={"From": start.isoformat(), "To": end.isoformat()},
            numeric_columns=[1],
            total_row=["NET PROFIT", pnl.net_profit],
        )

    async def student_payments(request: ReportRequest) -> ReportTable:
        uow = _scoped(container, SchoolErpUnitOfWork, request)
        async with uow:
            page = await _collect(uow.student_payments)
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
            title="Parent Payments",
            subtitle="Payments received from families, voided entries included and marked",
            headers=["Received", "Student", "Amount", "Currency", "Method", "Reference", "State"],
            rows=rows,
            metadata=_metadata(page, "Payments"),
            numeric_columns=[2],
            total_row=["TOTAL COLLECTED", "", f"{collected:.2f}", "", "", "", ""],
        )

    # ==========================================================================================
    # Platform reports (billing + platform_finance)
    # ==========================================================================================

    async def subscriptions_report(request: ReportRequest) -> ReportTable:
        uow: BillingUnitOfWork = container.resolve(BillingUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        async with uow:
            page = await _collect(uow.subscriptions)
        rows = [
            [
                str(s.organization_id),
                str(s.plan_id),
                s.status.value.replace("_", " ").title(),
                s.current_period_start.date().isoformat() if s.current_period_start else "—",
                s.current_period_end.date().isoformat() if s.current_period_end else "—",
                "Yes" if s.auto_renew else "No",
            ]
            for s in page.data
        ]
        return ReportTable(
            title="Subscriptions",
            subtitle="Every organization subscription and its lifecycle state",
            headers=["Organization", "Plan", "Status", "Period start", "Period end", "Auto-renew"],
            rows=rows,
            metadata=_metadata(page, "Subscriptions"),
        )

    async def invoices_report(request: ReportRequest) -> ReportTable:
        uow: BillingUnitOfWork = container.resolve(BillingUnitOfWork)
        uow.scope = TenantRegionScope(organization_ids=None)
        async with uow:
            page = await _collect(uow.invoices)
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
        async with uow:
            page = await _collect(uow.payments)
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
        async with uow:
            payments_page = await _collect(uow.payments)
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
        # -- Organization ----------------------------------------------------------------------
        ReportDefinition(
            key="org.student_billing",
            title="Student Billing",
            description="Every student invoice with paid and outstanding amounts.",
            scope="organization",
            build=student_billing,
            roles=_ORG_ROLES,
            accepts=("period",),
        ),
        ReportDefinition(
            key="org.vehicle_revenue",
            title="Vehicle Revenue",
            description="Revenue, collections, outstanding balance and cost per bus.",
            scope="organization",
            build=vehicle_revenue,
            roles=_ORG_ROLES,
            accepts=("period",),
        ),
        ReportDefinition(
            key="org.bus_report",
            title="Bus Report",
            description="Printable roster for one vehicle: students, fees and balances.",
            scope="organization",
            build=bus_roster,
            roles=_ORG_ROLES,
            accepts=("vehicle_id", "period"),
        ),
        ReportDefinition(
            key="org.outstanding_balances",
            title="Outstanding Balances",
            description="Every student invoice with money still owed.",
            scope="organization",
            build=outstanding_balances,
            roles=_ORG_ROLES,
        ),
        ReportDefinition(
            key="org.parent_payments",
            title="Parent Payments",
            description="Payments received from families, including voided entries.",
            scope="organization",
            build=student_payments,
            roles=_ORG_ROLES,
        ),
        ReportDefinition(
            key="org.profit_and_loss",
            title="Profit & Loss",
            description="School income against expenses for a date range.",
            scope="organization",
            build=org_profit_and_loss,
            roles=_ORG_ROLES,
            accepts=("start", "end"),
        ),
        # -- Platform --------------------------------------------------------------------------
        ReportDefinition(
            key="platform.subscriptions",
            title="Subscriptions",
            description="Every organization subscription and its lifecycle state.",
            scope="platform",
            build=subscriptions_report,
            roles=_PLATFORM_ROLES,
        ),
        ReportDefinition(
            key="platform.invoices",
            title="Invoices",
            description="RAAD invoices issued to organizations.",
            scope="platform",
            build=invoices_report,
            roles=_PLATFORM_ROLES,
        ),
        ReportDefinition(
            key="platform.payments",
            title="Payments",
            description="Payment attempts against RAAD invoices.",
            scope="platform",
            build=payments_report,
            roles=_PLATFORM_ROLES,
        ),
        ReportDefinition(
            key="platform.profit_and_loss",
            title="Platform Profit & Loss",
            description="RAAD revenue against operating costs.",
            scope="platform",
            build=platform_pnl,
            roles=_FINANCE_ROLES,
            accepts=("start", "end"),
        ),
        ReportDefinition(
            key="platform.expenses",
            title="Platform Expenses",
            description="RAAD operating costs by heading.",
            scope="platform",
            build=platform_expenses,
            roles=_FINANCE_ROLES,
        ),
        # -- Platform catalog expansion (2026-09-09) --------------------------------------------
        ReportDefinition(
            key="platform.organizations",
            title="Organizations",
            description="Every organization RAAD has onboarded, with type, status and region.",
            scope="platform",
            build=organizations_report,
            roles=_PLATFORM_ROLES,
        ),
        ReportDefinition(
            key="platform.regions",
            title="Regions",
            description="RAAD-internal region scoping.",
            scope="platform",
            build=regions_report,
            roles=_PLATFORM_ROLES,
        ),
        ReportDefinition(
            key="platform.plans",
            title="Plans",
            description="The RAAD subscription plan catalogue.",
            scope="platform",
            build=plans_report,
            roles=_PLATFORM_ROLES,
        ),
        ReportDefinition(
            key="platform.vehicles",
            title="Vehicles",
            description="Every bus registered, across every organization.",
            scope="platform",
            build=vehicles_report,
            roles=_PLATFORM_ROLES,
        ),
        ReportDefinition(
            key="platform.drivers",
            title="Drivers",
            description="Every driver profile, across every organization.",
            scope="platform",
            build=drivers_report,
            roles=_PLATFORM_ROLES,
        ),
        ReportDefinition(
            key="platform.devices",
            title="Devices",
            description="GPS/MDVR hardware RAAD has allocated, across every organization.",
            scope="platform",
            build=devices_report,
            roles=_PLATFORM_ROLES,
        ),
        ReportDefinition(
            key="platform.audit_logs",
            title="Audit Logs",
            description="Every recorded platform action — append-only, tamper-evident.",
            scope="platform",
            build=audit_logs_report,
            roles=_AUDIT_ROLES,
            accepts=("start", "end"),
        ),
        ReportDefinition(
            key="platform.revenue",
            title="Revenue",
            description="Collected subscription revenue — paid payments only.",
            scope="platform",
            build=revenue_report,
            roles=_FINANCE_ROLES,
            accepts=("start", "end"),
        ),
        ReportDefinition(
            key="platform.revenue_by_plan",
            title="Revenue by Plan",
            description="Collected subscription revenue grouped by plan.",
            scope="platform",
            build=revenue_by_plan_report,
            roles=_FINANCE_ROLES,
            accepts=("start", "end"),
        ),
        ReportDefinition(
            key="platform.revenue_by_region",
            title="Revenue by Region",
            description="Collected subscription revenue grouped by region.",
            scope="platform",
            build=revenue_by_region_report,
            roles=_FINANCE_ROLES,
            accepts=("start", "end"),
        ),
    ]

    for definition in definitions:
        catalog.register(definition)
