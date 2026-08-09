"""`DeviceGateway` composition-root tests (device-gateway multi-vendor architecture). Verifies
both configured adapters (`jt808`, `lsz`) start under one gateway, are independently reachable
over their own real sockets, share the same injected `EventPublisher` instance, and both stop
cleanly together.
"""

import asyncio
import json
import unittest

from src.events.device_position_reported import DevicePositionReported
from src.events.redis_event_publisher import RedisEventPublisher
from src.gateway import DeviceGateway
from src.vendors.jt808.config import ServerConfig as Jt808Config
from src.vendors.lsz.config import MdvrServerConfig as LszConfig
from src.vendors.lsz.handlers.provisioning_port import ProjectionBackedMdvrProvisioningPort


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[DevicePositionReported] = []

    async def publish(self, event: DevicePositionReported) -> None:
        self.published.append(event)


class FakeRedis:
    """Minimal fake covering both `RedisEventPublisher.publish` (`xadd`) and
    `RedisDeviceRegistryConsumer` (`xgroup_create`/`xreadgroup`/`xack`) — enough for
    `DeviceGateway`'s Redis-wired path to exercise both without a real Redis connection."""

    def __init__(self) -> None:
        self._next_id = 1
        self.entries: list[tuple[str, dict[str, str]]] = []
        self.groups: set[tuple[str, str]] = set()
        self.acked: list[str] = []

    async def xadd(self, name: str, fields: dict[str, str]) -> str:
        message_id = str(self._next_id)
        self._next_id += 1
        self.entries.append((message_id, fields))
        return message_id

    async def xgroup_create(self, name, groupname, id, mkstream) -> None:
        key = (name, groupname)
        if key in self.groups:
            raise Exception("BUSYGROUP Consumer Group name already exists")
        self.groups.add(key)

    async def xreadgroup(self, group_name, consumer_name, streams, count, block):
        # A real `redis.asyncio.Redis.xreadgroup` performs genuine network I/O and therefore
        # always suspends back to the event loop — this fake has no real I/O to await, so it
        # must yield explicitly (`asyncio.sleep(0)`), or `RedisDeviceRegistryConsumer.run_forever`'s
        # `while True` loop would never suspend at all once entries are exhausted, starving the
        # event loop (including this test's own `asyncio.sleep`/`task.cancel()`) forever.
        await asyncio.sleep(0)
        (stream_name, _marker) = next(iter(streams.items()))
        pending = [
            (message_id, fields)
            for message_id, fields in self.entries
            if message_id not in self.acked
        ]
        batch = pending[:count]
        return [(stream_name, batch)] if batch else []

    async def xack(self, name, groupname, message_id) -> None:
        self.acked.append(message_id)


class DeviceGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_adapters_are_registered_by_name(self) -> None:
        gateway = DeviceGateway(
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        self.assertEqual({a.name for a in gateway.adapters}, {"jt808", "lsz"})
        self.assertIs(gateway.adapter("jt808").__class__.__name__, "Jt808Server")

    async def test_start_binds_both_adapters_to_independent_real_ports(self) -> None:
        gateway = DeviceGateway(
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        await gateway.start()
        try:
            jt808_port = gateway.adapter("jt808").bound_port
            lsz_port = gateway.adapter("lsz").bound_port
            self.assertNotEqual(jt808_port, 0)
            self.assertNotEqual(lsz_port, 0)
            self.assertNotEqual(jt808_port, lsz_port)

            # Both ports genuinely accept a real TCP connection.
            for port in (jt808_port, lsz_port):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
        finally:
            await gateway.stop()

    async def test_both_adapters_share_the_same_injected_event_publisher(self) -> None:
        publisher = RecordingEventPublisher()
        gateway = DeviceGateway(
            event_publisher=publisher,
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        self.assertIs(gateway.adapter("jt808").event_publisher, publisher)
        self.assertIs(gateway.adapter("lsz").event_publisher, publisher)

    async def test_stop_is_safe_to_call_on_both_adapters(self) -> None:
        gateway = DeviceGateway(
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        await gateway.start()
        await gateway.stop()  # must not raise

    async def test_unknown_adapter_name_raises_lookup_error(self) -> None:
        gateway = DeviceGateway(
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        with self.assertRaises(LookupError):
            gateway.adapter("teltonika")

    async def test_without_a_broker_falls_back_to_logging_publisher_and_null_provisioning(
        self,
    ) -> None:
        """No `redis_client`/`broker_config.url` given -- must fall back exactly as before this
        phase, not silently require Redis. Covers both vendors (JT808 device-plane integration
        gap added the jt808 half of this assertion)."""
        from src.events.publisher_port import LoggingEventPublisher
        from src.vendors.jt808.handlers.provisioning_port import NullDeviceProvisioningPort
        from src.vendors.lsz.handlers.provisioning_port import NullMdvrDeviceProvisioningPort

        gateway = DeviceGateway(
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        self.assertIsInstance(gateway.adapter("lsz").event_publisher, LoggingEventPublisher)
        self.assertIsInstance(
            gateway.adapter("lsz").device_provisioning, NullMdvrDeviceProvisioningPort
        )
        self.assertIsInstance(
            gateway.adapter("jt808").device_provisioning, NullDeviceProvisioningPort
        )
        self.assertIsNone(gateway.registry_projection)


class DeviceGatewayRedisWiringTests(unittest.IsolatedAsyncioTestCase):
    """Proves the Redis-wired path end to end: injecting a fake Redis client (no real server,
    no `DEVICE_GATEWAY_BROKER_URL`) is enough to get a real `RedisEventPublisher`, a real
    `DeviceRegistryProjection` fed by a real `RedisDeviceRegistryConsumer` background task, and
    both vendors' real `ProjectionBacked*ProvisioningPort` — not the interim defaults. JT808's
    half (`ProjectionBackedJt808ProvisioningPort`) is the JT808 device-plane integration gap this
    suite closes; LSZ's own coverage is unchanged."""

    async def test_redis_client_wires_redis_event_publisher(self) -> None:
        redis = FakeRedis()
        gateway = DeviceGateway(
            redis_client=redis,
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        self.assertIsInstance(gateway.adapter("jt808").event_publisher, RedisEventPublisher)
        self.assertIsInstance(gateway.adapter("lsz").event_publisher, RedisEventPublisher)
        self.assertIs(gateway.adapter("jt808").event_publisher, gateway.adapter("lsz").event_publisher)

    async def test_redis_client_wires_projection_backed_lsz_provisioning(self) -> None:
        redis = FakeRedis()
        gateway = DeviceGateway(
            redis_client=redis,
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        self.assertIsInstance(
            gateway.adapter("lsz").device_provisioning, ProjectionBackedMdvrProvisioningPort
        )
        self.assertIsNotNone(gateway.registry_projection)

    async def test_redis_client_wires_projection_backed_jt808_provisioning(self) -> None:
        from src.vendors.jt808.handlers.provisioning_port import (
            ProjectionBackedJt808ProvisioningPort,
        )

        redis = FakeRedis()
        gateway = DeviceGateway(
            redis_client=redis,
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        self.assertIsInstance(
            gateway.adapter("jt808").device_provisioning, ProjectionBackedJt808ProvisioningPort
        )
        self.assertIsNotNone(gateway.registry_projection)

    async def test_jt808_and_lsz_provisioning_share_one_registry_projection(self) -> None:
        """A single `DeviceRegistered` event (carrying both `terminal_id` and `serial_number`)
        must be resolvable through *both* vendors' provisioning ports — proving they share one
        `DeviceRegistryProjection` instance, not two independently-fed copies."""
        redis = FakeRedis()
        redis.entries.append(
            (
                "1",
                {
                    "data": json.dumps(
                        {
                            "event_id": "evt-1",
                            "event_type": "DeviceRegistered",
                            "version": 1,
                            "occurred_at": "2026-08-09T10:00:00+00:00",
                            "org_id": "org-1",
                            "correlation_id": None,
                            "payload": {
                                "terminal_id": "013800138000",
                                "serial_number": "00007",
                            },
                            "aggregate_type": "Device",
                            "aggregate_id": "device-1",
                        }
                    )
                },
            )
        )
        for event_type in ("DeviceActivated",):
            redis.entries.append(
                (
                    str(len(redis.entries) + 1),
                    {
                        "data": json.dumps(
                            {
                                "event_id": f"evt-{event_type}",
                                "event_type": event_type,
                                "version": 1,
                                "occurred_at": "2026-08-09T10:00:01+00:00",
                                "org_id": "org-1",
                                "correlation_id": None,
                                "payload": {},
                                "aggregate_type": "Device",
                                "aggregate_id": "device-1",
                            }
                        )
                    },
                )
            )
        redis.entries.append(
            (
                str(len(redis.entries) + 1),
                {
                    "data": json.dumps(
                        {
                            "event_id": "evt-assigned",
                            "event_type": "DeviceAssignedToVehicle",
                            "version": 1,
                            "occurred_at": "2026-08-09T10:00:02+00:00",
                            "org_id": "org-1",
                            "correlation_id": None,
                            "payload": {"device_id": "device-1", "vehicle_id": "vehicle-1"},
                            "aggregate_type": "DeviceAssignment",
                            "aggregate_id": "assignment-1",
                        }
                    )
                },
            )
        )
        redis._next_id = len(redis.entries) + 1

        gateway = DeviceGateway(
            redis_client=redis,
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        await gateway.start()
        try:
            await asyncio.sleep(0.05)

            jt808_result = await gateway.adapter("jt808").device_provisioning.authorize_registration(
                terminal_phone="013800138000", request=None
            )
            self.assertEqual(jt808_result.result.value, "success")
            self.assertEqual(jt808_result.organization_id, "org-1")
            self.assertEqual(jt808_result.vehicle_id, "vehicle-1")

            lsz_result = await gateway.adapter("lsz").device_provisioning.authorize_registration(
                device_serial_number="00007"
            )
            self.assertEqual(lsz_result.result.value, "success")
            self.assertEqual(lsz_result.organization_id, "org-1")
            self.assertEqual(lsz_result.vehicle_id, "vehicle-1")
        finally:
            await gateway.stop()

    async def test_registry_consumer_runs_in_the_background_after_start(self) -> None:
        redis = FakeRedis()
        redis.entries.append(
            (
                "1",
                {
                    "data": json.dumps(
                        {
                            "event_id": "evt-1",
                            "event_type": "DeviceRegistered",
                            "version": 1,
                            "occurred_at": "2026-07-24T10:00:00+00:00",
                            "org_id": "org-1",
                            "correlation_id": None,
                            "payload": {
                                "terminal_id": "TERM-1",
                                "serial_number": "00007",
                            },
                            "aggregate_type": "Device",
                            "aggregate_id": "device-1",
                        }
                    )
                },
            )
        )
        redis._next_id = 2
        gateway = DeviceGateway(
            redis_client=redis,
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        await gateway.start()
        try:
            await asyncio.sleep(0.05)
            self.assertIsNotNone(gateway.registry_projection.lookup_by_serial_number("00007"))
        finally:
            await gateway.stop()

    async def test_stop_cancels_the_registry_consumer_task_cleanly(self) -> None:
        redis = FakeRedis()
        gateway = DeviceGateway(
            redis_client=redis,
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        await gateway.start()
        await gateway.stop()  # must not raise or hang


if __name__ == "__main__":
    unittest.main()
