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

from fastapi import APIRouter, Depends, status

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
