"""Worker process bootstrap (Backend LLD §11.1: workers "can run in-process with the API at
the smallest scale and split into their own process as load grows — no redesign"). Entry
point: `python -m raad.interfaces.workers.bootstrap`.

Builds the *same* composition root as the HTTP app (`core.di.bootstrap.build_container`) —
there is no separate worker-only container, since both processes need identical bindings
(`Settings`, `Clock`, the DB engine/UnitOfWork when `db.url` is configured, etc.). Manages every
worker's lifecycle with graceful shutdown on SIGINT/SIGTERM.

**Architecture Resolution (Backend Stabilization phase, Medium findings #6/#7 of the
pre-production review): "Notification/Report Workers are empty files"; "Scheduler has zero
registered jobs").** Notification Worker (`interfaces/workers/notification_worker.py`) and
Report Worker (`interfaces/workers/report_worker.py`) now have real implementations; three
scheduled jobs are registered below. The Notification Worker is only added to the lifecycle
when a `BrokerConsumer` is actually bound (ADR-0008, `RAAD_BROKER__URL` configured) — with no
broker, there is nothing for it to consume, the same "don't start a worker with nothing to do"
posture `OutboxRelayWorker` already tolerates via its own per-tick no-op instead (the difference
here being the Notification Worker's `consume()` call itself would fail loudly with
`LookupError` against an unbound `BrokerConsumer`, so it is left out of the lifecycle entirely
rather than ticking a guaranteed failure).

**Trip generation is deliberately not among the scheduled jobs registered here** — Backend LLD
§11.2 names "daily trip generation" as a Scheduler job, but no approved document (Database
Design in particular) gives any schedule/recurrence data model a `Trip` could be generated
*from* — `trips` are created one at a time via `POST /trips` (API Contracts §4.3), and inventing
a recurrence schema to drive automatic generation would be a new, undocumented business concept
this phase's "don't invent it" discipline forbids. Flagged as a real, unresolved gap for a
future phase that adds the missing schema, not silently omitted.
"""

from __future__ import annotations

import asyncio
import signal
from typing import Awaitable, Callable

from raad.core.config.settings import Settings, get_settings
from raad.core.di.bootstrap import build_container
from raad.core.di.container import Container
from raad.core.events.ports import BrokerConsumer
from raad.core.events.processor import EventProcessorRegistry
from raad.core.logging.setup import configure_logging, get_logger
from raad.core.time.clock import Clock
from raad.core.workers.base import Worker
from raad.core.workers.health import WorkerHealthRegistry
from raad.core.workers.lifecycle import WorkerLifecycle
from raad.core.workers.scheduler import IntervalScheduler, LockPort, ScheduledJob
from raad.interfaces.workers.notification_worker import NotificationWorker
from raad.interfaces.workers.outbox_relay import OutboxRelayWorker
from raad.interfaces.workers.report_worker import ReportWorker
from raad.interfaces.workers.scheduler import SchedulerWorker
from raad.modules.billing.application.ports import BillingUnitOfWork
from raad.modules.billing.application.services import BillingApplicationService
from raad.modules.tracking.application.ports import TrackingUnitOfWork
from raad.modules.tracking.application.services import TrackingApplicationService

logger = get_logger("raad.workers.bootstrap")


def build_worker_container(settings: Settings) -> Container:
    """Workers share the HTTP app's composition root — see module docstring."""
    return build_container(settings)


