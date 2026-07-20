"""Repository interface for the `reporting` module (Backend LLD §5.1/§7.1/§7.2). Framework-free
— no SQLAlchemy/FastAPI/Pydantic. No LLD-given contract skeleton exists (unlike
`TripRepository`) — mirrors the closest already-completed precedent, `billing.domain.
repositories.TransportFeeRepository` (a single, undocumented-route aggregate with the minimal
`get`/`add`/`list_all` shape).

No dedicated finder beyond `get`/`add`/`list_all` — Database Design §8.6 documents no unique
constraint on `report_runs` (unlike `payments.idempotency_key`/`invoices.number`), so no
`get_by_*` defense-in-depth method is warranted here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.modules.reporting.domain.entities import ReportRun
from raad.modules.reporting.domain.value_objects import ReportId


class ReportRunRepository(ABC):
    @abstractmethod
    async def get(self, report_run_id: ReportId) -> ReportRun | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, report_run: ReportRun) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[ReportRun]:
        """Uniform-shape method every repository in this codebase provides — no `GET
        /reports/runs` (list) route is documented (API Contracts §4.8 gives only the two rows
        `POST /reports/runs`/`GET /reports/runs/{id}`), so nothing calls this yet."""
        raise NotImplementedError
