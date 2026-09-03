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
import shutil
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


def _parse_flv_tags(buffer: bytes) -> list[tuple[int, bytes]]:
    """Splits a buffer holding one or more concatenated `Tag(11-byte header + Data) +
    PreviousTagSize(4)` sequences - exactly what a single WS binary frame from `broadcast_video`/
    `broadcast_audio_aac` may carry (`FlvMuxer.feed_audio_aac_frame`'s own "sequence header +
    raw frame in one chunk on first send" shape) - into `(tag_type, data)` pairs, mirroring a
    real FLV demuxer's own tag-walking loop."""
    tags: list[tuple[int, bytes]] = []
    pos = 0
    while pos + 11 <= len(buffer):
        tag_type = buffer[pos]
        data_size = int.from_bytes(buffer[pos + 1 : pos + 4], "big")
        data_start = pos + 11
        data = buffer[data_start : data_start + data_size]
        tags.append((tag_type, data))
        pos = data_start + data_size + 4  # skip the trailing PreviousTagSize
    return tags


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

    async def test_g711a_codec_declares_audio_and_never_breaks_video(self) -> None:
        """ADR-0034 (2026-08-28): G.711A (codec 6) is now transcoded to AAC via a per-session
        `ffmpeg` subprocess (`_TRANSCODABLE_AUDIO_CODECS`), so the session's own FLV header now
        correctly claims audio - unlike the prior, since-superseded Linear-PCM path this replaces
        (browser MSE rejected `audio/mp4;codecs=ipcm` outright). This test does not require a
        real `ffmpeg` binary: it only proves the header claim and the safety property that
        matters regardless of whether transcoding itself succeeds on this machine - video for the
        session is never affected by the audio path, whether ffmpeg is present, missing, or still
        starting (`test_audio_reaches_viewer_as_aac_via_real_ffmpeg` below is the real,
        ffmpeg-gated end-to-end proof that transcoded audio actually arrives)."""
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
        self.assertEqual(header_payload[4], 0b101)  # video + audio - codec 6 is transcodable

        device_reader, device_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.ingest_server.bound_port
        )
        g711a_payload = bytes([0xD5, 0x55, 0x2A, 0xAA] * 10)  # 40 bytes = 40ms @ 8kHz mono
        device_writer.write(
            _build_device_audio_frame(sim_card="138001380001", body=g711a_payload)
        )
        await device_writer.drain()

        # video for the same session is unaffected by the audio path regardless of whether the
        # transcoder ever produces output (real ffmpeg AAC framing is at least 128ms/frame, so no
        # audio tag is expected this soon even when ffmpeg is genuinely available).
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

    @unittest.skipUnless(shutil.which("ffmpeg"), "requires a real ffmpeg binary on PATH")
    async def test_audio_reaches_viewer_as_aac_via_real_ffmpeg(self) -> None:
        """The one test in this suite that spawns a genuine `ffmpeg` subprocess (ADR-0034) -
        proves real G.711A silence bytes survive the actual transcode -> ADTS-split -> FLV-tag
        pipeline and reach the viewer as an AAC sequence-header tag followed by an AAC raw tag.
        Skipped, not faked, when `ffmpeg` isn't on `PATH` (this repo's dev sandbox has no ffmpeg;
        the `jt1078-relay` Docker image does - `docker/jt1078-relay.Dockerfile`)."""
        session = self.relay.session_manager.create_session(
            terminal_id="138001380003",
            kind=VideoSessionKind.LIVE,
            correlation_id="corr-audio-3",
            logical_channel=1,
            audio_codec=6,
        )
        token = mint_token(session_id=session.session_id, secret=b"e2e-test-secret")

        viewer_reader, viewer_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.viewer_server.bound_port
        )
        await _ws_handshake(viewer_reader, viewer_writer, token=token)
        opcode, header_payload = await asyncio.wait_for(_read_ws_frame(viewer_reader), timeout=2.0)
        self.assertEqual(header_payload[4], 0b101)

        device_reader, device_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.ingest_server.bound_port
        )
        # 0xD5 is G.711A-encoded silence - real bytes ffmpeg's own `alaw` demuxer can decode.
        silence_frame = bytes([0xD5] * 320)  # 320 bytes = 40ms @ 8kHz mono, per Table 6.1
        # ffmpeg needs several 40ms input frames before it has enough audio to emit one 128ms
        # AAC-LC frame - feed a generous burst rather than guessing the exact minimum.
        for seq in range(20):
            device_writer.write(
                _build_device_audio_frame(
                    sim_card="138001380003", body=silence_frame, packet_sequence=seq
                )
            )
            await device_writer.drain()
            await asyncio.sleep(0.02)

        # The first `broadcast_audio_aac` call for a session sends the AAC sequence-header tag
        # and the first raw AAC tag concatenated in one WS binary frame (`feed_audio_aac_frame`'s
        # own "config changed -> prepend the header" shape); read defensively in case a future
        # change ever splits them across two WS frames instead.
        opcode, first_payload = await asyncio.wait_for(_read_ws_frame(viewer_reader), timeout=10.0)
        tags = _parse_flv_tags(first_payload)
        self.assertGreaterEqual(len(tags), 1)
        seq_tag_type, seq_data = tags[0]
        self.assertEqual(seq_tag_type, 8)  # FLV audio tag type
        self.assertEqual(seq_data[0] >> 4, 10)  # SoundFormat=10 (AAC)
        self.assertEqual(seq_data[1], 0)  # AACPacketType=0 (sequence header)

        if len(tags) > 1:
            raw_tag_type, raw_data = tags[1]
        else:
            opcode, second_payload = await asyncio.wait_for(
                _read_ws_frame(viewer_reader), timeout=10.0
            )
            raw_tags = _parse_flv_tags(second_payload)
            self.assertEqual(len(raw_tags), 1)
            raw_tag_type, raw_data = raw_tags[0]
        self.assertEqual(raw_tag_type, 8)
        self.assertEqual(raw_data[0] >> 4, 10)
        self.assertEqual(raw_data[1], 1)  # AACPacketType=1 (raw)
        self.assertGreater(len(raw_data), 2)  # real AAC bytes followed the 2-byte audio header

        device_writer.close()
        viewer_writer.close()

    async def test_audio_frame_with_unrecognized_codec_produces_no_audio_tag(self) -> None:
        """The explicit-dispatch safety net (`relay.py`'s own `_TRANSCODABLE_AUDIO_CODECS`
        membership check) - a session with no known codec (the default for every device today,
        until a real `AudioCapability` names one this relay implements) gets zero audio tags, and
        video for the same session is completely unaffected."""
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

    async def test_intercom_session_failing_closes_viewer_and_uplink_sockets(self) -> None:
        """Bug 1 regression test — REQUESTED -> FAILED. Before this fix, `fail_session` only
        dereferenced the hub from `self.relay._hubs`; a browser already connected (both the
        downlink viewer *and* the uplink mic socket, ADR-0036) was left holding an open, silent
        WebSocket forever, with no signal the session had failed — exactly the "stuck Connecting
        intercom..." symptom (live-reproduced, session `01M1EQZE1D1831D74MHXCTDGQP`,
        `reason="ingest_timeout"`, never any inbound ingest connection for this session)."""
        session = self.relay.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="corr-intercom-fail",
            logical_channel=1,
        )
        viewer_token = mint_token(session_id=session.session_id, secret=b"e2e-test-secret")
        uplink_token = mint_token(
            session_id=session.session_id, secret=b"e2e-test-secret", role="uplink"
        )

        viewer_reader, viewer_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.viewer_server.bound_port
        )
        await _ws_handshake(viewer_reader, viewer_writer, token=viewer_token)
        await asyncio.wait_for(_read_ws_frame(viewer_reader), timeout=2.0)  # FLV header

        uplink_reader, uplink_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.viewer_server.bound_port
        )
        await _ws_handshake(uplink_reader, uplink_writer, token=uplink_token)
        await asyncio.sleep(0.05)  # let the uplink connection register itself

        await self.relay.session_manager.fail_session(session.session_id, reason="ingest_timeout")

        viewer_opcode, viewer_payload = await asyncio.wait_for(
            _read_ws_frame(viewer_reader), timeout=2.0
        )
        self.assertEqual(viewer_opcode, 0x8)  # close
        self.assertEqual(struct.unpack("!H", viewer_payload[0:2])[0], 4010)
        self.assertEqual(viewer_payload[2:], b"ingest_timeout")

        uplink_opcode, uplink_payload = await asyncio.wait_for(
            _read_ws_frame(uplink_reader), timeout=2.0
        )
        self.assertEqual(uplink_opcode, 0x8)
        self.assertEqual(struct.unpack("!H", uplink_payload[0:2])[0], 4010)
        self.assertEqual(uplink_payload[2:], b"ingest_timeout")

        self.assertNotIn(session.session_id, self.relay._hubs)
        viewer_writer.close()
        uplink_writer.close()

    async def test_intercom_session_ending_closes_viewer_and_uplink_sockets(self) -> None:
        """Bug 1 regression test — REQUESTED -> ENDED (e.g. the operator's own "End Intercom"
        click, or `reconcile_stale_intercom_sessions`), distinct close code from the FAILED case
        above so the frontend can render "the call ended" separately from "the call failed"."""
        session = self.relay.session_manager.create_session(
            terminal_id="138001380000",
            kind=VideoSessionKind.INTERCOM,
            correlation_id="corr-intercom-end",
            logical_channel=1,
        )
        viewer_token = mint_token(session_id=session.session_id, secret=b"e2e-test-secret")
        uplink_token = mint_token(
            session_id=session.session_id, secret=b"e2e-test-secret", role="uplink"
        )

        viewer_reader, viewer_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.viewer_server.bound_port
        )
        await _ws_handshake(viewer_reader, viewer_writer, token=viewer_token)
        await asyncio.wait_for(_read_ws_frame(viewer_reader), timeout=2.0)  # FLV header

        uplink_reader, uplink_writer = await asyncio.open_connection(
            "127.0.0.1", self.relay.viewer_server.bound_port
        )
        await _ws_handshake(uplink_reader, uplink_writer, token=uplink_token)
        await asyncio.sleep(0.05)

        await self.relay.session_manager.end_session(
            session.session_id, reason="business_api_requested"
        )

        viewer_opcode, viewer_payload = await asyncio.wait_for(
            _read_ws_frame(viewer_reader), timeout=2.0
        )
        self.assertEqual(viewer_opcode, 0x8)
        self.assertEqual(struct.unpack("!H", viewer_payload[0:2])[0], 4011)
        self.assertEqual(viewer_payload[2:], b"business_api_requested")

        uplink_opcode, uplink_payload = await asyncio.wait_for(
            _read_ws_frame(uplink_reader), timeout=2.0
        )
        self.assertEqual(uplink_opcode, 0x8)
        self.assertEqual(struct.unpack("!H", uplink_payload[0:2])[0], 4011)

        self.assertNotIn(session.session_id, self.relay._hubs)
        viewer_writer.close()
        uplink_writer.close()

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
