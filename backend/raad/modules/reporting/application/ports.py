"""Outbound ports the `reporting` application layer depends on (Backend LLD §4.2). `UnitOfWork`
is the existing core abstraction (`core.db.unit_of_work`), extended here with `reporting`'s own
repository, mirroring `billing.application.ports.BillingUnitOfWork`'s exact shape.

**No report-rendering port is defined here.** The task's own Out of Scope section explicitly
forbids PDF/Excel generation, BI dashboards, scheduled reports, and an analytics engine this
phase — persistence only. No approved document names a rendering port interface for this module
either (unlike `billing.application.ports.PaymentProviderPort`, which LLD §4.2 names verbatim),
so none is declared even as an unbound interface — mirrors `notifications.application.ports`'s
identical "inventing one would be scope creep beyond what was asked" reasoning.
"""

from __future__ import annotations

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.reporting.domain.repositories import ReportRunRepository


class ReportingUnitOfWork(UnitOfWork):
    """Bundles this module's one repository onto the transaction boundary, mirroring
    `TransportOpsUnitOfWork`/`BillingUnitOfWork`/`NotificationsUnitOfWork`'s identical shape.
    The concrete implementation is `infra.repositories.SqlAlchemyReportingUnitOfWork`.
    """

    report_runs: ReportRunRepository
