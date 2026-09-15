"""HTTP surface of the `reporting` module (C9). Mounted at `/api/v1/reports` (Backend LLD
§16.1). Thin controllers only (Backend LLD §16.2): parse the request DTO, call exactly one
`ReportingApplicationService` method, return the response DTO — every error already maps to the
standard `ErrorEnvelope` via the global exception handlers. Mirrors `billing.api.routers`/
`notifications.api.routers`'s shape.

**Two routes, matching API Contracts §4.8's table exactly (lines 188-189) — no more, no less.**
The task's own scope explicitly forbids inventing export/analytics/dashboard endpoints unless
documented, and none is:

- `POST /reports/runs` — line 188, "Org Admin/Finance", "async render → report_run". Persists a
  `QUEUED` `ReportRun` only — no rendering happens here (out of scope, see `domain/entities.py`'s
  module docstring). Returns `202 Accepted` + the full resource, matching API Contracts §6's own
  documented pattern ("Write responses return the full resource (or `202 Accepted` + a job
  handle for async, e.g., **reports**/payments)" — reports is explicitly named as this pattern's
  own example).
- `GET /reports/runs/{id}` — line 189, "requester", "status + artifact url". Ownership enforced
  directly (not RBAC-deferred): a non-requester caller gets `NotFoundError` (404), not
  `AuthorizationError` — see `application/queries.py`'s `GetReportRunByIdQuery` docstring for
  the 404-over-403 reasoning, the same posture `notifications` already establishes.

**Not exposed this phase** (flagged, not silently dropped): no `GET /reports/runs` (list) route
is documented (API Contracts §4.8 gives only the two rows above); no status-transition routes
(`start`/`succeed`/`fail`) either — those are the future Report Worker's own entry points
(`application/commands.py`'s own docstring), unreachable via HTTP this phase, mirroring
`Route.remove_stop`/`Trip.interrupt`/`MarkPaymentExpiredCommand`'s identical "use-case exists,
no approved endpoint yet" posture.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel

from raad.core.di.container import Container
from raad.core.errors.exceptions import NotFoundError
from raad.core.tenancy.scope import TenantRegionScope
from raad.interfaces.http.deps import get_container, get_scope
from raad.modules.reporting.application.catalog import ReportCatalog, ReportRequest
from raad.modules.reporting.application.export_service import ReportExportService

from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import require_permission
from raad.modules.reporting.api.deps import get_reporting_service, get_reporting_uow
from raad.modules.reporting.api.schemas import RequestReportRequest, ReportRunResponse
from raad.modules.reporting.application.commands import RequestReportCommand
from raad.modules.reporting.application.ports import ReportingUnitOfWork
from raad.modules.reporting.application.queries import GetReportRunByIdQuery, ReportRunDTO
from raad.modules.reporting.application.services import ReportingApplicationService

reports_router = APIRouter()


def _report_run_dto_to_response(report_run: ReportRunDTO) -> ReportRunResponse:
    return ReportRunResponse(
        id=report_run.id,
        organization_id=report_run.organization_id,
        type=report_run.type,
        params=report_run.params,
        status=report_run.status,
        artifact_url=report_run.artifact_url,
        requested_by=report_run.requested_by,
        created_at=report_run.created_at,
        completed_at=report_run.completed_at,
    )


@reports_router.post(
    "/runs",
    response_model=ReportRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a report render",
    description=(
        "Org Admin/Finance (API Contracts §4.8 line 188: \"async render -> report_run\"). "
        "Persists a `QUEUED` `ReportRun` only - actual rendering is out of this phase's scope, "
        "see `domain/entities.py`'s module docstring. Authorization resolves against the "
        "real seeded RBAC permission matrix (ADR-0004)."
    ),
)
async def request_report(
    body: RequestReportRequest,
    principal: Principal = Depends(require_permission(Permission("reporting.reports.create"))),
    reporting_service: ReportingApplicationService = Depends(get_reporting_service),
    uow: ReportingUnitOfWork = Depends(get_reporting_uow),
) -> ReportRunResponse:
    command = RequestReportCommand(
        organization_id=body.organization_id,
        type=body.type,
        params=body.params,
        actor=principal,
    )
    report_run = await reporting_service.request_report(command, uow=uow)
    return _report_run_dto_to_response(report_run)


@reports_router.get(
    "/runs/{report_run_id}",
    response_model=ReportRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a report run's status and artifact url",
    description=(
        "Requester (API Contracts §4.8 line 189: \"status + artifact url\"). Ownership "
        "enforced directly - see `application/queries.py`'s `GetReportRunByIdQuery` docstring "
        "for the 404-over-403 reasoning. Authorization resolves against the real seeded "
        "RBAC permission matrix."
    ),
)
async def get_report_run(
    report_run_id: str,
    principal: Principal = Depends(require_permission(Permission("reporting.reports.read"))),
    reporting_service: ReportingApplicationService = Depends(get_reporting_service),
    uow: ReportingUnitOfWork = Depends(get_reporting_uow),
) -> ReportRunResponse:
    report_run = await reporting_service.get_report_run_by_id(
        GetReportRunByIdQuery(
            report_run_id=report_run_id, requester_user_id=principal.user_id
        ),
        uow=uow,
    )
    return _report_run_dto_to_response(report_run)


# --- ADR-0040 §6: the report catalogue and synchronous export --------------------------------
#
# **Why synchronous.** `ReportRun` (above) models a queued, long-running render whose artifact
# lands in an object store — and that store does not exist in this repository (Phase-2 §10.1 is
# unbuilt). Rather than fake an artifact URL, these two routes render on demand and stream the
# bytes back. `ReportRun` is left exactly as it was, still the right home for long runs once a
# store exists, with `artifact_url` still honestly unpopulated.
#
# The trade-off is stated rather than hidden: a very large report blocks its request. Builders
# cap themselves at 1000 rows (`core/di/report_definitions.py`), which covers a full school's
# monthly roster.


class ReportDefinitionResponse(BaseModel):
    key: str
    title: str
    description: str
    scope: str
    accepts: list[str]
    category: str


class ReportTableResponse(BaseModel):
    """ADR-0041 §3 — the JSON shape of `GET /reports/{key}/preview`, one field-for-field mirror
    of `application.report_table.ReportTable`. Built by the exact same `ReportExportService.
    build_table` call `export_report` below now also uses, so a preview and its PDF/XLSX can
    never disagree — one source of truth, not two calculations of the same numbers."""

    title: str
    subtitle: str | None
    headers: list[str]
    rows: list[list[str]]
    metadata: dict[str, str]
    numeric_columns: list[int]
    total_row: list[str] | None


@reports_router.get(
    "/catalog",
    response_model=list[ReportDefinitionResponse],
    status_code=status.HTTP_200_OK,
    summary="List the reports this caller can generate",
    description=(
        "Filtered to the definitions this caller's role may actually generate. The export "
        "route re-checks the same role list before building anything, so naming an unlisted "
        "key directly is refused rather than served."
    ),
)
async def list_report_catalog(
    scope: str | None = Query(default=None, pattern="^(platform|organization)$"),
    principal: Principal = Depends(require_permission(Permission("reporting.reports.request"))),
    container: Container = Depends(get_container),
) -> list[ReportDefinitionResponse]:
    catalog: ReportCatalog = container.resolve(ReportCatalog)
    return [
        ReportDefinitionResponse(
            key=d.key,
            title=d.title,
            description=d.description,
            scope=d.scope,
            accepts=list(d.accepts),
            category=d.category,
        )
        for d in catalog.list_for(principal, scope=scope)
    ]


@reports_router.get(
    "/{definition_key}/export",
    status_code=status.HTTP_200_OK,
    summary="Render and download a report",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
            },
            "description": "The rendered report as a file download.",
        }
    },
)
async def export_report(
    definition_key: str,
    format: str = Query(default="pdf", pattern="^(pdf|xlsx)$"),
    period: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    vehicle_id: str | None = Query(default=None),
    parent_id: str | None = Query(default=None),
    payment_method: str | None = Query(default=None),
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(unpaid|partial|paid|cancelled)$"
    ),
    organization_id: str | None = Query(
        default=None,
        description="Platform Report Center only — narrows a platform-scope report to one "
        "organization. Never used to resolve an organization-scope report's own tenant, which "
        "always comes from the caller's own principal.",
    ),
    subscription_status: str | None = Query(default=None),
    billing_cycle: str | None = Query(default=None, pattern="^(monthly|quarterly|annual)$"),
    principal: Principal = Depends(require_permission(Permission("reporting.reports.request"))),
    scope: TenantRegionScope = Depends(get_scope),
    container: Container = Depends(get_container),
) -> Response:
    export_service: ReportExportService = container.resolve(ReportExportService)
    rendered = await export_service.export(
        definition_key=definition_key,
        format=format,
        request=ReportRequest(
            principal=principal,
            organization_id=principal.org_id,
            start=start,
            end=end,
            period=period,
            vehicle_id=vehicle_id,
            parent_id=parent_id,
            payment_method=payment_method,
            status=status_filter,
            organization_filter_id=organization_id,
            subscription_status=subscription_status,
            billing_cycle=billing_cycle,
            scope=scope,
        ),
    )
    return Response(
        content=rendered.content,
        media_type=rendered.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{rendered.filename}"'
        },
    )


@reports_router.get(
    "/{definition_key}/preview",
    response_model=ReportTableResponse,
    status_code=status.HTTP_200_OK,
    summary="Render a report as JSON, for an in-app preview before export",
    description=(
        "ADR-0041 §3 — the same permission check and the same `definition.build(request)` call "
        "`export` makes (via the shared `ReportExportService.build_table`), returned as JSON "
        "instead of PDF/XLSX bytes. A preview and its export can never disagree: both read the "
        "identical `ReportTable`."
    ),
)
async def preview_report(
    definition_key: str,
    period: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    vehicle_id: str | None = Query(default=None),
    parent_id: str | None = Query(default=None),
    payment_method: str | None = Query(default=None),
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(unpaid|partial|paid|cancelled)$"
    ),
    organization_id: str | None = Query(
        default=None,
        description="Platform Report Center only — narrows a platform-scope report to one "
        "organization. Never used to resolve an organization-scope report's own tenant, which "
        "always comes from the caller's own principal.",
    ),
    subscription_status: str | None = Query(default=None),
    billing_cycle: str | None = Query(default=None, pattern="^(monthly|quarterly|annual)$"),
    principal: Principal = Depends(require_permission(Permission("reporting.reports.request"))),
    scope: TenantRegionScope = Depends(get_scope),
    container: Container = Depends(get_container),
) -> ReportTableResponse:
    export_service: ReportExportService = container.resolve(ReportExportService)
    table = await export_service.build_table(
        definition_key=definition_key,
        request=ReportRequest(
            principal=principal,
            organization_id=principal.org_id,
            start=start,
            end=end,
            period=period,
            vehicle_id=vehicle_id,
            parent_id=parent_id,
            payment_method=payment_method,
            status=status_filter,
            organization_filter_id=organization_id,
            subscription_status=subscription_status,
            billing_cycle=billing_cycle,
            scope=scope,
        ),
    )
    return ReportTableResponse(
        title=table.title,
        subtitle=table.subtitle,
        headers=table.headers,
        rows=table.rows,
        metadata=table.metadata,
        numeric_columns=table.numeric_columns,
        total_row=table.total_row,
    )
