"""Worker framework foundation (Backend LLD §11.1): a runtime-agnostic background worker
lifecycle. "Workers are stateless consumers... can run in-process with the API at the
smallest scale and split into their own processes as load grows — no redesign." This base
class is that stable shape: concrete workers (`OutboxRelayWorker`, `SchedulerWorker`) only
implement `run_once()`; polling, start/stop, and health tracking are identical for all of
them and don't depend on which worker *runtime* (Celery, arq — Backend LLD §20.1, still an
open item) eventually hosts them.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime

from raad.core.logging.setup import get_logger
from raad.core.time.clock import Clock
from raad.core.workers.health import WorkerHealth

logger = get_logger("raad.workers")


class Worker(ABC):
    """One instance per logical worker (Outbox Relay, Scheduler, ...). `start`/`stop` are
    idempotent-safe: calling `start` while already running is a no-op, and `stop` awaits the
    in-flight tick before returning so shutdown never leaves a task dangling."""

    def __init__(self, name: str, clock: Clock) -> None:
        self.name = name
        self._clock = clock
        self._stop_event: asyncio.Event | None = None
        self._task: "asyncio.Task[None] | None" = None
        self._last_run_at: datetime | None = None
        self._last_error: str | None = None

    @abstractmethod
    async def run_once(self) -> None:
        """One iteration of this worker's work. Exceptions are caught by the polling loop
        (`_tick`) and recorded as `last_error` — a single bad tick never kills the worker.
        """
        raise NotImplementedError

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def health(self) -> WorkerHealth:
        return WorkerHealth(
            name=self.name,
            is_running=self.is_running,
            last_run_at=self._last_run_at,
            last_error=self._last_error,
        )

    async def _tick(self) -> None:
        try:
            await self.run_once()
            self._last_error = None
        except (
            Exception
        ) as exc:  # noqa: BLE001 - a worker tick must never kill the loop
            self._last_error = str(exc)
            logger.exception("worker_tick_failed", extra={"worker": self.name})
        finally:
            self._last_run_at = self._clock.now()

    async def _run_forever(self, interval_seconds: float) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            await self._tick()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def start(self, interval_seconds: float) -> None:
        if self.is_running:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run_forever(interval_seconds), name=self.name
        )

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None
