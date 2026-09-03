"""`DeviceGateway` composition-root tests (device-gateway multi-vendor architecture). Verifies
both configured adapters (`jt808`, `lsz`) start under one gateway, are independently reachable
over their own real sockets, share the same injected `EventPublisher` instance, and both stop
cleanly together.
"""

import asyncio
import json
import unittest
from datetime import datetime, timezone

from src.events.device_position_reported import DevicePositionReported
from src.events.redis_event_publisher import RedisEventPublisher
from src.gateway import DeviceGateway
from src.vendors.jt808.config import ServerConfig as Jt808Config
from src.vendors.jt808.dispatcher import message_ids
from src.vendors.jt808.protocol.checksum import compute_checksum
from src.vendors.jt808.protocol.escaping import escape
from src.vendors.jt808.protocol.header import encode_bcd_phone
from src.vendors.jt808.protocol.parser import PacketParser
from src.vendors.jt808.protocol.strings import encode_gbk_string
from src.vendors.lsz.config import MdvrServerConfig as LszConfig
from src.vendors.lsz.handlers.provisioning_port import ProjectionBackedMdvrProvisioningPort


def _wire_frame(message_id: int, phone: str, serial_no: int, body: bytes = b"") -> bytes:
    body_attrs = (len(body) & 0x03FF) | (1 << 14)
    header = (
        message_id.to_bytes(2, "big")
        + body_attrs.to_bytes(2, "big")
        + bytes([0x01])
        + encode_bcd_phone(phone)
        + serial_no.to_bytes(2, "big")
    )
    payload = header + body
    checksum = compute_checksum(payload)
    return bytes([0x7E]) + escape(payload + bytes([checksum])) + bytes([0x7E])


def _device_registered_entries(
    *, terminal_id: str, serial_number: str, device_id: str, vehicle_id: str, org_id: str
) -> list[tuple[str, dict[str, str]]]:
    """Mirrors `DeviceGatewayRedisWiringTests.test_jt808_and_lsz_provisioning_share_one_registry_
    projection`'s own event-seeding pattern: enough `DeviceRegistered`/`DeviceActivated`/
    `DeviceAssignedToVehicle` events for `ProjectionBackedJt808ProvisioningPort` to genuinely
    authorize a real registration+authentication handshake against."""
    return [
        (
            "seed-1",
            {
                "data": json.dumps(
                    {
                        "event_id": "evt-registered",
                        "event_type": "DeviceRegistered",
                        "version": 1,
                        "occurred_at": "2026-08-11T09:00:00+00:00",
                        "org_id": org_id,
                        "correlation_id": None,
                        "payload": {"terminal_id": terminal_id, "serial_number": serial_number},
                        "aggregate_type": "Device",
                        "aggregate_id": device_id,
                    }
                )
            },
        ),
        (
            "seed-2",
            {
                "data": json.dumps(
                    {
                        "event_id": "evt-activated",
                        "event_type": "DeviceActivated",
                        "version": 1,
                        "occurred_at": "2026-08-11T09:00:01+00:00",
                        "org_id": org_id,
                        "correlation_id": None,
                        "payload": {},
                        "aggregate_type": "Device",
                        "aggregate_id": device_id,
                    }
                )
            },
        ),
        (
            "seed-3",
            {
                "data": json.dumps(
                    {
                        "event_id": "evt-assigned",
                        "event_type": "DeviceAssignedToVehicle",
                        "version": 1,
                        "occurred_at": "2026-08-11T09:00:02+00:00",
                        "org_id": org_id,
                        "correlation_id": None,
                        "payload": {"device_id": device_id, "vehicle_id": vehicle_id},
                        "aggregate_type": "DeviceAssignment",
                        "aggregate_id": "assignment-1",
                    }
                )
            },
        ),
    ]


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[DevicePositionReported] = []

    async def publish(self, event: DevicePositionReported) -> None:
        self.published.append(event)


