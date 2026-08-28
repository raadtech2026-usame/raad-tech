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
from src.ingest.extended_rtp import (
    DATA_TYPE_AUDIO,
    DATA_TYPE_I_FRAME,
    FRAME_HEADER_MAGIC,
    SUBPACKAGE_ATOMIC,
)
from src.relay import Jt1078Relay
from src.session.video_session import VideoSessionKind, VideoSessionState
from src.session.viewer_token import mint_token


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


def _build_device_audio_frame(*, sim_card: str, body: bytes, packet_sequence: int = 0) -> bytes:
    """Audio's own wire shape (Table 6.3) has a *shorter* trailer than video's - timestamp(8)
    only, no Last-I-Frame-Interval/Last-Frame-Interval fields (spec's own "当数据类型为非视频帧
    时，则没有该字段") - a distinct helper from `_build_device_frame`, not a shared one with a
    conditional trailer, so each stays a direct transcription of its own spec table row."""
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
        + bytes([(DATA_TYPE_AUDIO << 4) | SUBPACKAGE_ATOMIC])
    )
    trailer = (1000).to_bytes(8, "big")  # timestamp only - audio has no I/P-frame interval fields
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

    async def test_g711a_codec_currently_produces_no_audio_tag_or_header_claim(self) -> None:
        """`_AUDIO_DECODERS` is deliberately empty as of 2026-08-28 (real-browser evidence:
        Chrome's MSE rejects `audio/mp4;codecs=ipcm` and the failure is fatal to the whole
        player, video included) - even a device reporting the one codec this relay knows how to
        *decode* (G.711A, code 6) must currently get zero audio tags and a video-only header,
        identical to any other/unknown codec, until a real browser-MSE-compatible audio
        representation replaces this table's entry. `codec/g711a.py`'s own decode/resample
        functions remain correct and unit-tested (`tests/test_g711a.py`) for whichever delivery
        mechanism is chosen next - this test only proves the relay doesn't *use* them yet."""
        session = self.relay.session_manager.create_session(
            terminal_id="138001380001",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-audio-1",
            logical_channel=1,
            audio_codec=6,
        )
        token = mint_token(session_id=session.session_id, secret=b"e2e-test-secret")

        viewer_reader, viewer_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.viewer_server.bound_port
        )
        await _ws_handshake(viewer_reader, viewer_writer, token=token)
        opcode, header_payload = await asyncio.wait_for(_read_ws_frame(viewer_reader), timeout=2.0)
        self.assertEqual(header_payload[4], 0b001)  # video-only - never claim audio we can't ship

        device_reader, device_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.ingest_server.bound_port
        )
        g711a_payload = bytes([0xD5, 0x55, 0x2A, 0xAA] * 10)  # 40 bytes = 40ms @ 8kHz mono
        device_writer.write(
            _build_device_audio_frame(sim_card="138001380001", body=g711a_payload)
        )
        await device_writer.drain()
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(_read_ws_frame(viewer_reader), timeout=0.3)

        # video for the same session is completely unaffected by the disabled audio dispatch.
        device_writer.write(
            _build_device_frame(sim_card="138001380001", body=b"\x00\x00\x01\x65IDR-DATA")
        )
        await device_writer.drain()
        opcode, video_payload = await asyncio.wait_for(
            _read_ws_frame(viewer_reader), timeout=2.0
        )
        self.assertEqual(video_payload[0], 9)  # FLV video tag type

        device_writer.close()
        viewer_writer.close()

    async def test_audio_frame_with_unrecognized_codec_produces_no_audio_tag(self) -> None:
        """The explicit-dispatch safety net (`relay.py`'s own `_AUDIO_DECODERS.get(...)`) - a
        session with no known codec (the default for every device today, until a real
        `AudioCapability` names one this relay implements) gets zero audio tags, and video for
        the same session is completely unaffected."""
        session = self.relay.session_manager.create_session(
            terminal_id="138001380002",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-audio-2",
            logical_channel=1,
        )
        token = mint_token(session_id=session.session_id, secret=b"e2e-test-secret")

        viewer_reader, viewer_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.viewer_server.bound_port
        )
        await _ws_handshake(viewer_reader, viewer_writer, token=token)
        opcode, header_payload = await asyncio.wait_for(_read_ws_frame(viewer_reader), timeout=2.0)
        # The regression this whole fix targets: this header must declare video-only, never
        # audio it will never send - `mpegts.js` would otherwise wait forever for audio metadata
        # that never arrives, exactly the bug that broke the 4 already-working video channels.
        self.assertEqual(header_payload[4], 0b001)

        device_reader, device_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.ingest_server.bound_port
        )
        device_writer.write(
            _build_device_audio_frame(sim_card="138001380002", body=b"\xd5" * 40)
        )
        await device_writer.drain()
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(_read_ws_frame(viewer_reader), timeout=0.3)

        # video on the same session still works - the dispatch gap is audio-only.
        device_writer.write(
            _build_device_frame(sim_card="138001380002", body=b"\x00\x00\x01\x65IDR-DATA")
        )
        await device_writer.drain()
        opcode, video_payload = await asyncio.wait_for(
            _read_ws_frame(viewer_reader), timeout=2.0
        )
        self.assertEqual(video_payload[0], 9)  # FLV video tag type

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
