"""Worker health checks (Backend LLD §11). A `WorkerHealth` snapshot is cheap, in-memory
introspection of a running worker — not a business feature, and not yet exposed on any HTTP
route (the existing `/health/*` probes, `interfaces/http/health.py`, are process-level; wiring
worker health into them is left for whenever a worker actually runs in-process with the API).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from raad.core.workers.base import Worker


@dataclass(frozen=True)
class WorkerHealth:
    name: str
    is_running: bool
    last_run_at: datetime | None
    last_error: str | None


class WorkerHealthRegistry:
    """Collects `Worker` instances so their health can be queried together — e.g. by a future
    `/health/workers` probe or a worker-process CLI command."""

    def __init__(self) -> None:
        self._workers: list["Worker"] = []

    def register(self, worker: "Worker") -> None:
        self._workers.append(worker)

    def snapshot(self) -> list[WorkerHealth]:
        return [worker.health() for worker in self._workers]
