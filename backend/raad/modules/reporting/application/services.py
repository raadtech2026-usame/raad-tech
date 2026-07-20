"""Reporting application service (Backend LLD §4.1/§4.3). One `ReportingApplicationService`
class for the module's single aggregate, mirroring `billing`/`notifications`'s single-service
convention.

**Ownership enforcement (not RBAC) is implemented directly here**, mirroring `notifications.
application.services`'s identical, already-established posture: `get_report_run_by_id` compares
`ReportRun.requested_by` against the caller's `actor`/`requester_user_id` — API Contracts §4.8's
role column for `GET /reports/runs/{id}` is literally "requester", not a broader RBAC role. A
mismatch raises `NotFoundError` (see `queries.py`'s `GetReportRunByIdQuery` docstring for the
404-over-403 reasoning).

**`request_report` persists a `QUEUED` row only** — no rendering happens here (out of scope).
`start_report`/`mark_report_succeeded`/`mark_report_failed` exist for the future Report Worker's
own use, unreachable via any HTTP route this phase.
"""

from __future__ import annotations

from raad.core.errors.exceptions import NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.time.clock import Clock
from raad.modules.reporting.application.commands import (
    MarkReportFailedCommand,
    MarkReportSucceededCommand,
    RequestReportCommand,
    StartReportCommand,
)
from raad.modules.reporting.application.ports import ReportingUnitOfWork
from raad.modules.reporting.application.queries import (
    GetReportRunByIdQuery,
    ListReportRunsQuery,
    ReportRunDTO,
    report_run_to_dto,
)
from raad.modules.reporting.application.validators import ensure_report_run_exists
from raad.modules.reporting.domain.entities import ReportRun
from raad.modules.reporting.domain.value_objects import (
    OrganizationId,
    ReportId,
    ReportType,
    UserId,
)


class ReportingApplicationService:
    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    async def request_report(
        self, command: RequestReportCommand, *, uow: ReportingUnitOfWork
    ) -> ReportRunDTO:
        async with uow:
            report_run = ReportRun.request(
                id=ReportId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                type=ReportType(command.type),
                params=command.params,
                requested_by=UserId(command.actor.user_id),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.report_runs.add(report_run)
            uow.record_events(report_run.pull_domain_events())
            await uow.commit()
            return report_run_to_dto(report_run)

    async def get_report_run_by_id(
        self, query: GetReportRunByIdQuery, *, uow: ReportingUnitOfWork
    ) -> ReportRunDTO:
        async with uow:
            report_run = await ensure_report_run_exists(
                uow, ReportId(query.report_run_id)
            )
            if str(report_run.requested_by) != query.requester_user_id:
                raise NotFoundError(f"ReportRun {query.report_run_id} not found.")
            return report_run_to_dto(report_run)

    async def list_report_runs(
        self, query: ListReportRunsQuery, *, uow: ReportingUnitOfWork
    ) -> list[ReportRunDTO]:
        """No approved HTTP route — see `queries.py`'s `ListReportRunsQuery` docstring. Filters
        client-side over `list_all()` rather than adding a new repository method, mirroring
        `notifications.events.subscribers`'s identical minimal-change choice for its own
        vehicle-scoped assignment filter."""
        async with uow:
            report_runs = await uow.report_runs.list_all()
            dtos = [report_run_to_dto(r) for r in report_runs]
            if query.status is not None:
                dtos = [dto for dto in dtos if dto.status == query.status]
            return dtos

    async def start_report(
        self, command: StartReportCommand, *, uow: ReportingUnitOfWork
    ) -> ReportRunDTO:
        """No approved HTTP route (`commands.py`'s own docstring)."""
        async with uow:
            report_run = await ensure_report_run_exists(
                uow, ReportId(command.report_run_id)
            )
            report_run.start(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(report_run.pull_domain_events())
            await uow.commit()
            return report_run_to_dto(report_run)

    async def mark_report_succeeded(
        self, command: MarkReportSucceededCommand, *, uow: ReportingUnitOfWork
    ) -> ReportRunDTO:
        """No approved HTTP route."""
        async with uow:
            report_run = await ensure_report_run_exists(
                uow, ReportId(command.report_run_id)
            )
            report_run.succeed(
                artifact_url=command.artifact_url,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(report_run.pull_domain_events())
            await uow.commit()
            return report_run_to_dto(report_run)

    async def mark_report_failed(
        self, command: MarkReportFailedCommand, *, uow: ReportingUnitOfWork
    ) -> ReportRunDTO:
        """No approved HTTP route."""
        async with uow:
            report_run = await ensure_report_run_exists(
                uow, ReportId(command.report_run_id)
            )
            report_run.fail(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(report_run.pull_domain_events())
            await uow.commit()
            return report_run_to_dto(report_run)
