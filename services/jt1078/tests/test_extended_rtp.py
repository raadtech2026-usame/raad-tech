"""JT/T 1078 extended-RTP demux tests (`ingest/extended_rtp.py`, spec §6.2.1.1 Table 6.3) —
spec-verified byte layouts, synthetic frames, no hardware needed.
"""

import unittest

from src.ingest.extended_rtp import (
    DATA_TYPE_AUDIO,
    DATA_TYPE_I_FRAME,
    DATA_TYPE_PASSTHROUGH,
    FRAME_HEADER_MAGIC,
    SUBPACKAGE_ATOMIC,
    SUBPACKAGE_FIRST,
    ExtendedRtpStreamDemuxer,
    MalformedExtendedRtpFrameError,
    encode_audio_frame,
    parse_one_frame,
    PAYLOAD_TYPE_G711A,
)


def _build_video_frame(
    *,
    packet_sequence: int = 0,
    sim_card: str = "138001380000",
    logical_channel: int = 1,
    data_type: int = DATA_TYPE_I_FRAME,
    subpackage_marker: int = SUBPACKAGE_ATOMIC,
    timestamp_ms: int = 1000,
    last_i_frame_interval_ms: int = 0,
    last_frame_interval_ms: int = 40,
    body: bytes = b"\xaa" * 10,
) -> bytes:
    assert len(sim_card) == 12
    sim_bytes = bytes(
        ((int(sim_card[i]) << 4) | int(sim_card[i + 1])) for i in range(0, 12, 2)
    )
    header = (
        FRAME_HEADER_MAGIC.to_bytes(4, "big")
        + bytes([0b0010_0001])  # V=2,P=0,X=0,CC=1
        + bytes([0b1000_0001])  # M=1,PT=1
        + packet_sequence.to_bytes(2, "big")
        + sim_bytes
        + bytes([logical_channel])
        + bytes([(data_type << 4) | subpackage_marker])
    )
    if data_type == DATA_TYPE_PASSTHROUGH:
        trailer = b""
    elif data_type == DATA_TYPE_AUDIO:
        trailer = timestamp_ms.to_bytes(8, "big")
    else:
        trailer = (
            timestamp_ms.to_bytes(8, "big")
            + last_i_frame_interval_ms.to_bytes(2, "big")
            + last_frame_interval_ms.to_bytes(2, "big")
        )
    return header + trailer + len(body).to_bytes(2, "big") + body


class ParseOneFrameTests(unittest.TestCase):
    def test_parses_a_video_i_frame(self) -> None:
        raw = _build_video_frame(data_type=DATA_TYPE_I_FRAME, body=b"\x01\x02\x03")
        result = parse_one_frame(raw)
        self.assertIsNotNone(result)
        frame, consumed = result
        self.assertEqual(consumed, len(raw))
        self.assertEqual(frame.data_type, DATA_TYPE_I_FRAME)
        self.assertTrue(frame.is_video)
        self.assertFalse(frame.is_audio)
        self.assertEqual(frame.body, b"\x01\x02\x03")
        self.assertEqual(frame.sim_card_number, "138001380000")
        self.assertIsNotNone(frame.timestamp_ms)
        self.assertIsNotNone(frame.last_i_frame_interval_ms)
        self.assertIsNotNone(frame.last_frame_interval_ms)

    def test_parses_an_audio_frame_with_no_frame_intervals(self) -> None:
        raw = _build_video_frame(data_type=DATA_TYPE_AUDIO, body=b"\x99" * 5)
        frame, consumed = parse_one_frame(raw)
        self.assertEqual(consumed, len(raw))
        self.assertTrue(frame.is_audio)
        self.assertIsNotNone(frame.timestamp_ms)
        self.assertIsNone(frame.last_i_frame_interval_ms)
        self.assertIsNone(frame.last_frame_interval_ms)

    def test_parses_a_passthrough_frame_with_no_timestamp_or_intervals(self) -> None:
        raw = _build_video_frame(data_type=DATA_TYPE_PASSTHROUGH, body=b"\x01")
        frame, consumed = parse_one_frame(raw)
        self.assertEqual(consumed, len(raw))
        self.assertIsNone(frame.timestamp_ms)
        self.assertIsNone(frame.last_i_frame_interval_ms)
        self.assertIsNone(frame.last_frame_interval_ms)

    def test_returns_none_for_a_truncated_base_header(self) -> None:
        self.assertIsNone(parse_one_frame(b"\x30\x31\x63"))

    def test_returns_none_when_video_trailer_is_incomplete(self) -> None:
        raw = _build_video_frame(data_type=DATA_TYPE_I_FRAME, body=b"\x01")
        # cut off right after the base header, before the 8-byte timestamp is complete
        self.assertIsNone(parse_one_frame(raw[:20]))

    def test_returns_none_when_body_is_incomplete(self) -> None:
        raw = _build_video_frame(data_type=DATA_TYPE_I_FRAME, body=b"\x01\x02\x03\x04\x05")
        self.assertIsNone(parse_one_frame(raw[:-2]))

    def test_rejects_wrong_magic(self) -> None:
        raw = bytearray(_build_video_frame())
        raw[0] ^= 0xFF
        with self.assertRaises(MalformedExtendedRtpFrameError):
            parse_one_frame(bytes(raw))

    def test_rejects_body_length_over_950_bytes(self) -> None:
        raw = bytearray(_build_video_frame(body=b"\x00" * 10))
        # Overwrite the body_length field (last 2 bytes before body start) with an
        # out-of-range value without actually providing that many body bytes.
        body_length_offset = len(raw) - 10 - 2
        raw[body_length_offset : body_length_offset + 2] = (951).to_bytes(2, "big")
        with self.assertRaises(MalformedExtendedRtpFrameError):
            parse_one_frame(bytes(raw))

    def test_subpackage_marker_round_trips(self) -> None:
        raw = _build_video_frame(subpackage_marker=SUBPACKAGE_FIRST)
        frame, _ = parse_one_frame(raw)
        self.assertEqual(frame.subpackage_marker, SUBPACKAGE_FIRST)
        self.assertFalse(frame.is_atomic)


