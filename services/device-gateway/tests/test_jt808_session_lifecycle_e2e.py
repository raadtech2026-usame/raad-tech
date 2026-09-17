"""End-to-end JT/T 808 session lifecycle through the real `DeviceGateway` composition root
(2026-09-17 fixes). Everything below is production code except the transport's far end (a
loopback TCP client standing in for the MDVR) and Redis (the in-memory `FakeRedis` from
`test_gateway.py`): the real `RedisDeviceRegistryConsumer` builds the registry from seeded
`fleet_device` events, the real `ProjectionBackedJt808ProvisioningPort` mints and verifies the
auth code, the real `RedisDeviceSessionRegistry`/`RedisEventPublisher`/
`RedisLatestPositionWriter` run against the fake.

Covers the two defects found in the 2026-09-17 investigation, over the wire:

1. The auth code from `0x8100` keeps authenticating on every later connection, as the supplier
   spec §7.1.1–§7.1.3 requires; before the fix a verified code was deleted, so the second or
   third reconnect failed closed.
2. `0x0200` is answered with `0x8001`, echoing its serial number and message ID, after the
   position has been published and cached; before the fix it was never answered (spec §7.8.1).
"""

import asyncio
import json
import unittest
from datetime import datetime, timezone

from src.broker_config import BrokerConfig
from src.cache_config import CacheConfig
from src.gateway import DeviceGateway
from src.vendors.jt808.config import ServerConfig as Jt808Config
from src.vendors.jt808.dispatcher import message_ids
from src.vendors.jt808.protocol.framing import FrameBuffer
from src.vendors.jt808.protocol.parser import PacketParser
from src.vendors.jt808.protocol.strings import encode_gbk_string
from src.vendors.lsz.config import MdvrServerConfig as LszConfig
from tests.test_gateway import FakeRedis, _device_registered_entries, _wire_frame
from tests.test_position_body import _build_body

TERMINAL_PHONE = "00000000014482607571"
DEVICE_ID = "device-1"
VEHICLE_ID = "vehicle-1"
ORG_ID = "org-1"

_REGISTRATION_BODY = (
    (0).to_bytes(2, "big")
    + (0).to_bytes(2, "big")
    + b"\x00" * 11
    + b"\x00" * 30
    + b"\x00" * 30
    + b"\x00"
)


def _auth_body(code: str) -> bytes:
    encoded = encode_gbk_string(code)
    return bytes([len(encoded)]) + encoded + b"\x00" * 15 + b"\x00" * 20


