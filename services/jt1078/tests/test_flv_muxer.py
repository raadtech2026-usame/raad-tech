"""FLV muxer tests (`repackager/flv_muxer.py`) — container structure is spec-verified against
the public Adobe FLV format; the Annex-B->AVCC NAL conversion is exercised with synthetic byte
strings (flagged in the module's own docstring as unverified against real device output).
"""

import unittest

from src.repackager.flv_muxer import (
    TAG_TYPE_AUDIO,
    TAG_TYPE_VIDEO,
    FlvMuxer,
    build_avcc_from_annex_b,
    split_annex_b_nalus,
)


class SplitAnnexBNalusTests(unittest.TestCase):
    def test_splits_a_single_nalu_with_3_byte_start_code(self) -> None:
        payload = b"\x00\x00\x01" + b"\x67\x42\x00\x1e"
        nalus = split_annex_b_nalus(payload)
        self.assertEqual(nalus, [b"\x67\x42\x00\x1e"])

    def test_splits_two_nalus_with_4_byte_start_codes(self) -> None:
        payload = (
            b"\x00\x00\x00\x01" + b"\x67AA"  # SPS-like NALU
            + b"\x00\x00\x00\x01" + b"\x68BB"  # PPS-like NALU
        )
        nalus = split_annex_b_nalus(payload)
        self.assertEqual(len(nalus), 2)
        self.assertTrue(nalus[0].startswith(b"\x67AA"))
        self.assertTrue(nalus[1].startswith(b"\x68BB"))

    def test_no_start_code_returns_the_whole_payload_as_one_opaque_nalu(self) -> None:
        payload = b"\x01\x02\x03\x04"
        self.assertEqual(split_annex_b_nalus(payload), [payload])

    def test_empty_payload_returns_no_nalus(self) -> None:
        self.assertEqual(split_annex_b_nalus(b""), [])

    def test_three_nalus_in_sequence(self) -> None:
        payload = (
            b"\x00\x00\x01\x67SPS"
            + b"\x00\x00\x01\x68PPS"
            + b"\x00\x00\x01\x65IDR-DATA"
        )
        nalus = split_annex_b_nalus(payload)
        self.assertEqual(len(nalus), 3)
        self.assertTrue(nalus[2].startswith(b"\x65IDR-DATA"))


class BuildAvccTests(unittest.TestCase):
    def test_each_nalu_gets_a_4_byte_big_endian_length_prefix(self) -> None:
        payload = b"\x00\x00\x01" + b"\x67ABC"
        avcc = build_avcc_from_annex_b(payload)
        length = int.from_bytes(avcc[0:4], "big")
        self.assertEqual(length, len(b"\x67ABC"))
        self.assertEqual(avcc[4 : 4 + length], b"\x67ABC")

    def test_multiple_nalus_concatenate_with_their_own_prefixes(self) -> None:
        payload = b"\x00\x00\x01\x67AA" + b"\x00\x00\x01\x68BB"
        avcc = build_avcc_from_annex_b(payload)
        first_len = int.from_bytes(avcc[0:4], "big")
        offset = 4 + first_len
        second_len = int.from_bytes(avcc[offset : offset + 4], "big")
        self.assertEqual(avcc[offset + 4 : offset + 4 + second_len], b"\x68BB")


class FlvMuxerTests(unittest.TestCase):
    def test_start_emits_the_9_byte_header_plus_a_zero_previous_tag_size(self) -> None:
        muxer = FlvMuxer()
        header = muxer.start()
        self.assertEqual(header[0:3], b"FLV")
        self.assertEqual(header[3], 0x01)  # version
        self.assertEqual(int.from_bytes(header[5:9], "big"), 9)  # header size
        self.assertEqual(int.from_bytes(header[9:13], "big"), 0)  # PreviousTagSize0

    def test_video_tag_has_correct_type_and_previous_tag_size_trailer(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        chunk = muxer.feed_video_nalu(
            avcc_payload=b"\x00\x00\x00\x03\x67AB", is_keyframe=True, timestamp_ms=1000
        )
        tag_type = chunk[0]
        data_size = int.from_bytes(chunk[1:4], "big")
        self.assertEqual(tag_type, TAG_TYPE_VIDEO)
        self.assertEqual(data_size, len(chunk) - 11 - 4)  # tag header(11) + trailer(4)
        trailer = int.from_bytes(chunk[-4:], "big")
        self.assertEqual(trailer, len(chunk) - 4)  # size of the tag, excluding the trailer itself

    def test_first_frame_timestamp_is_rebased_to_zero(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        chunk = muxer.feed_video_nalu(
            avcc_payload=b"\x00", is_keyframe=True, timestamp_ms=50_000
        )
        timestamp_low = int.from_bytes(chunk[4:7], "big")
        self.assertEqual(timestamp_low, 0)

    def test_subsequent_frame_timestamp_is_relative_to_the_first(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        muxer.feed_video_nalu(avcc_payload=b"\x00", is_keyframe=True, timestamp_ms=50_000)
        chunk2 = muxer.feed_video_nalu(
            avcc_payload=b"\x00", is_keyframe=False, timestamp_ms=50_040
        )
        timestamp_low = int.from_bytes(chunk2[4:7], "big")
        self.assertEqual(timestamp_low, 40)

    def test_audio_tag_uses_the_audio_tag_type(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        chunk = muxer.feed_audio_aac(aac_payload=b"\x21\x22", timestamp_ms=1000)
        self.assertEqual(chunk[0], TAG_TYPE_AUDIO)

    def test_keyframe_and_interframe_produce_different_frame_type_nibble(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        key_chunk = muxer.feed_video_nalu(
            avcc_payload=b"\x00", is_keyframe=True, timestamp_ms=1000
        )
        inter_chunk = muxer.feed_video_nalu(
            avcc_payload=b"\x00", is_keyframe=False, timestamp_ms=1040
        )
        key_frame_type = key_chunk[11] >> 4
        inter_frame_type = inter_chunk[11] >> 4
        self.assertEqual(key_frame_type, 1)
        self.assertEqual(inter_frame_type, 2)
        self.assertNotEqual(key_frame_type, inter_frame_type)


if __name__ == "__main__":
    unittest.main()