class EncodeAudioFrameTests(unittest.TestCase):
    """ADR-0036 — the relay's own new uplink (operator mic audio -> device) encoder, the reverse
    of the decoder above. Round-trips through `parse_one_frame` unmodified, proving the two are
    mutually consistent."""

    def test_round_trips_through_parse_one_frame(self) -> None:
        body = b"\xd7\xd4" * 160  # 320 bytes, G.711A-shaped (ADR-0033's own confirmed size)
        raw = encode_audio_frame(
            sim_card_number="014482607571", logical_channel=1, packet_sequence=7, body=body
        )
        result = parse_one_frame(raw)
        assert result is not None
        frame, consumed = result
        self.assertEqual(consumed, len(raw))
        self.assertEqual(frame.data_type, DATA_TYPE_AUDIO)
        self.assertTrue(frame.is_audio)
        self.assertEqual(frame.subpackage_marker, SUBPACKAGE_ATOMIC)
        self.assertEqual(frame.sim_card_number, "014482607571")
        self.assertEqual(frame.logical_channel, 1)
        self.assertEqual(frame.packet_sequence, 7)
        self.assertEqual(frame.body, body)
        self.assertIsNotNone(frame.timestamp_ms)
        self.assertIsNone(frame.last_i_frame_interval_ms)  # audio never carries these
        self.assertIsNone(frame.last_frame_interval_ms)

    def test_packet_sequence_wraps_at_16_bits(self) -> None:
        raw = encode_audio_frame(
            sim_card_number="014482607571", logical_channel=1, packet_sequence=70000, body=b"x"
        )
        frame, _ = parse_one_frame(raw)
        self.assertEqual(frame.packet_sequence, 70000 % 65536)

    def test_rejects_a_sim_card_number_that_is_not_exactly_12_digits(self) -> None:
        with self.assertRaises(MalformedExtendedRtpFrameError):
            encode_audio_frame(
                sim_card_number="123", logical_channel=1, packet_sequence=0, body=b"x"
            )

    def test_rejects_a_body_over_the_950_byte_ceiling(self) -> None:
        with self.assertRaises(MalformedExtendedRtpFrameError):
            encode_audio_frame(
                sim_card_number="014482607571",
                logical_channel=1,
                packet_sequence=0,
                body=b"x" * 951,
            )


