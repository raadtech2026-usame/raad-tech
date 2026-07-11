"""Worker process bootstrap (Backend LLD §11.1: workers "can run in-process with the API at
the smallest scale and split into their own process as load grows — no redesign"). Entry
point: `python -m raad.interfaces.workers.bootstrap`.

Builds the *same* composition root as the HTTP app (`core.di.bootstrap.build_container`) —
there is no separate worker-only container, since both processes need identical bindings
(`Settings`, `Clock`, the DB engine/UnitOfWork when `db.url` is configured, etc.). Registers
only the foundation workers (Outbox Relay, Scheduler) with zero business jobs, and manages
their lifecycle with graceful shutdown on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import signal

from raad.core.config.settings import Settings, get_settings
from raad.core.di.bootstrap import build_container
from raad.core.di.container import Container
from raad.core.logging.setup import configure_logging, get_logger
from raad.core.time.clock import Clock
from raad.core.workers.health import WorkerHealthRegistry
from raad.core.workers.lifecycle import WorkerLifecycle
from raad.core.workers.scheduler import IntervalScheduler
from raad.interfaces.workers.outbox_relay import OutboxRelayWorker
from raad.interfaces.workers.scheduler import SchedulerWorker

logger = get_logger("raad.workers.bootstrap")


def build_worker_container(settings: Settings) -> Container:
    """Workers share the HTTP app's composition root — see module docstring."""
    return build_container(settings)


def create_lifecycle(
    container: Container, settings: Settings
) -> tuple[WorkerLifecycle, WorkerHealthRegistry]:
    clock = container.resolve(Clock)
    scheduler = IntervalScheduler(clock)  # no jobs registered — foundation only

    outbox_relay = OutboxRelayWorker(
        container, batch_size=settings.workers.outbox_relay_batch_size
    )
    scheduler_worker = SchedulerWorker(scheduler, clock)

    registry = WorkerHealthRegistry()
    registry.register(outbox_relay)
    registry.register(scheduler_worker)

    lifecycle = WorkerLifecycle(
        [
            (outbox_relay, settings.workers.outbox_relay_interval_seconds),
            (scheduler_worker, settings.workers.scheduler_tick_interval_seconds),
        ]
    )
    return lifecycle, registry


async def run_workers(settings: Settings, stop_event: asyncio.Event | None = None) -> None:
    container = build_worker_container(settings)
    lifecycle, registry = create_lifecycle(container, settings)

    stop_event = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows' default ProactorEventLoop doesn't support add_signal_handler; the
            # process still stops via KeyboardInterrupt/termination, just without this
            # graceful in-loop signal path.
            pass

    await lifecycle.start_all()
    logger.info("workers_started", extra={"workers": [h.name for h in registry.snapshot()]})
    await stop_event.wait()
    await lifecycle.stop_all()
    logger.info("workers_stopped")


def main() -> None:
    settings = get_settings()
    settings.validate_on_startup()
    configure_logging(settings.observability)
    asyncio.run(run_workers(settings))


if __name__ == "__main__":
    main()
