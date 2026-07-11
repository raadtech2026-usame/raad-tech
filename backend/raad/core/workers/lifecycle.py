"""Worker lifecycle management (Backend LLD §11.1): starts/stops a collection of `Worker`
instances together as one unit, whether they end up running in-process with the API or as a
separate worker process — the same `WorkerLifecycle` works either way.
"""

from __future__ import annotations

from typing import Sequence

from raad.core.workers.base import Worker
from raad.core.workers.health import WorkerHealth


class WorkerLifecycle:
    def __init__(self, workers: Sequence[tuple[Worker, float]]) -> None:
        """`workers` is a sequence of `(worker, poll_interval_seconds)` pairs."""
        self._workers = list(workers)

    async def start_all(self) -> None:
        for worker, interval_seconds in self._workers:
            await worker.start(interval_seconds)

    async def stop_all(self) -> None:
        for worker, _ in self._workers:
            await worker.stop()

    def health_snapshot(self) -> list[WorkerHealth]:
        return [worker.health() for worker, _ in self._workers]
