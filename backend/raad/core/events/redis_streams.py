"""Redis Streams broker adapters (ADR-0008; Backend LLD §10, §11.3). `RedisStreamsBrokerPort`
(producer, `XADD`) and `RedisStreamsBrokerConsumer` (consumer, `XREADGROUP`/`XACK`/`XAUTOCLAIM`)
are the concrete `BrokerPort`/`BrokerConsumer` this codebase picked at MVP — see the ADR for the
full Redis-Streams-vs-RabbitMQ reasoning. Lives in `core/events/`, not any bounded-context
module — the same shared-kernel placement `core.events.outbox` already establishes for the
identical "every module needs this" shape.

One shared stream (`raad:events` by default) carries every published `DomainEvent`, JSON-encoded
under a single `data` field (mirrors `outbox.payload_json`'s own JSON-blob storage, rather than
exploding each `DomainEvent` field into a separate Redis Streams field) — `core.events.processor.
EventProcessorRegistry` is what fans a single inbound stream out to per-`event_type` handlers,
so no per-type Redis stream is needed (ADR-0008's own "no per-event-type topic" decision).

**Retry/DLQ uses Redis's own native per-message delivery-count tracking (`XPENDING`), not a
second, hand-rolled counter store.** A message that a handler raises on is left unacknowledged;
`XAUTOCLAIM` (called at the start of every `consume()`) reclaims messages that have been pending
longer than `min_idle_time_ms`, and Redis's own `times-delivered` count (returned by `XPENDING`)
is compared against the injected `RetryPolicy` — once exhausted, the message is routed to the
`DeadLetterQueue` and acknowledged (removing it from the pending list; the DLQ, not the stream's
pending-entries list, is now its system of record), matching LLD §11.3's documented shape
exactly ("Retry with backoff, bounded attempts, then dead-letter queue + alert").
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from redis.asyncio import Redis

from raad.core.events.base import DomainEvent
from raad.core.events.ports import BrokerConsumer, BrokerPort
from raad.core.logging.setup import get_logger
from raad.core.workers.dlq import DeadLetterQueue
from raad.core.workers.retry import RetryPolicy

logger = get_logger("raad.events.redis_streams")

DEFAULT_STREAM_NAME = "raad:events"


def _event_to_fields(event: DomainEvent) -> dict[str, str]:
    return {
        "data": json.dumps(
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "version": event.version,
                "occurred_at": event.occurred_at.isoformat(),
                "org_id": event.org_id,
                "correlation_id": event.correlation_id,
                "payload": event.payload,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": event.aggregate_id,
            }
        )
    }


def _fields_to_event(fields: dict[str, str]) -> DomainEvent:
    data = json.loads(fields["data"])
    return DomainEvent(
        event_id=data["event_id"],
        event_type=data["event_type"],
        version=data["version"],
        occurred_at=datetime.fromisoformat(data["occurred_at"]),
        org_id=data["org_id"],
        correlation_id=data["correlation_id"],
        payload=data["payload"],
        aggregate_type=data["aggregate_type"],
        aggregate_id=data["aggregate_id"],
    )


class RedisStreamsBrokerPort(BrokerPort):
    def __init__(self, redis_client: Redis, *, stream_name: str = DEFAULT_STREAM_NAME) -> None:
        self._redis = redis_client
        self._stream_name = stream_name

    async def publish(self, event: DomainEvent) -> None:
        await self._redis.xadd(self._stream_name, _event_to_fields(event))


class RedisStreamsBrokerConsumer(BrokerConsumer):
    """One instance per logical worker/consumer group (e.g. the Notification Worker) — `group_name`
    is that worker's own durable consumer group; `consumer_name` disambiguates multiple replicas
    of the same worker (defaults to a fixed name, since this codebase runs one worker process per
    logical worker today, Backend LLD §11.1's "in-process... no redesign" posture)."""

    def __init__(
        self,
        redis_client: Redis,
        *,
        group_name: str,
        retry_policy: RetryPolicy,
        dead_letter_queue: DeadLetterQueue,
        stream_name: str = DEFAULT_STREAM_NAME,
        consumer_name: str = "worker-1",
        batch_size: int = 10,
        block_ms: int = 1000,
        min_idle_time_ms: int = 30_000,
    ) -> None:
        self._redis = redis_client
        self._stream_name = stream_name
        self._group_name = group_name
        self._consumer_name = consumer_name
        self._retry_policy = retry_policy
        self._dead_letter_queue = dead_letter_queue
        self._batch_size = batch_size
        self._block_ms = block_ms
        self._min_idle_time_ms = min_idle_time_ms
        self._group_ready = False

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            await self._redis.xgroup_create(
                self._stream_name, self._group_name, id="0", mkstream=True
            )
        except Exception as exc:  # noqa: BLE001 - redis-py raises a generic ResponseError
            if "BUSYGROUP" not in str(exc):
                raise
        self._group_ready = True

    async def consume(self, handler: Callable[[DomainEvent], Awaitable[None]]) -> None:
        """One pass: reclaims stale-pending messages, reads new ones, and processes both —
        called once per `Worker` tick (`interfaces/workers/notification_worker.py`), not a
        blocking loop, matching this codebase's existing poll-on-an-interval `Worker` model
        (`core.workers.base.Worker`) rather than a separately-managed long-lived task."""
        await self._ensure_group()

        reclaimed = await self._reclaim_stale_pending()
        for message_id, fields in reclaimed:
            await self._process_one(message_id, fields, handler)

        response = await self._redis.xreadgroup(
            self._group_name,
            self._consumer_name,
            {self._stream_name: ">"},
            count=self._batch_size,
            block=self._block_ms,
        )
        for _stream_name, messages in response or []:
            for message_id, fields in messages:
                await self._process_one(message_id, fields, handler)

    async def _reclaim_stale_pending(self) -> list[tuple[str, dict[str, str]]]:
        # `XAUTOCLAIM` replies `[cursor, claimed, deleted]` on Redis >=7.0 but only `[cursor,
        # claimed]` on older servers (no third element) — unpacked defensively by position
        # rather than assuming a fixed arity, since this codebase cannot integration-test
        # against a real Redis server this phase (no instance reachable in this sandbox).
        response = await self._redis.xautoclaim(
            self._stream_name,
            self._group_name,
            self._consumer_name,
            min_idle_time=self._min_idle_time_ms,
            start_id="0",
            count=self._batch_size,
        )
        return response[1] if len(response) > 1 else []

    async def _process_one(
        self,
        message_id: str,
        fields: dict[str, str],
        handler: Callable[[DomainEvent], Awaitable[None]],
    ) -> None:
        event = _fields_to_event(fields)
        try:
            await handler(event)
        except Exception as exc:  # noqa: BLE001 - a handler failure must never crash consume()
            await self._handle_failure(message_id, event, exc)
            return
        await self._redis.xack(self._stream_name, self._group_name, message_id)

    async def _handle_failure(
        self, message_id: str, event: DomainEvent, exc: Exception
    ) -> None:
        attempts = await self._delivery_count(message_id)
        if self._retry_policy.next_delay(attempts) is None:
            await self._dead_letter_queue.send(
                event=event, error=str(exc), attempts=attempts
            )
            await self._redis.xack(self._stream_name, self._group_name, message_id)
            logger.error(
                "event_dead_lettered",
                extra={"event_id": event.event_id, "event_type": event.event_type},
            )
        else:
            logger.warning(
                "event_processing_failed_will_retry",
                extra={
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "attempts": attempts,
                },
            )

    async def _delivery_count(self, message_id: str) -> int:
        entries = await self._redis.xpending_range(
            self._stream_name, self._group_name, min=message_id, max=message_id, count=1
        )
        if not entries:
            return 1
        return int(entries[0]["times_delivered"])


class RedisDeadLetterQueue(DeadLetterQueue):
    """`raad:events:dlq` (ADR-0008) — a second, ordinary Redis Stream, not a consumer-group
    target. Bounded attempts having already been exhausted (§11.3), nothing consumes this
    automatically this phase; it exists so failed events are inspectable/replayable rather than
    silently lost, and to make the "+ alert" half of §11.3 attachable later without a shape
    change."""

    def __init__(
        self, redis_client: Redis, *, stream_name: str = "raad:events:dlq"
    ) -> None:
        self._redis = redis_client
        self._stream_name = stream_name

    async def send(self, *, event: DomainEvent, error: str, attempts: int) -> None:
        fields = _event_to_fields(event)
        fields["error"] = error
        fields["attempts"] = str(attempts)
        fields["failed_at"] = datetime.now(timezone.utc).isoformat()
        await self._redis.xadd(self._stream_name, fields)
