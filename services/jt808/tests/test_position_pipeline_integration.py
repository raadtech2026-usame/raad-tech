"""Full-stack Phase 9.6 integration: real loopback TCP client, real `Jt808Server` (Transport ->
Session -> Codec -> Dispatcher -> Position Handler -> EventPublisher), a scriptable
`DeviceProvisioningPort` double granting authentication so a `DeviceSession` exists, and a
recording `EventPublisher` fake injected via `Jt808Server(event_publisher=...)`. Exercises the
task's own manual-verification scenario end to end: authenticate, then send `0x0200`/`0x0704`
and confirm the position reaches the publisher — matching the resolved architecture (JT808
publishes `DevicePositionReported`, never calls `TrackingApplicationService` directly; see
`src/handlers/location_handler.py`'s module docstring for the conflict record).
"""

import asyncio
import unittest
from datetime import datetime, timezone

from src.config import ServerConfig
from src.events.device_position_reported import DevicePositionReported
from src.handlers.provisioning_port import (
    AuthenticationResult,
    DeviceProvisioningPort,
    RegistrationAuthorization,
    RegistrationResult,
)
from src.protocol.checksum import compute_checksum
from src.protocol.escaping import escape
from src.protocol.header import encode_bcd_phone
from src.protocol.strings import encode_gbk_string
from src.server import Jt808Server
from tests.test_position_body import _build_body

TERMINAL_PHONE = "013800138000"
AUTH_CODE = "GRANTED-CODE-1"


def build_wire_frame(
    message_id: int, terminal_phone: str, serial_no: int, body: bytes = b""
) -> bytes:
    body_attrs = len(body) & 0x03FF
    header = (
        message_id.to_bytes(2, "big")
        + body_attrs.to_bytes(2, "big")
        + encode_bcd_phone(terminal_phone)
        + serial_no.to_bytes(2, "big")
    )
    payload = header + body
    checksum = compute_checksum(payload)
    return bytes([0x7E]) + escape(payload + bytes([checksum])) + bytes([0x7E])


def bulk_body(item_bodies: list[bytes], *, position_data_type: int = 1) -> bytes:
    body = len(item_bodies).to_bytes(2, "big") + bytes([position_data_type])
    for item_body in item_bodies:
        body += len(item_body).to_bytes(2, "big") + item_body
    return body


