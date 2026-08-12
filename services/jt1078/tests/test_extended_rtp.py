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
    parse_one_frame,
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


if __name__ == "__main__":
    unittest.main()
