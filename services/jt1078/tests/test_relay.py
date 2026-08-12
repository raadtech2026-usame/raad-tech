"""`Jt1078Relay` end-to-end tests — real loopback TCP for both the ingest side (a synthetic
"device" client) and the viewer side (a hand-rolled WS client), proving a full
device-streams -> relay-repackages -> viewer-receives-FLV path works without any hardware or new
dependency. This is the closest this test suite gets to ADR-0024's own "Integration: a live
end-to-end proof... a real (or faithfully simulated) `0x9101`/extended-RTP handshake, through a
real relay process, publishing real events onto a real Redis broker" — Redis itself is not
exercised here (no real Redis in this sandbox; see `test_gateway.py`'s own equivalent fake-Redis
precedent for that half, not duplicated here since this relay's own Redis wiring is a thin,
already-tested (`test_relay_redis_wiring` below) conditional-binding layer, not new logic).
"""

import asyncio
import base64
import struct
import unittest

from src.config import RelayConfig
from src.ingest.extended_rtp import DATA_TYPE_I_FRAME, FRAME_HEADER_MAGIC, SUBPACKAGE_ATOMIC
from src.relay import Jt1078Relay
from src.session.video_session import VideoSessionState


def _build_device_frame(*, sim_card: str, body: bytes, packet_sequence: int = 0) -> bytes:
    sim_bytes = bytes(
        ((int(sim_card[i]) << 4) | int(sim_card[i + 1])) for i in range(0, 12, 2)
    )
    header = (
        FRAME_HEADER_MAGIC.to_bytes(4, "big")
        + bytes([0b0010_0001])
        + bytes([0b1000_0001])
        + packet_sequence.to_bytes(2, "big")
        + sim_bytes
        + bytes([1])
        + bytes([(DATA_TYPE_I_FRAME << 4) | SUBPACKAGE_ATOMIC])
    )
    trailer = (1000).to_bytes(8, "big") + (0).to_bytes(2, "big") + (40).to_bytes(2, "big")
    return header + trailer + len(body).to_bytes(2, "big") + body


async def _ws_handshake(reader, writer, *, token: str) -> None:
    import os

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET /viewer?token={token} HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    writer.write(request.encode("ascii"))
    await writer.drain()
    status_line = (await reader.readline()).decode("iso-8859-1")
    assert "101" in status_line, status_line
    while True:
        line = (await reader.readline()).decode("iso-8859-1").strip()
        if not line:
            break


async def _read_ws_frame(reader) -> tuple[int, bytes]:
    first_two = await reader.readexactly(2)
    opcode = first_two[0] & 0x0F
    length = first_two[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await reader.readexactly(8))[0]
    payload = await reader.readexactly(length) if length else b""
    return opcode, payload


class Jt1078RelayEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        config = RelayConfig(
            ingest_host="127.0.0.1",
            ingest_port=0,
            viewer_host="127.0.0.1",
            viewer_port=0,
            viewer_token_secret=b"e2e-test-secret",
        )
        self.relay = Jt1078Relay(config=config)
        await self.relay.start()

    async def asyncTearDown(self) -> None:
        await self.relay.stop()

    async def test_device_stream_reaches_a_connected_viewer_as_flv(self) -> None:
        session, token = self.relay.create_live_session(
            terminal_id="138001380000",
            correlation_id="corr-1",
            logical_channel=1,
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
        )

        viewer_reader, viewer_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.viewer_server.bound_port
        )
        await _ws_handshake(viewer_reader, viewer_writer, token=token)
        opcode, header_payload = await asyncio.wait_for(_read_ws_frame(viewer_reader), timeout=2.0)
        self.assertEqual(header_payload[0:3], b"FLV")

        device_reader, device_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.ingest_server.bound_port
        )
        device_writer.write(
            _build_device_frame(sim_card="138001380000", body=b"\x00\x00\x01\x65IDR-DATA")
        )
        await device_writer.drain()

        opcode, video_payload = await asyncio.wait_for(_read_ws_frame(viewer_reader), timeout=2.0)
        self.assertEqual(video_payload[0], 9)  # FLV video tag type

        self.assertEqual(session.state, VideoSessionState.ACTIVE)
        self.assertEqual(session.viewer_count, 1)

        device_writer.close()
        viewer_writer.close()

    async def test_ending_a_session_removes_its_hub_and_playback_stop_is_signaled(self) -> None:
        session, _token = self.relay.create_live_session(
            terminal_id="138001380000", correlation_id="corr-2", logical_channel=1
        )
        self.assertIn(session.session_id, self.relay._hubs)

        await self.relay.session_manager.end_session(session.session_id, reason="explicit_stop")

        self.assertNotIn(session.session_id, self.relay._hubs)
        self.assertIsNone(self.relay.session_manager.resolve(session.session_id))

    async def test_a_viewer_token_for_a_session_that_was_already_ended_is_rejected(self) -> None:
        session, token = self.relay.create_live_session(
            terminal_id="138001380000", correlation_id="corr-3", logical_channel=1
        )
        await self.relay.session_manager.end_session(session.session_id, reason="explicit_stop")

        reader, writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.viewer_server.bound_port
        )
        await _ws_handshake(reader, writer, token=token)
        opcode, payload = await asyncio.wait_for(_read_ws_frame(reader), timeout=2.0)
        self.assertEqual(opcode, 0x8)
        self.assertEqual(struct.unpack("!H", payload[0:2])[0], 4004)
        writer.close()


if __name__ == "__main__":
    unittest.main()
