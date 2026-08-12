"""Full-stack JT/T 1078 video-signaling-forwarding integration: a real loopback TCP client
authenticates, `Jt808Server.command_sender.send(...)` pushes a real `0x9101`/`0x9205` frame out
over that live connection (the same path `RedisVideoSignalingConsumer` would drive from a real
broker event), the "terminal" (test client) reads and decodes it, replies with `0x0001`/`0x1205`,
and the resulting `DeviceCommandResult`/`DeviceResourceListReported` events are observed on the
injected `EventPublisher` — proving the whole forward-command / correlate-response loop works
end to end against the real wire codec, without any hardware.
"""

import asyncio
import unittest
from datetime import datetime, timezone

from src.events.device_command_result import DeviceCommandResult
from src.events.device_resource_list_reported import DeviceResourceListReported
from src.vendors.jt808.commands.video_signaling import (
    LiveVideoRequest,
    QueryResourceList,
    encode_live_video_request,
    encode_query_resource_list,
)
from src.vendors.jt808.config import ServerConfig
from src.vendors.jt808.dispatcher import message_ids
from src.vendors.jt808.handlers.provisioning_port import (
    AuthenticationResult,
    DeviceProvisioningPort,
    RegistrationAuthorization,
    RegistrationResult,
)
from src.vendors.jt808.protocol.bcd_datetime import encode_bcd_datetime
from src.vendors.jt808.protocol.checksum import compute_checksum
from src.vendors.jt808.protocol.escaping import escape
from src.vendors.jt808.protocol.header import encode_bcd_phone
from src.vendors.jt808.protocol.parser import PacketParser
from src.vendors.jt808.protocol.strings import encode_gbk_string
from src.vendors.jt808.server import Jt808Server

TERMINAL_PHONE = "00000000013800138000"
AUTH_CODE = "GRANTED-CODE-1"


def build_wire_frame(
    message_id: int, terminal_phone: str, serial_no: int, body: bytes = b""
) -> bytes:
    body_attrs = (len(body) & 0x03FF) | (1 << 14)
    header = (
        message_id.to_bytes(2, "big")
        + body_attrs.to_bytes(2, "big")
        + bytes([0x01])
        + encode_bcd_phone(terminal_phone)
        + serial_no.to_bytes(2, "big")
    )
    payload = header + body
    checksum = compute_checksum(payload)
    return bytes([0x7E]) + escape(payload + bytes([checksum])) + bytes([0x7E])


def auth_body(code: str) -> bytes:
    encoded = encode_gbk_string(code)
    return bytes([len(encoded)]) + encoded + b"\x00" * 15 + b"\x00" * 20


def general_response_body(*, original_serial_no: int, original_message_id: int, result: int) -> bytes:
    return (
        original_serial_no.to_bytes(2, "big")
        + original_message_id.to_bytes(2, "big")
        + bytes([result])
    )


class GrantingProvisioningPort(DeviceProvisioningPort):
    async def authorize_registration(self, *, terminal_phone, request):
        return RegistrationAuthorization(result=RegistrationResult.SUCCESS, auth_code=AUTH_CODE)

    async def verify_auth_code(self, *, terminal_phone, auth_code):
        return AuthenticationResult(
            is_valid=(auth_code == AUTH_CODE),
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)

    def of_type(self, cls):
        return [e for e in self.published if isinstance(e, cls)]


class VideoSignalingIntegrationTests(unittest.IsolatedAsyncioTestCase):
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
        self.parser = PacketParser()

    async def asyncTearDown(self) -> None:
        for writer in self._client_writers:
            if not writer.is_closing():
                writer.close()
        await self.server.stop()

    async def _open_authenticated_client(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self._client_writers.append(writer)
        writer.write(build_wire_frame(0x0102, TERMINAL_PHONE, 1, body=auth_body(AUTH_CODE)))
        await writer.drain()
        await asyncio.wait_for(reader.read(64), timeout=2.0)  # discard the 0x8001 ack
        return reader, writer

    async def test_live_video_request_reaches_the_terminal_and_ack_is_correlated(self) -> None:
        _reader, writer = await self._open_authenticated_client()

        request = LiveVideoRequest(
            server_ip="10.0.0.5",
            tcp_port=7900,
            udp_port=7901,
            logical_channel=1,
            data_type=0,
            stream_type=0,
        )
        sent = await self.server.command_sender.send(
            terminal_id=TERMINAL_PHONE,
            message_id=message_ids.LIVE_VIDEO_REQUEST,
            body=encode_live_video_request(request),
            correlation_id="corr-live-1",
        )
        self.assertTrue(sent)

        data = await asyncio.wait_for(_reader.read(256), timeout=2.0)
        command = self.parser.parse(data[1:-1], received_at=datetime.now(timezone.utc))
        self.assertEqual(command.message_id, message_ids.LIVE_VIDEO_REQUEST)

        # Terminal acks the command it just received (echoing the command's own serial_no).
        writer.write(
            build_wire_frame(
                0x0001,
                TERMINAL_PHONE,
                2,
                body=general_response_body(
                    original_serial_no=command.serial_no,
                    original_message_id=command.message_id,
                    result=0,
                ),
            )
        )
        await writer.drain()
        await asyncio.sleep(0.1)

        results = self.publisher.of_type(DeviceCommandResult)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)
        self.assertEqual(results[0].correlation_id, "corr-live-1")
        self.assertEqual(results[0].reason, "acknowledged")

    async def test_command_to_offline_terminal_publishes_device_offline_result(self) -> None:
        sent = await self.server.command_sender.send(
            terminal_id="00000000099999999999",
            message_id=message_ids.LIVE_VIDEO_CONTROL,
            body=b"\x00\x00\x00\x00",
            correlation_id="corr-offline",
        )
        self.assertFalse(sent)

        results = self.publisher.of_type(DeviceCommandResult)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertEqual(results[0].reason, "device_offline")

    async def test_query_resource_list_round_trip_publishes_resource_list_reported(self) -> None:
        _reader, writer = await self._open_authenticated_client()

        query = QueryResourceList(
            logical_channel=0,
            start_time=None,
            end_time=None,
            alarm_flag_filter=0,
            resource_type=3,
            stream_type=0,
            storage_type=0,
        )
        await self.server.command_sender.send(
            terminal_id=TERMINAL_PHONE,
            message_id=message_ids.QUERY_RESOURCE_LIST,
            body=encode_query_resource_list(query),
            correlation_id="corr-resources",
        )

        data = await asyncio.wait_for(_reader.read(256), timeout=2.0)
        command = self.parser.parse(data[1:-1], received_at=datetime.now(timezone.utc))
        self.assertEqual(command.message_id, message_ids.QUERY_RESOURCE_LIST)

        start = datetime(2026, 8, 11, 8, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 8, 11, 9, 0, 0, tzinfo=timezone.utc)
        item = (
            bytes([1])
            + encode_bcd_datetime(start)
            + encode_bcd_datetime(end)
            + (0).to_bytes(8, "big")
            + bytes([2, 0, 0])
            + (4096).to_bytes(4, "big")
        )
        report_body = command.serial_no.to_bytes(2, "big") + (1).to_bytes(4, "big") + item
        writer.write(build_wire_frame(0x1205, TERMINAL_PHONE, 5, body=report_body))
        await writer.drain()
        await asyncio.sleep(0.1)

        reports = self.publisher.of_type(DeviceResourceListReported)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].correlation_id, "corr-resources")
        self.assertEqual(reports[0].total_resource_count, 1)
        self.assertEqual(reports[0].items[0]["file_size_bytes"], 4096)


if __name__ == "__main__":
    unittest.main()