class ExtendedRtpStreamDemuxerTests(unittest.TestCase):
    def test_single_frame_fed_whole(self) -> None:
        demuxer = ExtendedRtpStreamDemuxer()
        raw = _build_video_frame(body=b"\x01\x02")
        frames = demuxer.feed(raw)
        self.assertEqual(len(frames), 1)
        self.assertEqual(demuxer.buffered_byte_count, 0)

    def test_frame_split_across_multiple_feeds(self) -> None:
        demuxer = ExtendedRtpStreamDemuxer()
        raw = _build_video_frame(body=b"\x01\x02\x03\x04")
        first_half, second_half = raw[:15], raw[15:]

        self.assertEqual(demuxer.feed(first_half), [])
        self.assertGreater(demuxer.buffered_byte_count, 0)

        frames = demuxer.feed(second_half)
        self.assertEqual(len(frames), 1)
        self.assertEqual(demuxer.buffered_byte_count, 0)

    def test_multiple_frames_coalesced_in_one_feed(self) -> None:
        demuxer = ExtendedRtpStreamDemuxer()
        raw = _build_video_frame(packet_sequence=1, body=b"A") + _build_video_frame(
            packet_sequence=2, body=b"BB"
        )
        frames = demuxer.feed(raw)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].packet_sequence, 1)
        self.assertEqual(frames[1].packet_sequence, 2)

    def test_mixed_video_and_audio_frames_in_sequence(self) -> None:
        demuxer = ExtendedRtpStreamDemuxer()
        raw = _build_video_frame(data_type=DATA_TYPE_I_FRAME, body=b"V") + _build_video_frame(
            data_type=DATA_TYPE_AUDIO, body=b"A"
        )
        frames = demuxer.feed(raw)
        self.assertEqual(len(frames), 2)
        self.assertTrue(frames[0].is_video)
        self.assertTrue(frames[1].is_audio)


class PayloadTypeTests(unittest.TestCase):
    """Wire-confirmed 2026-09-03 against the physical `LSZ-C5804DG-Q-F`: every one of 23,544
    device-originated audio frames carried `M/PT = 0x86` (M=1, PT=6 = G.711A, Table 6.21), while
    this relay's own uplink was hardcoding PT=0 on all 712 frames of a live Hold-to-Talk press."""

    def test_encode_audio_frame_stamps_g711a_payload_type_by_default(self) -> None:
        frame = encode_audio_frame(
            sim_card_number="014482607571", logical_channel=1, packet_sequence=0, body=bytes([0xD5]) * 320
        )
        self.assertEqual(frame[5], 0x86, "M=1|PT=6 — must match the device's own audio frames")
        self.assertEqual(frame[5] & 0x7F, PAYLOAD_TYPE_G711A)
        self.assertTrue(frame[5] & 0x80, "M (complete-frame) bit must stay set")

    def test_encode_audio_frame_honours_an_explicit_payload_type(self) -> None:
        frame = encode_audio_frame(
            sim_card_number="014482607571", logical_channel=1, packet_sequence=0,
            body=bytes([0xD5]) * 320, payload_type=99,
        )
        self.assertEqual(frame[5] & 0x7F, 99)

    def test_encoded_audio_frame_round_trips_its_payload_type(self) -> None:
        frame = encode_audio_frame(
            sim_card_number="014482607571", logical_channel=1, packet_sequence=7, body=bytes([0xD5]) * 320
        )
        parsed, _consumed = parse_one_frame(frame)
        self.assertEqual(parsed.payload_type, PAYLOAD_TYPE_G711A)
        self.assertTrue(parsed.marker)

    def test_parses_the_devices_own_captured_audio_header(self) -> None:
        """A real header byte-for-byte off the wire (pktmon, 2026-09-03) — PT=6, data_type=3,
        atomic, channel 1, 320-byte body."""
        header = bytes.fromhex("303163648186001d0144826075710130000001a065e9ea8a0140")
        frame, _consumed = parse_one_frame(header + bytes([0xD7]) * 320)
        self.assertEqual(frame.payload_type, 6)
        self.assertTrue(frame.marker)
        self.assertTrue(frame.is_audio)
        self.assertTrue(frame.is_atomic)
        self.assertEqual(frame.logical_channel, 1)
        self.assertEqual(frame.sim_card_number, "014482607571")
        self.assertEqual(len(frame.body), 320)

    def test_parses_the_devices_own_captured_video_header_payload_type(self) -> None:
        """Same capture: video frames from this device carry PT=98 (H.264), proving PT really
        identifies the codec rather than being a constant."""
        header = bytes.fromhex("30316364816200000144826075710101000001a065e9ea5d00000000000a")
        frame, _consumed = parse_one_frame(header + bytes(10))
        self.assertEqual(frame.payload_type, 98)
        self.assertFalse(frame.marker)
        self.assertTrue(frame.is_video)


if __name__ == "__main__":
    unittest.main()
