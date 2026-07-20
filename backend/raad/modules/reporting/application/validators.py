"""Cross-cutting application-layer validators for `reporting` (Backend LLD §15.2: "application
layer validates cross-aggregate/business rules"), mirroring `billing.application.validators`'s
exact shape and existence-check pattern (new file, no scaffold existed, matching `billing`'s own
Phase 15 precedent).
"""

from __future__ import annotations

from raad.core.errors.exceptions import NotFoundError
from raad.modules.reporting.application.ports import ReportingUnitOfWork
from raad.modules.reporting.domain.entities import ReportRun
from raad.modules.reporting.domain.value_objects import ReportId


async def ensure_report_run_exists(
    uow: ReportingUnitOfWork, report_run_id: ReportId
) -> ReportRun:
    report_run = await uow.report_runs.get(report_run_id)
    if report_run is None:
        raise NotFoundError(f"ReportRun {report_run_id} not found.")
    return report_run
