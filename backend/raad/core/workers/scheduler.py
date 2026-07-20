"""Scheduler foundation (Backend LLD §11.2 "Scheduler" worker row: "Cron ticks", "Each job
keyed by date/window; re-run yields same result"). `IntervalScheduler` is a minimal polling
scheduler (no cron-expression parser, no external dependency) that a worker ticks repeatedly;
`LockPort` is the overlap-guard interface §11.3 calls for ("guarded against overlap — a run-lock
in Redis") — `RedisLockPort` (Backend Stabilization phase, ADR-0008) is its concrete
implementation, now that Redis is an approved dependency. Business jobs (retention/pruning,
subscription-status sweeps, payment reconciliation) are registered by `interfaces/workers/
bootstrap.py`, not here — this module stays domain-agnostic scheduling machinery only. Trip
generation is deliberately not among them — see `bootstrap.py`'s own docstring for why.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

from redis.asyncio import Redis

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
    a run-lock in Redis")."""

    @abstractmethod
    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        """Returns `True` if the lock was acquired, `False` if another holder already has
        it."""
        raise NotImplementedError

    @abstractmethod
    async def release(self, key: str) -> None:
        raise NotImplementedError


class RedisLockPort(LockPort):
    """`SET key value NX EX ttl_seconds` for `acquire` (atomic: fails if the key already
    exists, i.e. another holder has the lock); plain `DEL` for `release` — the exact primitive
    §11.3 names. A fixed sentinel value is used since this codebase's scheduler jobs never need
    to verify *which* holder owns a lock, only whether one exists (no compare-and-delete
    "only release if I'm still the holder" requirement is documented)."""

    _LOCK_VALUE = "1"

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        acquired = await self._redis.set(key, self._LOCK_VALUE, nx=True, ex=ttl_seconds)
        return bool(acquired)

    async def release(self, key: str) -> None:
        await self._redis.delete(key)
