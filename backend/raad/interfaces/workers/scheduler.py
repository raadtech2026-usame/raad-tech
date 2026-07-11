"""Scheduler worker (Backend LLD §11.2 "Scheduler" row: "Cron ticks" trigger). Foundation
only — ticks a `Scheduler` (`core/workers/scheduler.py`) and runs whatever jobs are
registered. No business jobs (trip generation, subscription-status sweeps, retention/pruning,
payment reconciliation) are registered here; those are `transport_ops`/`billing`/`reporting`
business logic added in a later phase once those modules exist.
"""

from __future__ import annotations

from raad.core.time.clock import Clock
from raad.core.workers.base import Worker
from raad.core.workers.scheduler import Scheduler


class SchedulerWorker(Worker):
    def __init__(self, scheduler: Scheduler, clock: Clock) -> None:
        super().__init__("scheduler", clock)
        self._scheduler = scheduler

    async def run_once(self) -> None:
        await self._scheduler.run_pending()
