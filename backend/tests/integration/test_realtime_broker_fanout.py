"""Redis Streams integration test for `interfaces.http.realtime`'s `BrokerFanOutWorker` +
`build_realtime_broker_consumer` (WebSocket phase). Mirrors `test_tracking_redis_latest_
position.py`'s live-Redis skip-guard pattern exactly, but gated on `RAAD_BROKER__URL` instead
of `RAAD_REDIS__URL`.

Covers what the unit tests (`test_realtime.py`, `test_tracking_ws.py`, `test_notifications_ws.py`)
cannot: a real `RedisStreamsBrokerPort.publish()` -> real `XADD` -> a **distinct** consumer
group's real `XREADGROUP` -> `BrokerFanOutWorker.run_once()` -> handler round trip, proving two
independently-named consumer groups (`ws-tracking`/`ws-notifications`, vs. `core/di/
bootstrap.py`'s own `notification-worker` group) each receive their own full copy of every
event on one shared stream, exactly as ADR-0008's consumer-group semantics promise and this
module's own docstring explains. That shared stream is a per-run throwaway here, never the
real `raad:events` — see **Stream isolation** below.

**Requires a reachable broker**, configured via `RAAD_BROKER__URL` (`.env`). Skipped entirely
(not failed) when unavailable, the same already-established gap
`test_tracking_redis_latest_position.py` documents for its own, independently-configured Redis
client.

**Stream isolation (2026-09-03).** Every run publishes to, and consumes from, its own
throwaway `raad:events:test-<tag>` stream, deleted in `asyncTearDown` — mirroring
`test_tracking_redis_latest_position.py`'s existing "unique key per run, delete only that key"
pattern exactly. The shared `raad:events` stream is never read, written, or trimmed here.

This is not cosmetic. A consumer group is created at `id="0"` (`redis_streams.py`), i.e. it
replays a stream from the very beginning, and `run_once()` reads only `batch_size` (10)
messages per tick. Against a development broker whose `raad:events` already holds ~195k
entries, a fresh group therefore spends both ticks on ancient history and never reaches the
event the test just published — the assertions failed with `0 != 1` for a reason that had
nothing to do with fan-out semantics. CI passes only because its Redis service container
starts empty. A per-run stream makes the test independent of how much history the target
broker happens to hold.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from redis.asyncio import Redis

from raad.core.config.settings import get_settings
from raad.core.events.base import DomainEvent
from raad.core.events.redis_streams import RedisStreamsBrokerPort
from raad.core.time.clock import SystemClock
from raad.interfaces.http.realtime import BrokerFanOutWorker, build_realtime_broker_consumer


def _broker_available() -> bool:
    try:
        return bool(get_settings().broker.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_BROKER__URL not configured — broker integration tests require a live instance."


@unittest.skipUnless(_broker_available(), _SKIP_REASON)
class BrokerFanOutWorkerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.tag = uuid.uuid4().hex[:8]
        # Own stream per run — never the shared `raad:events` (see module docstring).
        self.stream_name = f"raad:events:test-{self.tag}"
        self.redis = Redis.from_url(settings.broker.url, decode_responses=True)
        self.broker_port = RedisStreamsBrokerPort(self.redis, stream_name=self.stream_name)
        self.clock = SystemClock()

    async def asyncTearDown(self) -> None:
        # Deletes only this run's own stream; consumer groups live inside it and go with it.
        await self.redis.delete(self.stream_name)
        await self.redis.aclose()

    def _make_consumer(self, group_name: str):
        return build_realtime_broker_consumer(
            broker_url=get_settings().broker.url,
            group_name=f"{group_name}-{self.tag}",
            clock=self.clock,
            stream_name=self.stream_name,
        )

    async def test_two_distinct_consumer_groups_each_receive_the_published_event(self) -> None:
        event = DomainEvent(
            event_id=f"evt-{self.tag}",
            event_type="DevicePositionReported",
            version=1,
            occurred_at=datetime.now(timezone.utc),
            org_id="org-1",
            correlation_id=None,
            payload={"vehicle_id": f"veh-{self.tag}", "lat": 1.0, "lng": 2.0},
            aggregate_type="Vehicle",
            aggregate_id=f"veh-{self.tag}",
        )
        await self.broker_port.publish(event)

        received_a: list[DomainEvent] = []
        received_b: list[DomainEvent] = []
        worker_a = BrokerFanOutWorker(
            "test-a",
            clock=self.clock,
            consumer=self._make_consumer("ws-tracking-test"),
            handler=received_a.append,
        )
        worker_b = BrokerFanOutWorker(
            "test-b",
            clock=self.clock,
            consumer=self._make_consumer("ws-notifications-test"),
            handler=received_b.append,
        )

        await worker_a.run_once()
        await worker_b.run_once()

        matching_a = [e for e in received_a if e.event_id == event.event_id]
        matching_b = [e for e in received_b if e.event_id == event.event_id]
        self.assertEqual(len(matching_a), 1)
        self.assertEqual(len(matching_b), 1)
        self.assertEqual(matching_a[0].payload["vehicle_id"], f"veh-{self.tag}")

    async def test_a_second_run_once_does_not_redeliver_the_same_event(self) -> None:
        """At-least-once delivery within *one* group's own tracking, not "redeliver forever" —
        once acked, a `run_once()` tick must not see the same message again."""
        event = DomainEvent(
            event_id=f"evt-redeliver-{self.tag}",
            event_type="DevicePositionReported",
            version=1,
            occurred_at=datetime.now(timezone.utc),
            org_id="org-1",
            correlation_id=None,
            payload={"vehicle_id": f"veh-{self.tag}"},
            aggregate_type="Vehicle",
            aggregate_id=f"veh-{self.tag}",
        )
        await self.broker_port.publish(event)

        received: list[DomainEvent] = []
        consumer = self._make_consumer("ws-redeliver-test")
        worker = BrokerFanOutWorker(
            "test-redeliver", clock=self.clock, consumer=consumer, handler=received.append
        )

        await worker.run_once()
        await worker.run_once()

        matching = [e for e in received if e.event_id == event.event_id]
        self.assertEqual(len(matching), 1)


if __name__ == "__main__":
    unittest.main()
