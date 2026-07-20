"""Outbound ports the `reporting` application layer depends on (Backend LLD §4.2). `UnitOfWork`
is the existing core abstraction (`core.db.unit_of_work`), extended here with `reporting`'s own
repository, mirroring `billing.application.ports.BillingUnitOfWork`'s exact shape.

**`ReportRendererPort` — added under the Backend Stabilization phase, reversing this file's own
earlier "no report-rendering port" stance.** The earlier phase's exclusion was scoped to actual
PDF/Excel *generation* (still true, still out of scope — no concrete renderer exists, see
`infra/adapters.py`); the *abstraction* itself is exactly what this phase's own explicit
authorization for a "Report Worker" calls for, mirroring `billing.application.ports.
PaymentProviderPort`/`video.application.ports.VideoProviderPort`'s identical "define the
interface, leave the concrete adapter unbound" precedent. `render()`'s signature is derived from
the one fact every one of `ReportRun`'s three documented fields already gives it a use for
(`type`/`params`/`organization_id` are the render inputs; `artifact_url` — Phase-2 §10.1's object
store — is the return value `ReportRun.succeed()` already expects, Database Design §8.6).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from raad.core.db.unit_of_work import UnitOfWork
from raad.modules.reporting.domain.repositories import ReportRunRepository


class ReportRendererPort(ABC):
    """MVP abstraction over whatever actually produces a report artifact (PDF/Excel rendering
    engine, Phase-2 §11.2's "Report Worker" job) — no concrete implementation exists this phase,
    the same "fail loudly, don't fake" doctrine `PaymentProviderPort`/`VideoProviderPort` already
    establish."""

    @abstractmethod
    async def render(
        self,
        *,
        report_run_id: str,
        type: str,
        params: dict[str, Any] | None,
        organization_id: str,
    ) -> str:
        """Renders the report and returns its artifact URL (object store, Phase-2 §10.1)."""
        raise NotImplementedError


class ReportingUnitOfWork(UnitOfWork):
    """Bundles this module's one repository onto the transaction boundary, mirroring
    `TransportOpsUnitOfWork`/`BillingUnitOfWork`/`NotificationsUnitOfWork`'s identical shape.
    The concrete implementation is `infra.repositories.SqlAlchemyReportingUnitOfWork`.
    """

    report_runs: ReportRunRepository
