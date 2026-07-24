"""`RedisDeviceRegistryConsumer` tests. A minimal in-memory fake stands in for the Redis Streams
consumer-group commands this class calls (`xgroup_create`, `xreadgroup`, `xack`) — no real Redis
connection, mirroring the backend's own `test_redis_streams_broker.py` fake-client convention.
"""

import json
import unittest

from src.registry.device_registry_projection import DeviceRegistryProjection
from src.registry.redis_device_registry_consumer import RedisDeviceRegistryConsumer


class FakeRedisConsumerGroupStream:
    def __init__(self) -> None:
        self._next_id = 1
        self.entries: list[tuple[str, dict[str, str]]] = []
        self.groups: set[tuple[str, str]] = set()
        self.acked: list[str] = []

    def add_event(self, *, event_type: str, aggregate_id: str, org_id, payload: dict) -> None:
        message_id = str(self._next_id)
        self._next_id += 1
        data = json.dumps(
            {
                "event_id": f"evt-{message_id}",
                "event_type": event_type,
                "version": 1,
                "occurred_at": "2026-07-24T10:00:00+00:00",
                "org_id": org_id,
                "correlation_id": None,
                "payload": payload,
                "aggregate_type": "Device",
                "aggregate_id": aggregate_id,
            }
        )
        self.entries.append((message_id, {"data": data}))

    async def xgroup_create(self, name, groupname, id, mkstream) -> None:
        key = (name, groupname)
        if key in self.groups:
            raise Exception("BUSYGROUP Consumer Group name already exists")
        self.groups.add(key)

    async def xreadgroup(self, group_name, consumer_name, streams, count, block):
        (stream_name, _marker) = next(iter(streams.items()))
        pending = [
            (message_id, fields)
            for message_id, fields in self.entries
            if message_id not in self.acked
        ]
        batch = pending[:count]
        if not batch:
            return []
        return [(stream_name, batch)]

    async def xack(self, name, groupname, message_id) -> None:
        self.acked.append(message_id)


class RedisDeviceRegistryConsumerTests(unittest.IsolatedAsyncioTestCase):
    async def test_relevant_event_is_applied_to_projection(self) -> None:
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="DeviceRegistered",
            aggregate_id="device-1",
            org_id="org-1",
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        projection = DeviceRegistryProjection()
        consumer = RedisDeviceRegistryConsumer(redis, projection=projection)

        applied = await consumer.poll_once()

        self.assertEqual(applied, 1)
        self.assertIsNotNone(projection.lookup_by_serial_number("00007"))
        self.assertEqual(redis.acked, ["1"])

    async def test_irrelevant_event_is_acked_but_not_applied(self) -> None:
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="TripStarted",
            aggregate_id="trip-1",
            org_id="org-1",
            payload={"vehicle_id": "vehicle-1"},
        )
        projection = DeviceRegistryProjection()
        consumer = RedisDeviceRegistryConsumer(redis, projection=projection)

        applied = await consumer.poll_once()

        self.assertEqual(applied, 0)
        self.assertEqual(redis.acked, ["1"])  # still acked - must not pile up unbounded
        self.assertEqual(len(projection), 0)

    async def test_multiple_events_processed_in_one_poll(self) -> None:
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="DeviceRegistered",
            aggregate_id="device-1",
            org_id="org-1",
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        redis.add_event(
            event_type="DeviceActivated", aggregate_id="device-1", org_id="org-1", payload={}
        )
        projection = DeviceRegistryProjection()
        consumer = RedisDeviceRegistryConsumer(redis, projection=projection)

        applied = await consumer.poll_once()

        self.assertEqual(applied, 2)
        self.assertFalse(
            projection.lookup_by_serial_number("00007").is_provisionable
        )  # active but still unassigned

    async def test_group_already_exists_does_not_raise(self) -> None:
        redis = FakeRedisConsumerGroupStream()
        projection = DeviceRegistryProjection()
        consumer = RedisDeviceRegistryConsumer(redis, projection=projection)
        await consumer.poll_once()
        await consumer.poll_once()  # second call must not raise on BUSYGROUP


if __name__ == "__main__":
    unittest.main()
