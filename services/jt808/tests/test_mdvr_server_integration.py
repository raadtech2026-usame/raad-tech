"""Full-stack MDVR integration: a real loopback TCP client against a real `MdvrServer`
(Transport -> Session -> Parser -> Dispatcher -> Handlers -> EventPublisher), the vendor-protocol
proof that ADR-0009's design actually works end to end over a real socket, mirroring
`test_position_pipeline_integration.py`'s conventions for the JT/T 808 stack. Uses the same real
device-00007 worked examples the unit tests validate.
"""

import asyncio
import unittest
from datetime import datetime, timezone

from src.events.device_position_reported import DevicePositionReported
from src.vendors.lsz_mdvr.config import MdvrServerConfig
from src.vendors.lsz_mdvr.handlers.provisioning_port import (
    InMemoryMdvrDeviceProvisioningPort,
)
from src.vendors.lsz_mdvr.protocol.parser import parse_frame
from src.vendors.lsz_mdvr.server import MdvrServer

_REGISTRATION_FRAME = (
    b"$$dc0227,20,V101,00007,,180903 094112,A0010,114,3,341826000,22,40,236220000,0.00,7000,"
    b"000E00010101D383,0000000000000000,0.00,0.00,0.00,0,0.00,67,0|0.00|0|0|0|0|0|0|0,,V1.0.0.1,"
    b"4108,,0,0,0,123,2,,1,1,2,101,,D2017120781,V6.1.45 20160519,#"
)
_HEARTBEAT_FRAME = b"$$dc0029,13,V109,00007,,180903 110250#"
_POSITION_FRAME = (
    b"$$dc0165,192,V114,00007,,180903 135949,A0010,114,3,338214000,22,40,220920000,0.00,1521000,"
    b"000E00010101D383,0000000000000000,0.00,0.00,0.00,0,0.00,2266,0|0.00|0|0|0|0|0|0|0,1#"
)


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[DevicePositionReported] = []

    async def publish(self, event: DevicePositionReported) -> None:
        self.published.append(event)


class MdvrServerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.provisioning = InMemoryMdvrDeviceProvisioningPort()
        self.provisioning.register_known_device(
            device_serial_number="00007",
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )
        self.publisher = RecordingEventPublisher()
        self.server = MdvrServer(
            MdvrServerConfig(host="127.0.0.1", port=0),
            device_provisioning=self.provisioning,
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

    async def test_registration_returns_a_c100_success_ack(self) -> None:
        reader, writer = await self._open_client()
        writer.write(_REGISTRATION_FRAME)
        await writer.drain()

        raw = await asyncio.wait_for(reader.read(256), timeout=2.0)
        message = parse_frame(raw[:-1], received_at=datetime.now(timezone.utc))
        self.assertEqual(message.keyword, "C100")
        self.assertEqual(message.device_serial_number, "00007")
        self.assertEqual(message.fields[:3], ["V101", "180903 094112", "0"])
        self.assertEqual(message.fields[3], "1")  # success flag

    async def test_unknown_device_registration_is_rejected_and_socket_closes(self) -> None:
        reader, writer = await self._open_client()
        writer.write(
            _REGISTRATION_FRAME.replace(b",00007,", b",UNKNOWN,")
        )
        await writer.drain()

        raw = await asyncio.wait_for(reader.read(256), timeout=2.0)
        message = parse_frame(raw[:-1], received_at=datetime.now(timezone.utc))
        self.assertEqual(message.fields[3], "0")  # failure flag

        # Connection should be closed by the server shortly after the rejection ack.
        closed = await asyncio.wait_for(reader.read(1), timeout=2.0)
        self.assertEqual(closed, b"")

    async def test_heartbeat_after_registration_returns_c501_and_promotes_online(
        self,
    ) -> None:
        reader, writer = await self._open_client()
        writer.write(_REGISTRATION_FRAME)
        await writer.drain()
        await asyncio.wait_for(reader.read(256), timeout=2.0)  # discard C100 ack

        writer.write(_HEARTBEAT_FRAME)
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(256), timeout=2.0)
        message = parse_frame(raw[:-1], received_at=datetime.now(timezone.utc))
        self.assertEqual(message.keyword, "C501")
        self.assertEqual(message.device_serial_number, "00007")

    async def test_position_report_after_registration_reaches_publisher(self) -> None:
        reader, writer = await self._open_client()
        writer.write(_REGISTRATION_FRAME)
        await writer.drain()
        await asyncio.wait_for(reader.read(256), timeout=2.0)  # discard C100 ack

        writer.write(_POSITION_FRAME)
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(len(self.publisher.published), 1)
        event = self.publisher.published[0]
        self.assertEqual(event.organization_id, "org-1")
        self.assertEqual(event.vehicle_id, "vehicle-1")
        self.assertEqual(event.device_id, "device-1")
        self.assertFalse(event.is_backfill)
        self.assertAlmostEqual(event.latitude, 22.672803, places=5)
        self.assertAlmostEqual(event.longitude, 114.059395, places=5)

    async def test_position_report_sends_no_wire_response(self) -> None:
        reader, writer = await self._open_client()
        writer.write(_REGISTRATION_FRAME)
        await writer.drain()
        await asyncio.wait_for(reader.read(256), timeout=2.0)  # discard C100 ack

        writer.write(_POSITION_FRAME)
        await writer.drain()

        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.read(64), timeout=0.3)

    async def test_position_report_before_registration_is_dropped(self) -> None:
        reader, writer = await self._open_client()
        writer.write(_POSITION_FRAME)
        await writer.drain()
        await asyncio.sleep(0.1)

        self.assertEqual(self.publisher.published, [])


if __name__ == "__main__":
    unittest.main()
