"""Scheduler foundation (Backend LLD §11.2 "Scheduler" worker row: "Cron ticks", "Each job
keyed by date/window; re-run yields same result"). No business jobs (trip generation,
subscription-status sweeps, retention/pruning, payment reconciliation) are registered here —
those belong to `transport_ops`/`billing`/`reporting` in later phases. `IntervalScheduler` is
a minimal polling scheduler (no cron-expression parser, no external dependency) that a worker
ticks repeatedly; `LockPort` is the overlap-guard interface `§11.3` calls for ("guarded
against overlap — a run-lock in Redis") — interface only, since Redis isn't an approved
dependency for this phase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

from raad.core.time.clock import Clock


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    interval_seconds: float
    handler: Callable[[], Awaitable[None]]


class Scheduler(ABC):
    @abstractmethod
    def register(self, job: ScheduledJob) -> None:
        raise NotImplementedError

    @abstractmethod
    async def run_pending(self) -> None:
        """Runs every registered job whose interval has elapsed since its last run. Intended
        to be called on every tick of a `SchedulerWorker` (`interfaces/workers/scheduler.py`).
        """
        raise NotImplementedError


class IntervalScheduler(Scheduler):
    """Runs each job once its own `interval_seconds` has elapsed since it last ran, checked on
    every `run_pending()` call. Deliberately simple — no cron expressions, no distributed
    overlap guard (`LockPort`, below, is the seam for that once Redis is wired)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._jobs: list[ScheduledJob] = []
        self._last_run: dict[str, datetime] = {}

    def register(self, job: ScheduledJob) -> None:
        self._jobs.append(job)

    async def run_pending(self) -> None:
        now = self._clock.now()
        for job in self._jobs:
            last_run = self._last_run.get(job.name)
            elapsed = (now - last_run).total_seconds() if last_run is not None else None
            if elapsed is None or elapsed >= job.interval_seconds:
                self._last_run[job.name] = now
                await job.handler()


class LockPort(ABC):
    """Overlap guard for scheduler jobs (§11.3: "scheduler jobs are guarded against overlap —
    a run-lock in Redis"). Interface only in this phase — no Redis client is wired yet.
    """

    @abstractmethod
    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        """Returns `True` if the lock was acquired, `False` if another holder already has
        it."""
        raise NotImplementedError

    @abstractmethod
    async def release(self, key: str) -> None:
        raise NotImplementedError
