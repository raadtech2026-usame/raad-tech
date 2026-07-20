"""Reporting application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite read-models). DTOs
are plain dataclasses — id fields become `str(vo)`, enum fields become `.value`, timestamps stay
native `datetime`, mirroring `billing.application.queries`'s exact convention.

**`ListReportRunsQuery` has no approved HTTP route** — API Contracts §4.8 documents no list
route for `report_runs` (this module's own `CLAUDE.md`-recorded scope note). Added under the
Backend Stabilization phase as the Report Worker's own entry point for finding `queued` work,
the same "use-case exists, no approved endpoint yet" posture `StartReportCommand`/
`MarkReportSucceededCommand` already establish for this identical module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from raad.modules.reporting.domain.entities import ReportRun


@dataclass(frozen=True)
class GetReportRunByIdQuery:
    """`requester_user_id` is the requesting caller's own id (router-populated from
    `principal.user_id`) — API Contracts §4.8's role column for `GET /reports/runs/{id}` is
    literally "requester", not "Org Admin/Finance" — enforced here, not RBAC-deferred. A
    mismatch raises `NotFoundError`, not `AuthorizationError` — mirrors `notifications.
    application.queries.GetNotificationByIdQuery`'s identical, already-established 404-over-403
    reasoning."""

    report_run_id: str
    requester_user_id: str


@dataclass(frozen=True)
class ListReportRunsQuery:
    status: str | None = None


@dataclass(frozen=True)
class ReportRunDTO:
    id: str
    organization_id: str
    type: str
    params: dict[str, Any] | None
    status: str
    artifact_url: str | None
    requested_by: str
    created_at: datetime
    completed_at: datetime | None


def report_run_to_dto(report_run: ReportRun) -> ReportRunDTO:
    return ReportRunDTO(
        id=str(report_run.id),
        organization_id=str(report_run.organization_id),
        type=report_run.type.value,
        params=report_run.params,
        status=report_run.status.value,
        artifact_url=report_run.artifact_url,
        requested_by=str(report_run.requested_by),
        created_at=report_run.created_at,
        completed_at=report_run.completed_at,
    )
