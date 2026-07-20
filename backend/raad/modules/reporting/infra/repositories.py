"""SQLAlchemy repository implementation for `reporting` (Backend LLD §7.1/§7.2; Database
Design §8.6). Composes `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM ↔ domain conversion goes through `mappers.py` (§7.1's "aggregate-in/
aggregate-out" rule). Mirrors `billing.infra.repositories`'s identity-map/
`flush_tracked_changes` pattern exactly.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.reporting.application.ports import ReportingUnitOfWork
from raad.modules.reporting.domain.entities import ReportRun
from raad.modules.reporting.domain.repositories import ReportRunRepository
from raad.modules.reporting.domain.value_objects import ReportId
from raad.modules.reporting.infra.mappers import model_to_report_run, report_run_to_model
from raad.modules.reporting.infra.models import ReportRunModel


class SqlAlchemyReportRunRepository(
    SqlAlchemyRepositoryBase[ReportRunModel], ReportRunRepository
):
    model = ReportRunModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[ReportRun, ReportRunModel]] = {}

    async def get(self, report_run_id: ReportId) -> ReportRun | None:
        row = await self.get_by_id(str(report_run_id))
        return self._track(row)

    def add(self, report_run: ReportRun) -> None:
        model = report_run_to_model(report_run)
        super().add(model)
        self._tracked[str(report_run.id)] = (report_run, model)

    async def list_all(self) -> list[ReportRun]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_report_run(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for report_run, model in self._tracked.values():
            report_run_to_model(report_run, existing=model)

    def _track(self, row: ReportRunModel | None) -> ReportRun | None:
        if row is None:
            return None
        report_run = model_to_report_run(row)
        self._tracked[row.id] = (report_run, row)
        return report_run


class SqlAlchemyReportingUnitOfWork(SqlAlchemyUnitOfWork, ReportingUnitOfWork):
    """Concrete `ReportingUnitOfWork` (Backend LLD §8.2/§6.2). Constructs `reporting`'s one
    repository once the session is open, and re-syncs the tracked aggregate's in-place
    mutations onto its ORM row immediately before delegating to `SqlAlchemyUnitOfWork.commit()`
    — identical shape to `billing.infra.repositories.SqlAlchemyBillingUnitOfWork`.
    """

    report_runs: SqlAlchemyReportRunRepository

    async def __aenter__(self) -> "SqlAlchemyReportingUnitOfWork":
        await super().__aenter__()
        self.report_runs = SqlAlchemyReportRunRepository(self.session)
        return self

    async def commit(self) -> None:
        self.report_runs.flush_tracked_changes()
        await super().commit()
