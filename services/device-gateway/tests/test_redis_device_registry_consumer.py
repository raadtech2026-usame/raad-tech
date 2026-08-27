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

    async def xrange(self, name, min="-", max="+", count=None):
        entries = self.entries
        if min != "-":
            if min.startswith("("):
                after = int(min[1:])
                entries = [e for e in entries if int(e[0]) > after]
            else:
                floor = int(min)
                entries = [e for e in entries if int(e[0]) >= floor]
        if max != "+":
            ceiling = int(max)
            entries = [e for e in entries if int(e[0]) <= ceiling]
        if count is not None:
            entries = entries[:count]
        return entries


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

    async def test_auth_code_issued_event_is_now_relevant_and_applied(self) -> None:
        """P0 #2 fix: `DeviceAuthCodeIssued` must no longer be filtered out as irrelevant — it
        needs to reach the projection the same way `DeviceActivated`/etc. already do, so
        `replay_from_start` can recover a previously-minted `auth_key_hash` after a restart."""
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="DeviceRegistered",
            aggregate_id="device-1",
            org_id="org-1",
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        redis.add_event(
            event_type="DeviceAuthCodeIssued",
            aggregate_id="device-1",
            org_id="org-1",
            payload={"auth_key_hash": "pbkdf2_sha256$10000$salt$hash"},
        )
        projection = DeviceRegistryProjection()
        consumer = RedisDeviceRegistryConsumer(redis, projection=projection)

        applied = await consumer.poll_once()

        self.assertEqual(applied, 2)
        self.assertEqual(
            projection.lookup_by_terminal_id("TERM-1").auth_key_hash,
            "pbkdf2_sha256$10000$salt$hash",
        )

    async def test_group_already_exists_does_not_raise(self) -> None:
        redis = FakeRedisConsumerGroupStream()
        projection = DeviceRegistryProjection()
        consumer = RedisDeviceRegistryConsumer(redis, projection=projection)
        await consumer.poll_once()
        await consumer.poll_once()  # second call must not raise on BUSYGROUP


class ReplayFromStartTests(unittest.IsolatedAsyncioTestCase):
    """The fix for a real, live-found gap (2026-08-19): a fresh, in-memory
    `DeviceRegistryProjection` combined with a Redis consumer *group* that already sits caught
    up (its cursor is durable Redis state, unlike the projection) previously meant a
    device-gateway restart silently lost the registry for every already-provisioned device.
    `replay_from_start` must rebuild the projection from the full stream regardless of the
    consumer group's own position."""

    async def test_rebuilds_projection_from_full_stream(self) -> None:
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
        redis.add_event(
            event_type="DeviceAssignedToVehicle",
            aggregate_id="assignment-1",
            org_id="org-1",
            payload={"device_id": "device-1", "vehicle_id": "vehicle-1"},
        )
        projection = DeviceRegistryProjection()
        consumer = RedisDeviceRegistryConsumer(redis, projection=projection)

        applied = await consumer.replay_from_start()

        self.assertEqual(applied, 3)
        record = projection.lookup_by_terminal_id("TERM-1")
        self.assertIsNotNone(record)
        self.assertTrue(record.is_provisionable)

    async def test_rebuilds_even_when_the_consumer_group_already_acked_everything(self) -> None:
        """Reproduces the exact live incident: events already fully consumed/acked by a prior
        process (the group's cursor is past them), but a brand-new process has an empty
        projection. A plain `poll_once`/`xreadgroup` would see nothing; `replay_from_start`
        (raw `XRANGE`, no group semantics) must still recover full state."""
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="DeviceRegistered",
            aggregate_id="device-1",
            org_id="org-1",
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        redis.add_event(
            event_type="DeviceAssignedToVehicle",
            aggregate_id="assignment-1",
            org_id="org-1",
            payload={"device_id": "device-1", "vehicle_id": "vehicle-1"},
        )
        stale_projection = DeviceRegistryProjection()
        stale_consumer = RedisDeviceRegistryConsumer(redis, projection=stale_projection)
        await stale_consumer.poll_once()  # simulates the prior process: fully caught up, acked
        self.assertEqual(len(redis.acked), 2)

        # A fresh process restarts: new in-memory projection, but the SAME Redis-side group
        # state (same fake `redis` instance) already sits past both events.
        fresh_projection = DeviceRegistryProjection()
        fresh_consumer = RedisDeviceRegistryConsumer(redis, projection=fresh_projection)

        # The bug this fix closes: a plain poll_once() sees nothing new to read.
        self.assertEqual(await fresh_consumer.poll_once(), 0)
        self.assertEqual(len(fresh_projection), 0)

        # replay_from_start ignores the group's position entirely and recovers full state.
        applied = await fresh_consumer.replay_from_start()

        self.assertEqual(applied, 2)
        self.assertEqual(
            fresh_projection.lookup_by_terminal_id("TERM-1").vehicle_id, "vehicle-1"
        )

    async def test_paginates_past_a_single_batch(self) -> None:
        redis = FakeRedisConsumerGroupStream()
        for i in range(5):
            redis.add_event(
                event_type="DeviceRegistered",
                aggregate_id=f"device-{i}",
                org_id="org-1",
                payload={"terminal_id": f"TERM-{i}", "serial_number": f"SN-{i}"},
            )
        projection = DeviceRegistryProjection()
        consumer = RedisDeviceRegistryConsumer(redis, projection=projection, batch_size=2)

        applied = await consumer.replay_from_start()

        self.assertEqual(applied, 5)
        self.assertEqual(len(projection), 5)

    async def test_does_not_ack_anything(self) -> None:
        """A raw XRANGE replay must never touch the consumer group's own ack state - it is a
        read-only reconstruction pass, not a substitute for the group's own incremental
        consumption."""
        redis = FakeRedisConsumerGroupStream()
        redis.add_event(
            event_type="DeviceRegistered",
            aggregate_id="device-1",
            org_id="org-1",
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        projection = DeviceRegistryProjection()
        consumer = RedisDeviceRegistryConsumer(redis, projection=projection)

        await consumer.replay_from_start()

        self.assertEqual(redis.acked, [])


if __name__ == "__main__":
    unittest.main()