class FakeRedis:
    """Minimal fake covering `RedisEventPublisher.publish` (`xadd`), every consumer-group reader
    this deployable now has (`RedisDeviceRegistryConsumer`, `RedisVideoSignalingConsumer`), and
    the plain string/set commands `RedisDeviceSessionRegistry` uses (P0 #2 fix, device-gateway
    session-durability audit, 2026-08-25) — enough for `DeviceGateway`'s Redis-wired path to
    exercise all of them together without a real Redis connection.

    **Acknowledgment is tracked per consumer group** (`self.acked: dict[groupname, set[message_id]]`),
    matching real Redis Streams semantics — a message acked in one group's own pending-entries
    list is untouched in every other group's. Two independent consumer groups reading the *same*
    stream (the registry consumer and the video-signaling consumer, both now real in
    `DeviceGateway`) would otherwise "steal" each other's unread messages under a single shared
    ack list, a real bug this fake's own earlier single-list shape had until the JT/T 1078
    video-signaling-forwarding phase's second consumer group exposed it."""

    def __init__(self) -> None:
        self._next_id = 1
        self.entries: list[tuple[str, dict[str, str]]] = []
        self.groups: set[tuple[str, str]] = set()
        self.acked: dict[str, set[str]] = {}
        # P0 #2 fix (device-gateway session-durability audit, 2026-08-25): plain string/set
        # commands, so this same fake can also back a `RedisDeviceSessionRegistry` alongside the
        # stream commands above — mirrors `test_redis_device_session_registry.py`'s own `FakeRedis`.
        self._strings: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}

    async def get(self, key: str):
        return self._strings.get(key)

    async def set(self, key: str, value: str) -> None:
        self._strings[key] = value

    async def delete(self, key: str) -> None:
        self._strings.pop(key, None)

    async def sadd(self, key: str, *values: str) -> None:
        self._sets.setdefault(key, set()).update(values)

    async def srem(self, key: str, *values: str) -> None:
        self._sets.get(key, set()).difference_update(values)

    async def smembers(self, key: str):
        return set(self._sets.get(key, set()))

    async def scard(self, key: str) -> int:
        return len(self._sets.get(key, set()))

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = False,
    ) -> str:
        # `maxlen`/`approximate` mirror redis-py's own `XADD` kwargs — accepted (and
        # recorded) so this fake stays call-compatible with the stream-trimming fix
        # (2026-09-02); trimming itself is asserted in the publisher's own unit tests.
        self.last_xadd_kwargs = {"maxlen": maxlen, "approximate": approximate}
        message_id = str(self._next_id)
        self._next_id += 1
        self.entries.append((message_id, fields))
        return message_id

    async def xgroup_create(self, name, groupname, id, mkstream) -> None:
        key = (name, groupname)
        if key in self.groups:
            raise Exception("BUSYGROUP Consumer Group name already exists")
        self.groups.add(key)
        self.acked.setdefault(groupname, set())

    async def xreadgroup(self, group_name, consumer_name, streams, count, block):
        # A real `redis.asyncio.Redis.xreadgroup` performs genuine network I/O and therefore
        # always suspends back to the event loop — this fake has no real I/O to await, so it
        # must yield explicitly (`asyncio.sleep(0)`), or a consumer's `run_forever`'s `while True`
        # loop would never suspend at all once entries are exhausted, starving the event loop
        # (including this test's own `asyncio.sleep`/`task.cancel()`) forever.
        await asyncio.sleep(0)
        (stream_name, _marker) = next(iter(streams.items()))
        already_acked = self.acked.setdefault(group_name, set())
        pending = [
            (message_id, fields)
            for message_id, fields in self.entries
            if message_id not in already_acked
        ]
        batch = pending[:count]
        return [(stream_name, batch)] if batch else []

    async def xack(self, name, groupname, message_id) -> None:
        self.acked.setdefault(groupname, set()).add(message_id)

    async def xrange(self, name, min="-", max="+", count=None):
        # `RedisDeviceRegistryConsumer.replay_from_start` reads with plain XRANGE, deliberately
        # bypassing consumer-group/ack state entirely - same yield-back requirement as
        # `xreadgroup` above, for the same reason.
        await asyncio.sleep(0)
        entries = self.entries
        if min != "-":
            if min.startswith("("):
                floor = int(min[1:])
                entries = [e for e in entries if int(e[0]) > floor]
            else:
                floor = int(min)
                entries = [e for e in entries if int(e[0]) >= floor]
        if max != "+":
            ceiling = int(max)
            entries = [e for e in entries if int(e[0]) <= ceiling]
        if count is not None:
            entries = entries[:count]
        return entries


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

    async def test_redis_client_wires_redis_device_session_registry_for_jt808_only(self) -> None:
        """P0 #2 fix (device-gateway session-durability audit, 2026-08-25): JT808 alone gets a
        `RedisDeviceSessionRegistry` whenever a broker is configured. LSZ/`MdvrServer` is not
        given this wiring at all — its constructor has no `device_session_registry` parameter to
        begin with, so there is nothing to assert here beyond that structural fact; it keeps its
        in-memory default, dormant per CLAUDE.md's own posture."""
        from src.session.redis_device_session_registry import RedisDeviceSessionRegistry

        redis = FakeRedis()
        gateway = DeviceGateway(
            redis_client=redis,
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        self.assertIsInstance(
            gateway.adapter("jt808").device_session_registry, RedisDeviceSessionRegistry
        )

    async def test_without_a_broker_jt808_falls_back_to_in_memory_session_registry(self) -> None:
        from src.session.device_session_registry import DeviceSessionRegistry

        gateway = DeviceGateway(
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        self.assertIsInstance(
            gateway.adapter("jt808").device_session_registry, DeviceSessionRegistry
        )

    async def test_session_created_on_one_jt808_server_is_visible_from_another_sharing_redis(
        self,
    ) -> None:
        """The actual point of this wiring: session state now lives in Redis, not a single
        process's memory. Two independent `Jt808Server` instances (standing in for two
        independent device-gateway processes/restarts) sharing one Redis backing must see the
        same session — proving durability, not just that the right class got constructed."""
        from src.session.redis_device_session_registry import RedisDeviceSessionRegistry
        from src.vendors.jt808.server import Jt808Server

        redis = FakeRedis()
        registry_a = RedisDeviceSessionRegistry(redis)
        registry_b = RedisDeviceSessionRegistry(redis)

        server_a = Jt808Server(
            Jt808Config(host="127.0.0.1", port=0), device_session_registry=registry_a
        )
        server_b = Jt808Server(
            Jt808Config(host="127.0.0.1", port=0), device_session_registry=registry_b
        )

        await server_a.device_sessions.create(connection_id="conn-1", terminal_id="TERM-1")

        session_from_b = await server_b.device_sessions.resolve("TERM-1")
        self.assertIsNotNone(session_from_b)
        self.assertEqual(session_from_b.connection_id, "conn-1")

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

    async def test_without_a_broker_no_video_signaling_consumer_is_built(self) -> None:
        gateway = DeviceGateway(
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        self.assertIsNone(gateway._video_signaling_consumer)  # nothing to run/stop without Redis

    async def test_broker_configured_builds_a_video_signaling_consumer_bound_to_jt808(
        self,
    ) -> None:
        redis = FakeRedis()
        gateway = DeviceGateway(
            redis_client=redis,
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        self.assertIsNotNone(gateway._video_signaling_consumer)

    async def test_video_signaling_command_from_the_broker_reaches_a_live_terminal(self) -> None:
        """End-to-end proof of ADR-0024 §8's "Command direction (Backend -> device, via
        device-gateway)": a `Jt1078SignalCommandRequested` event sitting on the shared stream is
        picked up by the background consumer and actually reaches a real, authenticated JT808
        connection as a real `0x9101` frame - the same path a real Business API publisher would
        drive. Authenticates the real way (register -> mint auth code -> authenticate with it),
        the same real `ProjectionBackedJt808ProvisioningPort` path `DeviceGatewayRedisWiringTests.
        test_jt808_and_lsz_provisioning_share_one_registry_projection` already proves works, so
        this test needs no fake provisioning port of its own."""
        terminal_phone = "00000000013800138000"

        redis = FakeRedis()
        redis.entries.extend(
            _device_registered_entries(
                terminal_id=terminal_phone,
                serial_number="00007",
                device_id="device-1",
                vehicle_id="vehicle-1",
                org_id="org-1",
            )
        )
        redis._next_id = 4

        gateway = DeviceGateway(
            redis_client=redis,
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        await gateway.start()
        try:
            await asyncio.sleep(0.05)  # let the registry consumer apply the seed events

            reader, writer = await asyncio.open_connection(
                "127.0.0.1", gateway.adapter("jt808").bound_port
            )
            try:
                registration_body = (
                    (0).to_bytes(2, "big")
                    + (0).to_bytes(2, "big")
                    + b"\x00" * 11
                    + b"\x00" * 30
                    + b"\x00" * 30
                    + b"\x00"
                )
                writer.write(
                    _wire_frame(
                        message_ids.REGISTRATION, terminal_phone, 1, body=registration_body
                    )
                )
                await writer.drain()
                registration_response = PacketParser().parse(
                    (await asyncio.wait_for(reader.read(256), timeout=2.0))[1:-1],
                    received_at=datetime.now(timezone.utc),
                )
                self.assertEqual(registration_response.body[2], 0)  # success
                minted_auth_code = registration_response.body[3:].decode("gbk")

                encoded = encode_gbk_string(minted_auth_code)
                auth_body = bytes([len(encoded)]) + encoded + b"\x00" * 15 + b"\x00" * 20
                writer.write(
                    _wire_frame(message_ids.AUTHENTICATION, terminal_phone, 2, body=auth_body)
                )
                await writer.drain()
                await asyncio.wait_for(reader.read(64), timeout=2.0)  # discard the 0x8001 ack

                # Only *now* does the simulated Business API publish its command - the terminal
                # is genuinely online and authenticated at this point, matching a real deployment
                # (a command published while the device is offline correctly fails "device_offline"
                # instead, see `test_command_sender.py`'s own dedicated coverage of that case).
                redis.entries.append(
                    (
                        "seed-command",
                        {
                            "data": json.dumps(
                                {
                                    "event_id": "evt-command",
                                    "event_type": "Jt1078SignalCommandRequested",
                                    "version": 1,
                                    "occurred_at": "2026-08-11T10:00:00+00:00",
                                    "org_id": "org-1",
                                    "correlation_id": "corr-e2e",
                                    "payload": {
                                        "terminal_id": terminal_phone,
                                        "correlation_id": "corr-e2e",
                                        "command": "live_video_request",
                                        "fields": {
                                            "server_ip": "10.0.0.5",
                                            "tcp_port": 7900,
                                            "udp_port": 7901,
                                            "logical_channel": 1,
                                            "data_type": 0,
                                            "stream_type": 0,
                                        },
                                    },
                                    "aggregate_type": "Device",
                                    "aggregate_id": terminal_phone,
                                }
                            )
                        },
                    )
                )

                data = await asyncio.wait_for(reader.read(256), timeout=2.0)
                command = PacketParser().parse(
                    data[1:-1], received_at=datetime.now(timezone.utc)
                )
                self.assertEqual(command.message_id, message_ids.LIVE_VIDEO_REQUEST)
                self.assertEqual(command.terminal_id, terminal_phone)
            finally:
                writer.close()
        finally:
            await gateway.stop()


if __name__ == "__main__":
    unittest.main()
