"""Background worker foundation (Backend LLD §11): a runtime-agnostic worker lifecycle, retry/
DLQ/idempotency abstractions, and a minimal in-process scheduler. No business jobs
(notification sending, billing, trip generation, JT808/JT1078) are implemented here — see
`interfaces/workers/` for the concrete foundation workers (Outbox Relay, Scheduler) and
`modules/*` for where business event handling will eventually live.
"""

from raad.core.workers.base import Worker
from raad.core.workers.dlq import DeadLetterQueue
from raad.core.workers.health import WorkerHealth, WorkerHealthRegistry
from raad.core.workers.idempotency import IdempotencyStore, InMemoryIdempotencyStore
from raad.core.workers.lifecycle import WorkerLifecycle
from raad.core.workers.logging import bind_worker_context, unbind_worker_context
from raad.core.workers.retry import ExponentialBackoffRetryPolicy, RetryPolicy
from raad.core.workers.scheduler import (
    IntervalScheduler,
    LockPort,
    ScheduledJob,
    Scheduler,
)

__all__ = [
    "DeadLetterQueue",
    "ExponentialBackoffRetryPolicy",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "IntervalScheduler",
    "LockPort",
    "RetryPolicy",
    "ScheduledJob",
    "Scheduler",
    "Worker",
    "WorkerHealth",
    "WorkerHealthRegistry",
    "WorkerLifecycle",
    "bind_worker_context",
    "unbind_worker_context",
]
