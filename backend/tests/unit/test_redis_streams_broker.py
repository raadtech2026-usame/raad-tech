"""Unit tests for `core.events.redis_streams` (ADR-0008: Redis Streams broker). Stdlib
`unittest` — no `pytest` (not an approved dependency). A minimal in-memory fake standing in for
`redis.asyncio.Redis`'s stream/lock commands (`xadd`, `xreadgroup`, `xack`, `xautoclaim`,
`xpending_range`, `xgroup_create`, `set`, `delete`) — no real Redis connection, mirroring every
other fake-external-port test in this suite.

Covers: publish/consume round trip, retry-then-DLQ on repeated handler failure (using Redis's
own native per-message delivery-count via `XPENDING`, not a second counter store — `core/events/
redis_streams.py`'s own module docstring), successful processing acknowledges and removes the
message from pending, and `RedisLockPort` acquire/release/contention.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from raad.core.events.base import DomainEvent
from raad.core.events.redis_streams import (
    RedisDeadLetterQueue,
    RedisStreamsBrokerConsumer,
    RedisStreamsBrokerPort,
)
from raad.core.workers.dlq import DeadLetterQueue
from raad.core.workers.retry import RetryPolicy
from raad.core.workers.scheduler import RedisLockPort


def make_event(event_type: str = "TripStarted", event_id: str = "evt-1") -> DomainEvent:
    return DomainEvent(
        event_id=event_id,
        event_type=event_type,
        version=1,
        occurred_at=datetime(2026, 7, 21, 8, 0, 0, tzinfo=timezone.utc),
        org_id="01J8Z3K9G6X8YV5T4N2R7QW3MD",
        correlation_id=None,
        payload={"vehicle_id": "veh-1", "actor_id": None},
        aggregate_type="Trip",
        aggregate_id="01J8Z3K9G6X8YV5T4N2R7QW3TR",
    )


class FakeRedisStream:
    """A minimal, single-consumer-group fake of the Redis Streams commands this module's two
    classes actually call. Message ids are monotonically increasing integers rendered as
    strings, matching Redis's own `<ms>-<seq>` shape closely enough for these tests (exact
    id format is never asserted on)."""

    def __init__(self) -> None:
        self._next_id = 1
        self.entries: dict[str, dict[str, str]] = {}
        self.groups: set[tuple[str, str]] = set()
        self.pending: dict[str, dict[str, object]] = {}
        # Real Redis Streams tracks a per-group "last delivered id" cursor: once a message has
        # been handed out via `XREADGROUP ... >` at least once, it is never handed out via `>`
        # again (ack or not) - only `XAUTOCLAIM` can redeliver it. Tracked explicitly here so
        # this fake doesn't (incorrectly) treat "acked, no longer pending" as "never delivered."
        self._ever_delivered: set[str] = set()
        self.acked: list[str] = []
        self.locks: dict[str, str] = {}

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = False,
    ) -> str:
        # `maxlen`/`approximate` mirror redis-py's own `XADD` kwargs (stream-trimming fix,
        # 2026-09-02). Recorded so a test can assert they are passed through, and applied
        # (exactly, not approximately - a fake has no node structure to round to) so a test can
        # assert the stream is genuinely bounded.
        self.last_xadd_kwargs = {"maxlen": maxlen, "approximate": approximate}
        message_id = str(self._next_id)
        self._next_id += 1
        self.entries[message_id] = fields
        if maxlen is not None and maxlen > 0:
            while len(self.entries) > maxlen:
                self.entries.pop(next(iter(self.entries)))
        return message_id

    async def xgroup_create(self, name: str, groupname: str, id: str, mkstream: bool) -> None:
        key = (name, groupname)
        if key in self.groups:
            raise Exception("BUSYGROUP Consumer Group name already exists")
        self.groups.add(key)

    async def xreadgroup(
        self, groupname: str, consumername: str, streams: dict[str, str], count: int, block: int
    ):
        (stream_name, _cursor) = next(iter(streams.items()))
        undelivered = [
            (mid, fields)
            for mid, fields in self.entries.items()
            if mid not in self._ever_delivered
        ][:count]
        for mid, _fields in undelivered:
            self.pending[mid] = {"consumer": consumername, "times_delivered": 1}
            self._ever_delivered.add(mid)
        if not undelivered:
            return []
        return [(stream_name, undelivered)]

    async def xack(self, name: str, groupname: str, message_id: str) -> None:
        self.acked.append(message_id)
        self.pending.pop(message_id, None)

    async def xautoclaim(
        self, name: str, groupname: str, consumername: str, min_idle_time: int, start_id: str,
        count: int,
    ):
        # Tests drive reclaiming explicitly via `force_reclaimable`; by default nothing is
        # stale enough to reclaim.
        claimable = [
            (mid, self.entries[mid])
            for mid, meta in self.pending.items()
            if meta.get("reclaimable")
        ][:count]
        for mid, _fields in claimable:
            self.pending[mid]["times_delivered"] += 1
        return ["0-0", claimable, []]

    async def xpending_range(
        self, name: str, groupname: str, min: str, max: str, count: int
    ) -> list[dict[str, object]]:
        meta = self.pending.get(min)
        if meta is None:
            return []
        return [{"message_id": min, "times_delivered": meta["times_delivered"]}]

    def force_reclaimable(self, message_id: str) -> None:
        self.pending[message_id]["reclaimable"] = True

    # --- lock primitives (RedisLockPort) ---------------------------------------------------

    async def set(self, key: str, value: str, nx: bool, ex: int) -> bool:
        if nx and key in self.locks:
            return False
        self.locks[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.locks.pop(key, None)


class FixedRetryPolicy(RetryPolicy):
    def __init__(self, max_attempts: int) -> None:
        self._max_attempts = max_attempts

    def next_delay(self, attempt: int):
        if attempt >= self._max_attempts:
            return None
        return 0.0


class RecordingDeadLetterQueue(DeadLetterQueue):
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.malformed: list[dict] = []

    async def send(self, *, event: DomainEvent, error: str, attempts: int) -> None:
        self.sent.append({"event": event, "error": error, "attempts": attempts})

    async def send_malformed(self, *, raw_data: str, error: str) -> None:
        self.malformed.append({"raw_data": raw_data, "error": error})


class RedisStreamsBrokerPortTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_writes_a_single_entry_with_json_data_field(self) -> None:
        redis = FakeRedisStream()
        port = RedisStreamsBrokerPort(redis)
        await port.publish(make_event())
        self.assertEqual(len(redis.entries), 1)
        fields = next(iter(redis.entries.values()))
        data = json.loads(fields["data"])
        self.assertEqual(data["event_type"], "TripStarted")
        self.assertEqual(data["aggregate_id"], "01J8Z3K9G6X8YV5T4N2R7QW3TR")

    async def test_publish_does_not_trim_by_default(self) -> None:
        """`max_length=0` (the constructor default) keeps this class's original unbounded
        behavior, so every existing caller/test is unaffected by the trimming option."""
        redis = FakeRedisStream()
        port = RedisStreamsBrokerPort(redis)
        for _ in range(5):
            await port.publish(make_event())
        self.assertEqual(len(redis.entries), 5)
        self.assertEqual(redis.last_xadd_kwargs, {"maxlen": None, "approximate": False})

    async def test_publish_trims_the_stream_when_a_max_length_is_configured(self) -> None:
        """Stream-growth fix (2026-09-02): `raad:events` was never trimmed and had reached
        301,162 entries / ~223 MB against a 256 MB `maxmemory` under `noeviction`, where the
        next write would have failed outright and stopped the whole event backbone."""
        redis = FakeRedisStream()
        port = RedisStreamsBrokerPort(redis, max_length=3)
        for _ in range(10):
            await port.publish(make_event())

        self.assertEqual(len(redis.entries), 3)
        self.assertEqual(redis.last_xadd_kwargs, {"maxlen": 3, "approximate": True})


class RedisStreamsBrokerConsumerTests(unittest.IsolatedAsyncioTestCase):
    def _make_consumer(
        self, redis: FakeRedisStream, *, max_attempts: int = 3
    ) -> tuple[RedisStreamsBrokerConsumer, RecordingDeadLetterQueue]:
        dlq = RecordingDeadLetterQueue()
        consumer = RedisStreamsBrokerConsumer(
            redis,
            group_name="notification-worker",
            retry_policy=FixedRetryPolicy(max_attempts),
            dead_letter_queue=dlq,
        )
        return consumer, dlq

    async def test_successful_handler_acks_the_message(self) -> None:
        redis = FakeRedisStream()
        port = RedisStreamsBrokerPort(redis)
        await port.publish(make_event())
        consumer, dlq = self._make_consumer(redis)

        seen: list[DomainEvent] = []

        async def handler(event: DomainEvent) -> None:
            seen.append(event)

        await consumer.consume(handler)

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].event_type, "TripStarted")
        self.assertEqual(len(redis.acked), 1)
        self.assertEqual(redis.pending, {})
        self.assertEqual(dlq.sent, [])

    async def test_failed_handler_leaves_message_pending_not_acked(self) -> None:
        redis = FakeRedisStream()
        port = RedisStreamsBrokerPort(redis)
        await port.publish(make_event())
        consumer, dlq = self._make_consumer(redis, max_attempts=5)

        async def failing_handler(event: DomainEvent) -> None:
            raise RuntimeError("boom")

        await consumer.consume(failing_handler)

        self.assertEqual(redis.acked, [])
        self.assertEqual(len(redis.pending), 1)
        self.assertEqual(dlq.sent, [])

    async def test_exhausted_retries_routes_to_dead_letter_queue_and_acks(self) -> None:
        redis = FakeRedisStream()
        port = RedisStreamsBrokerPort(redis)
        await port.publish(make_event(event_id="evt-exhausted"))
        consumer, dlq = self._make_consumer(redis, max_attempts=1)

        async def failing_handler(event: DomainEvent) -> None:
            raise RuntimeError("boom")

        await consumer.consume(failing_handler)

        self.assertEqual(len(dlq.sent), 1)
        self.assertEqual(dlq.sent[0]["event"].event_id, "evt-exhausted")
        self.assertEqual(dlq.sent[0]["error"], "boom")
        # Exhausted -> acked (removed from the pending list; the DLQ is now its record).
        self.assertEqual(len(redis.acked), 1)

    async def test_reclaims_stale_pending_messages_and_retries_them(self) -> None:
        redis = FakeRedisStream()
        port = RedisStreamsBrokerPort(redis)
        await port.publish(make_event(event_id="evt-stale"))
        consumer, dlq = self._make_consumer(redis, max_attempts=5)

        attempts: list[int] = []

        async def counting_handler(event: DomainEvent) -> None:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("first delivery fails")

        # First pass: delivered, handler fails, stays pending.
        await consumer.consume(counting_handler)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(redis.acked, [])

        # Mark it stale so the next consume() call reclaims it via XAUTOCLAIM.
        pending_id = next(iter(redis.pending))
        redis.force_reclaimable(pending_id)

        await consumer.consume(counting_handler)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(redis.acked), 1)

    async def test_malformed_message_is_dead_lettered_and_acked_not_retried(self) -> None:
        """Live-found incident, 2026-09-01: a message written directly onto the shared stream
        without going through `_event_to_fields` (missing `event_id`) crashed `_fields_to_event`
        with an unhandled `KeyError`, which used to propagate straight out of `_process_one` -
        never acked, never dead-lettered, staying pending forever."""
        redis = FakeRedisStream()
        await redis.xadd("raad:events", {"data": json.dumps({"event_type": "SomeEvent"})})
        consumer, dlq = self._make_consumer(redis)

        async def handler(event: DomainEvent) -> None:
            pass  # must never be reached for an unparseable message

        await consumer.consume(handler)  # must not raise

        self.assertEqual(len(dlq.malformed), 1)
        self.assertIn("event_id", dlq.malformed[0]["error"])
        self.assertEqual(len(redis.acked), 1)
        self.assertEqual(redis.pending, {})

    async def test_a_malformed_message_does_not_block_a_later_well_formed_one(self) -> None:
        """The actual production symptom this bug caused: once a poisoned message existed
        anywhere in the stream, EVERY later, well-formed event (e.g. a real `VideoSessionFailed`
        reconciliation event) was never reached, because `consume()`'s own reclaim-then-read
        sequence crashed on the poisoned message before `xreadgroup` for new messages ever ran."""
        redis = FakeRedisStream()
        await redis.xadd("raad:events", {"data": json.dumps({"event_type": "Poisoned"})})
        port = RedisStreamsBrokerPort(redis)
        await port.publish(make_event(event_id="evt-well-formed"))
        consumer, dlq = self._make_consumer(redis)

        seen: list[DomainEvent] = []

        async def handler(event: DomainEvent) -> None:
            seen.append(event)

        await consumer.consume(handler)

        self.assertEqual(len(dlq.malformed), 1)
        self.assertEqual([e.event_id for e in seen], ["evt-well-formed"])
        self.assertEqual(len(redis.acked), 2)

    async def test_a_reclaimed_stale_malformed_message_is_cleared_not_re_crashed(self) -> None:
        """Mirrors `test_reclaims_stale_pending_messages_and_retries_them` for the malformed
        case — a poisoned message stuck in the pending list from before this fix (or from any
        future redelivery) must be cleared by the very next reclaim pass, not re-wedge the
        group forever."""
        redis = FakeRedisStream()
        await redis.xadd("raad:events", {"data": json.dumps({"event_type": "Poisoned"})})
        consumer, dlq = self._make_consumer(redis)

        async def handler(event: DomainEvent) -> None:
            pass

        await consumer.consume(handler)  # first pass: dead-lettered and acked immediately
        self.assertEqual(len(redis.acked), 1)
        self.assertEqual(redis.pending, {})

        # A later `consume()` call must reach `xreadgroup` cleanly - proven by publishing and
        # picking up a real event afterward.
        port = RedisStreamsBrokerPort(redis)
        await port.publish(make_event(event_id="evt-after"))
        seen: list[DomainEvent] = []

        async def handler2(event: DomainEvent) -> None:
            seen.append(event)

        await consumer.consume(handler2)
        self.assertEqual([e.event_id for e in seen], ["evt-after"])

    async def test_no_messages_is_a_clean_no_op(self) -> None:
        redis = FakeRedisStream()
        consumer, dlq = self._make_consumer(redis)
        calls: list[DomainEvent] = []

        await consumer.consume(lambda event: calls.append(event))  # type: ignore[arg-type]

        self.assertEqual(calls, [])
        self.assertEqual(dlq.sent, [])


class RedisDeadLetterQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_writes_event_plus_error_metadata(self) -> None:
        redis = FakeRedisStream()
        dlq = RedisDeadLetterQueue(redis, stream_name="raad:events:dlq")
        await dlq.send(event=make_event(), error="boom", attempts=3)

        self.assertEqual(len(redis.entries), 1)
        fields = next(iter(redis.entries.values()))
        self.assertEqual(fields["error"], "boom")
        self.assertEqual(fields["attempts"], "3")
        data = json.loads(fields["data"])
        self.assertEqual(data["event_type"], "TripStarted")

    async def test_send_malformed_writes_raw_data_plus_error_metadata(self) -> None:
        redis = FakeRedisStream()
        dlq = RedisDeadLetterQueue(redis, stream_name="raad:events:dlq")
        raw = json.dumps({"event_type": "Poisoned"})

        await dlq.send_malformed(raw_data=raw, error="KeyError: 'event_id'")

        self.assertEqual(len(redis.entries), 1)
        fields = next(iter(redis.entries.values()))
        self.assertEqual(fields["data"], raw)
        self.assertEqual(fields["error"], "KeyError: 'event_id'")
        self.assertEqual(fields["malformed"], "true")


class RedisLockPortTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_then_release_allows_reacquire(self) -> None:
        redis = FakeRedisStream()
        lock = RedisLockPort(redis)
        self.assertTrue(await lock.acquire("scheduler:lock:job", 60))
        await lock.release("scheduler:lock:job")
        self.assertTrue(await lock.acquire("scheduler:lock:job", 60))

    async def test_acquire_while_held_returns_false(self) -> None:
        redis = FakeRedisStream()
        lock = RedisLockPort(redis)
        self.assertTrue(await lock.acquire("scheduler:lock:job", 60))
        self.assertFalse(await lock.acquire("scheduler:lock:job", 60))


if __name__ == "__main__":
    unittest.main()