class GrantingProvisioningPort(DeviceProvisioningPort):
    async def authorize_registration(self, *, terminal_phone, request):
        return RegistrationAuthorization(
            result=RegistrationResult.SUCCESS, auth_code=AUTH_CODE
        )

    async def verify_auth_code(self, *, terminal_phone, auth_code):
        return AuthenticationResult(
            is_valid=(auth_code == AUTH_CODE),
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[DevicePositionReported] = []

    async def publish(self, event: DevicePositionReported) -> None:
        self.published.append(event)


class PositionPipelineIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = ServerConfig(host="127.0.0.1", port=0)
        self.publisher = RecordingEventPublisher()
        self.server = Jt808Server(
            self.config,
            device_provisioning=GrantingProvisioningPort(),
            event_publisher=self.publisher,
        )
        await self.server.start()
        self.port = self.server.bound_port
        self._client_writers: list[asyncio.StreamWriter] = []

    async def asyncTearDown(self) -> None:
        for writer in self._client_writers:
            if not writer.is_closing():
                writer.close()
        await self.server.stop()

    async def _open_client(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self._client_writers.append(writer)
        return reader, writer

    async def _authenticate(
        self, writer: asyncio.StreamWriter, reader: asyncio.StreamReader
    ) -> None:
        writer.write(
            build_wire_frame(
                0x0102, TERMINAL_PHONE, 1, body=encode_gbk_string(AUTH_CODE)
            )
        )
        await writer.drain()
        await asyncio.wait_for(reader.read(64), timeout=2.0)  # discard the 0x8001 ack

    async def test_single_position_report_reaches_publisher(self) -> None:
        reader, writer = await self._open_client()
        await self._authenticate(writer, reader)

        writer.write(build_wire_frame(0x0200, TERMINAL_PHONE, 2, body=_build_body()))
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(len(self.publisher.published), 1)
        event = self.publisher.published[0]
        self.assertEqual(event.vehicle_id, "vehicle-1")
        self.assertEqual(event.organization_id, "org-1")
        self.assertFalse(event.is_backfill)

    async def test_batch_position_report_reaches_publisher_as_backfill(self) -> None:
        reader, writer = await self._open_client()
        await self._authenticate(writer, reader)

        body = bulk_body([_build_body(), _build_body(), _build_body()])
        writer.write(build_wire_frame(0x0704, TERMINAL_PHONE, 2, body=body))
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(len(self.publisher.published), 3)
        self.assertTrue(all(event.is_backfill for event in self.publisher.published))

    async def test_position_report_sends_no_wire_response(self) -> None:
        reader, writer = await self._open_client()
        await self._authenticate(writer, reader)

        writer.write(build_wire_frame(0x0200, TERMINAL_PHONE, 2, body=_build_body()))
        await writer.drain()

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.read(64), timeout=0.3)

    async def test_position_report_before_authentication_is_dropped_not_crashed(
        self,
    ) -> None:
        reader, writer = await self._open_client()  # never authenticates

        writer.write(build_wire_frame(0x0200, TERMINAL_PHONE, 1, body=_build_body()))
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(self.publisher.published, [])
        self.assertEqual(self.server.manager.connection_count, 1)  # connection survives

    async def test_malformed_position_frame_never_reaches_publisher(self) -> None:
        reader, writer = await self._open_client()
        await self._authenticate(writer, reader)

        good_frame = bytearray(
            build_wire_frame(0x0200, TERMINAL_PHONE, 2, body=_build_body())
        )
        good_frame[-2] ^= 0xFF  # corrupt checksum
        writer.write(bytes(good_frame))
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(self.publisher.published, [])
        self.assertEqual(self.server.manager.connection_count, 1)

    async def test_malformed_but_checksum_valid_position_body_does_not_crash_connection(
        self,
    ) -> None:
        reader, writer = await self._open_client()
        await self._authenticate(writer, reader)

        writer.write(build_wire_frame(0x0200, TERMINAL_PHONE, 2, body=b"\x00" * 5))
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(self.publisher.published, [])
        self.assertEqual(
            self.server.manager.connection_count, 1
        )  # survives the handler error

        # connection still works afterward - not left in a broken state
        writer.write(build_wire_frame(0x0200, TERMINAL_PHONE, 3, body=_build_body()))
        await writer.drain()
        await asyncio.sleep(0.1)
        self.assertEqual(len(self.publisher.published), 1)

    async def test_event_ordering_preserved_across_a_batch(self) -> None:
        reader, writer = await self._open_client()
        await self._authenticate(writer, reader)

        item_bodies = [
            _build_body(raw_latitude=n * 1_000_000, raw_longitude=n * 1_000_000)
            for n in (1, 2, 3, 4, 5)
        ]
        writer.write(
            build_wire_frame(0x0704, TERMINAL_PHONE, 2, body=bulk_body(item_bodies))
        )
        await writer.drain()
        await asyncio.sleep(0.1)

        latitudes = [round(event.latitude) for event in self.publisher.published]
        self.assertEqual(latitudes, [1, 2, 3, 4, 5])

    async def test_graceful_shutdown_after_position_reports_leaves_no_connections(
        self,
    ) -> None:
        reader, writer = await self._open_client()
        await self._authenticate(writer, reader)
        writer.write(build_wire_frame(0x0200, TERMINAL_PHONE, 2, body=_build_body()))
        await writer.drain()
        await asyncio.sleep(0.1)

        before_tasks = {t for t in asyncio.all_tasks() if not t.done()}
        await self.server.stop()
        self.assertEqual(self.server.manager.connection_count, 0)
        await asyncio.sleep(0.05)
        after_tasks = {t for t in asyncio.all_tasks() if not t.done()}
        leaked = after_tasks - before_tasks
        leaked = {t for t in leaked if "_sweep_loop" not in repr(t)}
        self.assertEqual(leaked, set(), f"leaked tasks: {leaked}")

        await self.server.start()  # asyncTearDown's own stop() becomes a harmless no-op


if __name__ == "__main__":
    unittest.main()
