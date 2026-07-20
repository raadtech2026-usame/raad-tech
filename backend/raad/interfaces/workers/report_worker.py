"""Report Worker (Backend LLD §11.2's "Report Worker" row: "background jobs (report
rendering)"). Foundation + real, tested control flow: each tick finds every `queued`
`ReportRun`, marks it `running`, attempts to render it via `ReportRendererPort` (deliberately
unbound this phase — see `reporting/infra/adapters.py`'s own docstring), and marks the run
`succeeded`/`failed` accordingly. **No `ReportRendererPort` is bound this phase**, so every run
this worker picks up ends `failed` with a clear reason — the same "fail loudly per unit of work,
don't fake a render, don't crash the worker" posture `OutboxRelayWorker`'s own "no publisher
bound -> documented no-op" already establishes for its own optional dependency, adapted here to
"no renderer bound -> documented failure" since a `ReportRun` has already been durably queued
and must resolve to a terminal status rather than silently sit unfinished.

**`SYSTEM_PRINCIPAL` — the identical, independently-flagged gap `modules/notifications/events/
subscribers.py`'s own module docstring already documents for the Notification Worker.** No
`SYSTEM`/worker `Role` exists in this codebase; duplicated here rather than shared, matching
this codebase's own "duplicate per module/worker rather than a shared-kernel dependency for a
small constant" convention (`_AggregateRoot` is the running precedent).
"""

from __future__ import annotations

from raad.core.di.container import Container
from raad.core.logging.setup import get_logger
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.core.workers.base import Worker
from raad.modules.reporting.application.commands import (
    MarkReportFailedCommand,
    MarkReportSucceededCommand,
    StartReportCommand,
)
from raad.modules.reporting.application.ports import ReportingUnitOfWork, ReportRendererPort
from raad.modules.reporting.application.queries import ListReportRunsQuery
from raad.modules.reporting.application.services import ReportingApplicationService

logger = get_logger("raad.workers.report")

SYSTEM_PRINCIPAL = Principal(user_id="system", role=Role.FOUNDER, org_id=None)


class ReportWorker(Worker):
    def __init__(self, container: Container) -> None:
        super().__init__("report", container.resolve(Clock))
        self._container = container

    async def run_once(self) -> None:
        service = self._container.resolve(ReportingApplicationService)
        queued = await service.list_report_runs(
            ListReportRunsQuery(status="queued"),
            uow=self._container.resolve(ReportingUnitOfWork),
        )
        for report_run in queued:
            await self._process(report_run.id, report_run.type, report_run.params,
                                 report_run.organization_id)

    async def _process(
        self, report_run_id: str, type: str, params: dict | None, organization_id: str
    ) -> None:
        service = self._container.resolve(ReportingApplicationService)
        await service.start_report(
            StartReportCommand(report_run_id=report_run_id, actor=SYSTEM_PRINCIPAL),
            uow=self._container.resolve(ReportingUnitOfWork),
        )

        renderer = self._container.try_resolve(ReportRendererPort)
        if renderer is None:
            logger.warning(
                "report_run_failed_no_renderer_bound",
                extra={"report_run_id": report_run_id},
            )
            await service.mark_report_failed(
                MarkReportFailedCommand(
                    report_run_id=report_run_id, actor=SYSTEM_PRINCIPAL
                ),
                uow=self._container.resolve(ReportingUnitOfWork),
            )
            return

        try:
            artifact_url = await renderer.render(
                report_run_id=report_run_id,
                type=type,
                params=params,
                organization_id=organization_id,
            )
        except Exception:  # noqa: BLE001 - a render failure must not crash the tick
            logger.exception(
                "report_run_render_failed", extra={"report_run_id": report_run_id}
            )
            await service.mark_report_failed(
                MarkReportFailedCommand(
                    report_run_id=report_run_id, actor=SYSTEM_PRINCIPAL
                ),
                uow=self._container.resolve(ReportingUnitOfWork),
            )
            return

        await service.mark_report_succeeded(
            MarkReportSucceededCommand(
                report_run_id=report_run_id,
                artifact_url=artifact_url,
                actor=SYSTEM_PRINCIPAL,
            ),
            uow=self._container.resolve(ReportingUnitOfWork),
        )