def _register_scheduled_jobs(
    scheduler: IntervalScheduler, container: Container, settings: Settings
) -> None:
    """Wraps each job body with the `LockPort` overlap guard (§11.3) whenever one is bound
    (ADR-0008) — jobs still run without one (no overlap protection), the same graceful
    degradation every other optional port in this codebase already has, since a single
    in-process worker (this phase's only deployment shape, per this file's own module
    docstring) cannot actually overlap with itself."""
    lock_port = container.try_resolve(LockPort)

    async def _with_lock(
        job_name: str, ttl_seconds: int, body: Callable[[], Awaitable[None]]
    ) -> None:
        if lock_port is None:
            await body()
            return
        lock_key = f"scheduler:lock:{job_name}"
        if not await lock_port.acquire(lock_key, ttl_seconds):
            logger.debug("scheduled_job_skipped_locked", extra={"job": job_name})
            return
        try:
            await body()
        finally:
            await lock_port.release(lock_key)

    async def prune_vehicle_positions() -> None:
        async def _body() -> None:
            service = container.resolve(TrackingApplicationService)
            deleted = await service.prune_position_history(
                settings.workers.vehicle_position_retention_days,
                uow=container.resolve(TrackingUnitOfWork),
            )
            if deleted:
                logger.info("vehicle_positions_pruned", extra={"count": deleted})

        await _with_lock(
            "prune_vehicle_positions",
            int(settings.workers.vehicle_position_retention_job_interval_seconds),
            _body,
        )

    async def sweep_expired_subscriptions() -> None:
        async def _body() -> None:
            service = container.resolve(BillingApplicationService)
            expired = await service.sweep_expired_subscriptions(
                uow=container.resolve(BillingUnitOfWork)
            )
            if expired:
                logger.info("subscriptions_expired", extra={"count": expired})

        await _with_lock(
            "sweep_expired_subscriptions",
            int(settings.workers.subscription_sweep_interval_seconds),
            _body,
        )

    async def reconcile_expired_payments() -> None:
        async def _body() -> None:
            service = container.resolve(BillingApplicationService)
            expired = await service.reconcile_expired_payments(
                timeout_minutes=settings.workers.payment_reconciliation_timeout_minutes,
                uow=container.resolve(BillingUnitOfWork),
            )
            if expired:
                logger.info("payments_reconciled_expired", extra={"count": expired})

        await _with_lock(
            "reconcile_expired_payments",
            int(settings.workers.payment_reconciliation_interval_seconds),
            _body,
        )

    scheduler.register(
        ScheduledJob(
            name="prune_vehicle_positions",
            interval_seconds=settings.workers.vehicle_position_retention_job_interval_seconds,
            handler=prune_vehicle_positions,
        )
    )
    scheduler.register(
        ScheduledJob(
            name="sweep_expired_subscriptions",
            interval_seconds=settings.workers.subscription_sweep_interval_seconds,
            handler=sweep_expired_subscriptions,
        )
    )
    scheduler.register(
        ScheduledJob(
            name="reconcile_expired_payments",
            interval_seconds=settings.workers.payment_reconciliation_interval_seconds,
            handler=reconcile_expired_payments,
        )
    )


def create_lifecycle(
    container: Container, settings: Settings
) -> tuple[WorkerLifecycle, WorkerHealthRegistry]:
    clock = container.resolve(Clock)
    scheduler = IntervalScheduler(clock)
    _register_scheduled_jobs(scheduler, container, settings)

    outbox_relay = OutboxRelayWorker(
        container, batch_size=settings.workers.outbox_relay_batch_size
    )
    scheduler_worker = SchedulerWorker(scheduler, clock)
    report_worker = ReportWorker(container)

    registry = WorkerHealthRegistry()
    registry.register(outbox_relay)
    registry.register(scheduler_worker)
    registry.register(report_worker)

    workers: list[tuple[Worker, float]] = [
        (outbox_relay, settings.workers.outbox_relay_interval_seconds),
        (scheduler_worker, settings.workers.scheduler_tick_interval_seconds),
        (report_worker, settings.workers.report_worker_interval_seconds),
    ]

    broker_consumer = container.try_resolve(BrokerConsumer)
    if broker_consumer is not None:
        notification_worker = NotificationWorker(
            clock=clock,
            consumer=broker_consumer,
            registry=container.resolve(EventProcessorRegistry),
        )
        registry.register(notification_worker)
        workers.append(
            (notification_worker, settings.workers.notification_worker_interval_seconds)
        )
    else:
        logger.info(
            "notification_worker_not_started",
            extra={"reason": "no BrokerConsumer bound (RAAD_BROKER__URL not configured)"},
        )

    lifecycle = WorkerLifecycle(workers)
    return lifecycle, registry


async def run_workers(
    settings: Settings, stop_event: asyncio.Event | None = None
) -> None:
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
    logger.info(
        "workers_started", extra={"workers": [h.name for h in registry.snapshot()]}
    )
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