class _Terminal:
    """One TCP connection from the simulated MDVR's side, reading whole frames off the socket."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._frames = FrameBuffer(max_frame_size=8192)
        self._pending: list[bytes] = []
        self._serial = 0

    async def send(self, message_id: int, body: bytes = b"") -> int:
        self._serial += 1
        self._writer.write(_wire_frame(message_id, TERMINAL_PHONE, self._serial, body=body))
        await self._writer.drain()
        return self._serial

    async def receive(self):
        while not self._pending:
            chunk = await asyncio.wait_for(self._reader.read(256), timeout=2.0)
            if not chunk:
                return None  # the platform closed the connection
            self._pending.extend(self._frames.feed(chunk))
        return PacketParser().parse(self._pending.pop(0), received_at=datetime.now(timezone.utc))

    async def close(self) -> None:
        self._writer.close()


def _general_response_fields(frame) -> tuple[int, int, int]:
    return (
        int.from_bytes(frame.body[0:2], "big"),
        int.from_bytes(frame.body[2:4], "big"),
        frame.body[4],
    )


class Jt808SessionLifecycleEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.redis = FakeRedis()
        self.redis.entries.extend(
            _device_registered_entries(
                terminal_id=TERMINAL_PHONE,
                serial_number="00007",
                device_id=DEVICE_ID,
                vehicle_id=VEHICLE_ID,
                org_id=ORG_ID,
            )
        )
        self.redis._next_id = 4
        self.gateway = DeviceGateway(
            broker_config=BrokerConfig(),
            cache_config=CacheConfig(),
            redis_client=self.redis,
            cache_redis_client=self.redis,
            jt808_config=Jt808Config(host="127.0.0.1", port=0),
            lsz_config=LszConfig(host="127.0.0.1", port=0),
        )
        await self.gateway.start()
        await asyncio.sleep(0.05)  # let the registry consumer settle on the seeded events
        self._terminals: list[_Terminal] = []

    async def asyncTearDown(self) -> None:
        for terminal in self._terminals:
            await terminal.close()
        await self.gateway.stop()

    async def _connect(self) -> _Terminal:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", self.gateway.adapter("jt808").bound_port
        )
        terminal = _Terminal(reader, writer)
        self._terminals.append(terminal)
        return terminal

    async def _register(self, terminal: _Terminal) -> str:
        await terminal.send(message_ids.REGISTRATION, _REGISTRATION_BODY)
        response = await terminal.receive()
        self.assertEqual(response.message_id, 0x8100)
        self.assertEqual(response.body[2], 0)  # registration success
        return response.body[3:].decode("gbk")

    async def _authenticate(self, terminal: _Terminal, code: str) -> int:
        serial = await terminal.send(message_ids.AUTHENTICATION, _auth_body(code))
        response = await terminal.receive()
        self.assertIsNotNone(response, "connection closed instead of answering 0x0102")
        self.assertEqual(response.message_id, 0x8001)
        self.assertEqual(_general_response_fields(response)[:2], (serial, 0x0102))
        return response.body[4]

    def _published(self, event_type: str) -> list[dict]:
        events = [json.loads(fields["data"]) for _, fields in self.redis.entries]
        return [event for event in events if event["event_type"] == event_type]

    async def test_register_authenticate_heartbeat_location_ack_then_reconnect_with_same_code(
        self,
    ) -> None:
        # --- First connection: the full registration handshake -------------------------------
        first = await self._connect()
        code = await self._register(first)
        self.assertEqual(await self._authenticate(first, code), 0)

        heartbeat_serial = await first.send(message_ids.HEARTBEAT)
        heartbeat_ack = await first.receive()
        self.assertEqual(
            _general_response_fields(heartbeat_ack), (heartbeat_serial, 0x0002, 0)
        )

        location_serial = await first.send(message_ids.LOCATION_REPORT, _build_body())
        location_ack = await first.receive()
        self.assertEqual(location_ack.message_id, 0x8001)
        self.assertEqual(location_ack.terminal_id, TERMINAL_PHONE)
        self.assertEqual(
            _general_response_fields(location_ack), (location_serial, 0x0200, 0)
        )

        # The acknowledged position really went through GPS processing: published to the
        # broker stream and written to the current-position snapshot the backend reads.
        positions = self._published("DevicePositionReported")
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["payload"]["vehicle_id"], VEHICLE_ID)
        self.assertTrue(positions[0]["payload"]["is_gps_valid"])
        snapshot = json.loads(await self.redis.get(f"vehicle:{VEHICLE_ID}:last"))
        self.assertEqual(snapshot["device_id"], DEVICE_ID)
        self.assertEqual(len(self._published("DeviceOnline")), 1)

        await first.close()
        await asyncio.sleep(0.05)

        # --- Reconnects: no 0x0100, the stored code straight away (spec §7.1.2) ---------------
        for reconnect in range(1, 4):
            terminal = await self._connect()
            self.assertEqual(
                await self._authenticate(terminal, code),
                0,
                f"reconnect {reconnect} was rejected with the device's own stored code",
            )
            serial = await terminal.send(message_ids.LOCATION_REPORT, _build_body())
            ack = await terminal.receive()
            self.assertEqual(_general_response_fields(ack), (serial, 0x0200, 0))
            await terminal.close()
            await asyncio.sleep(0.05)

        self.assertEqual(len(self._published("DevicePositionReported")), 4)
        # One mint, one stored hash — the gateway reading its own DeviceAuthCodeIssued back off
        # the stream must not duplicate it.
        record = self.gateway.registry_projection.lookup_by_terminal_id(TERMINAL_PHONE)
        self.assertEqual(len(record.auth_key_hashes), 1)

    async def test_auth_code_and_its_hash_never_reach_the_logs_even_at_debug(self) -> None:
        """`DEVICE_GATEWAY_LOG_LEVEL=DEBUG` is now actually reachable in deployment, so every log
        record emitted during a full handshake, a location report and a reconnect is captured at
        DEBUG and checked for the plaintext auth code and its stored hash."""
        with self.assertLogs(level="DEBUG") as captured:
            first = await self._connect()
            code = await self._register(first)
            self.assertEqual(await self._authenticate(first, code), 0)
            await first.send(message_ids.LOCATION_REPORT, _build_body())
            await first.receive()
            await first.close()
            await asyncio.sleep(0.05)

            second = await self._connect()
            self.assertEqual(await self._authenticate(second, code), 0)
            await asyncio.sleep(0.05)

        record = self.gateway.registry_projection.lookup_by_terminal_id(TERMINAL_PHONE)
        secrets = [code, *record.auth_key_hashes]
        rendered = [
            f"{r.getMessage()} {getattr(r, 'extra_fields', {})!r}" for r in captured.records
        ]
        self.assertTrue(any("response_frame_sent" in line for line in rendered))
        for line in rendered:
            for secret in secrets:
                self.assertNotIn(secret, line)

    async def test_wrong_code_is_rejected_and_closed_even_after_the_real_code_has_been_reused(
        self,
    ) -> None:
        first = await self._connect()
        code = await self._register(first)
        self.assertEqual(await self._authenticate(first, code), 0)
        await first.close()
        await asyncio.sleep(0.05)

        second = await self._connect()
        self.assertEqual(await self._authenticate(second, code), 0)
        await second.close()
        await asyncio.sleep(0.05)

        intruder = await self._connect()
        self.assertEqual(await self._authenticate(intruder, "NOT-THE-CODE"), 1)  # failure
        self.assertIsNone(await intruder.receive())  # and the platform closed the socket

        position_count = len(self._published("DevicePositionReported"))
        self.assertEqual(position_count, 0)


if __name__ == "__main__":
    unittest.main()
