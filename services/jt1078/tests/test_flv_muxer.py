"""FLV muxer tests (`repackager/flv_muxer.py`) — container structure is spec-verified against
the public Adobe FLV format; the Annex-B->AVCC NAL conversion is exercised with synthetic byte
strings (flagged in the module's own docstring as unverified against real device output).
"""

import unittest

from src.repackager.flv_muxer import (
    TAG_TYPE_AUDIO,
    TAG_TYPE_VIDEO,
    FlvMuxer,
    build_avc_decoder_config,
    build_avcc_from_annex_b,
    extract_sps_pps,
    split_annex_b_nalus,
)

# A minimal, realistic-shaped H.264 SPS/PPS pair - `0x67`/`0x68`'s low 5 bits are NAL types
# 7 (SPS) / 8 (PPS); `0x42 0x00 0x1e` are SPS bytes 1-3 (AVCProfileIndication=Baseline,
# profile_compatibility=0, AVCLevelIndication=30) - the same fixture shape
# `SplitAnnexBNalusTests` above already uses, extended to full-length SPS/PPS bytes.
_SPS = b"\x67\x42\x00\x1e\xab\xcd\xef"
_PPS = b"\x68\xce\x3c\x80"
_IDR = b"\x65IDR-DATA"


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


class ExtractSpsPpsTests(unittest.TestCase):
    def test_classifies_sps_and_pps_by_nal_type(self) -> None:
        sps_list, pps_list = extract_sps_pps([_SPS, _PPS])
        self.assertEqual(sps_list, [_SPS])
        self.assertEqual(pps_list, [_PPS])

    def test_non_parameter_set_nalus_are_ignored(self) -> None:
        sps_list, pps_list = extract_sps_pps([_SPS, _PPS, _IDR])
        self.assertEqual(sps_list, [_SPS])
        self.assertEqual(pps_list, [_PPS])

    def test_no_parameter_sets_returns_two_empty_lists(self) -> None:
        sps_list, pps_list = extract_sps_pps([_IDR])
        self.assertEqual(sps_list, [])
        self.assertEqual(pps_list, [])

    def test_empty_nalu_is_skipped_not_raised(self) -> None:
        sps_list, pps_list = extract_sps_pps([b"", _SPS])
        self.assertEqual(sps_list, [_SPS])

    def test_multiple_sps_are_all_collected(self) -> None:
        sps_list, _pps_list = extract_sps_pps([_SPS, _SPS])
        self.assertEqual(len(sps_list), 2)


class BuildAvcDecoderConfigTests(unittest.TestCase):
    def test_reads_profile_compatibility_level_from_the_first_sps(self) -> None:
        config = build_avc_decoder_config(sps_list=[_SPS], pps_list=[_PPS])
        self.assertEqual(config[0], 0x01)  # configurationVersion
        self.assertEqual(config[1], 0x42)  # AVCProfileIndication
        self.assertEqual(config[2], 0x00)  # profile_compatibility
        self.assertEqual(config[3], 0x1E)  # AVCLevelIndication

    def test_length_size_minus_one_is_3_matching_the_4_byte_avcc_prefix(self) -> None:
        config = build_avc_decoder_config(sps_list=[_SPS], pps_list=[_PPS])
        # reserved(6)=111111 + lengthSizeMinusOne(2)=11 -> 0xFF, byte offset 4
        self.assertEqual(config[4], 0xFF)
        self.assertEqual(config[4] & 0x03, 0x03)

    def test_sps_and_pps_are_length_prefixed_and_recoverable(self) -> None:
        config = build_avc_decoder_config(sps_list=[_SPS], pps_list=[_PPS])
        num_sps = config[5] & 0x1F
        self.assertEqual(num_sps, 1)
        sps_len = int.from_bytes(config[6:8], "big")
        self.assertEqual(sps_len, len(_SPS))
        self.assertEqual(config[8 : 8 + sps_len], _SPS)
        offset = 8 + sps_len
        num_pps = config[offset]
        self.assertEqual(num_pps, 1)
        pps_len = int.from_bytes(config[offset + 1 : offset + 3], "big")
        self.assertEqual(pps_len, len(_PPS))
        self.assertEqual(config[offset + 3 : offset + 3 + pps_len], _PPS)

    def test_pps_list_may_be_empty(self) -> None:
        config = build_avc_decoder_config(sps_list=[_SPS], pps_list=[])
        sps_len = int.from_bytes(config[6:8], "big")
        num_pps = config[8 + sps_len]
        self.assertEqual(num_pps, 0)

    def test_empty_sps_list_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            build_avc_decoder_config(sps_list=[], pps_list=[_PPS])

    def test_sps_too_short_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            build_avc_decoder_config(sps_list=[b"\x67\x42"], pps_list=[])


class FeedAnnexBVideoTests(unittest.TestCase):
    """`FlvMuxer.feed_annex_b_video` — the SPS/PPS-aware entry point real players need before
    they can decode anything (completes the seam `build_avc_sequence_header_tag` used to leave
    unpopulated)."""

    def _annex_b(self, *nalus: bytes) -> bytes:
        return b"".join(b"\x00\x00\x01" + nalu for nalu in nalus)

    def test_first_frame_with_sps_pps_emits_a_sequence_header_before_the_nalu_tag(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        chunk = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS, _PPS, _IDR),
            is_keyframe=True,
            timestamp_ms=1000,
        )
        # Sequence header tag first: AVCPacketType (byte 12, after the 11-byte tag header +
        # 1-byte frame/codec byte) must be 0 (sequence header), not 1 (NALU).
        self.assertEqual(chunk[12], 0)

    def test_sequence_header_is_not_repeated_for_an_unchanged_parameter_set(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS, _PPS, _IDR),
            is_keyframe=True,
            timestamp_ms=1000,
        )
        chunk2 = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_IDR), is_keyframe=False, timestamp_ms=1040
        )
        # Only one tag this time (the NALU tag) - AVCPacketType=1, not a sequence header.
        self.assertEqual(chunk2[12], 1)

    def test_sequence_header_is_re_sent_if_the_parameter_set_changes(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS, _PPS, _IDR),
            is_keyframe=True,
            timestamp_ms=1000,
        )
        different_sps = b"\x67\x4d\x00\x1f\x00\x00"  # different profile/level bytes
        chunk2 = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(different_sps, _PPS, _IDR),
            is_keyframe=True,
            timestamp_ms=1040,
        )
        self.assertEqual(chunk2[12], 0)  # sequence header again, not skipped

    def test_sps_pps_appear_once_in_the_sequence_header_not_duplicated_in_the_nalu_tag(
        self,
    ) -> None:
        muxer = FlvMuxer()
        muxer.start()
        chunk = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS, _PPS, _IDR),
            is_keyframe=True,
            timestamp_ms=1000,
        )
        # SPS/PPS legitimately appear once each, inside the sequence-header tag's own
        # AVCDecoderConfigurationRecord - never a second time inside the NALU tag.
        self.assertEqual(chunk.count(_SPS), 1)
        self.assertEqual(chunk.count(_PPS), 1)
        self.assertIn(_IDR, chunk)

    def test_frame_with_no_sps_and_no_vcl_nalu_returns_empty_bytes(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        chunk = muxer.feed_annex_b_video(
            annex_b_payload=b"", is_keyframe=True, timestamp_ms=1000
        )
        self.assertEqual(chunk, b"")

    def test_sps_only_frame_with_no_vcl_nalu_returns_only_the_sequence_header(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        chunk = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS, _PPS), is_keyframe=False, timestamp_ms=1000
        )
        self.assertGreater(len(chunk), 0)
        self.assertEqual(chunk[12], 0)  # sequence header, no trailing NALU tag

    def test_each_viewers_own_muxer_tracks_its_own_sequence_header_independently(self) -> None:
        """The per-viewer independence `SessionBroadcastHub`'s own docstring already documents
        for the FLV file header - now proven for the codec sequence header too: an early
        viewer's muxer has already sent the config and won't repeat it, while a late viewer's
        fresh muxer has not, independent of what any other viewer's own muxer has done."""
        early_viewer = FlvMuxer()
        early_viewer.start()
        early_viewer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS, _PPS, _IDR),
            is_keyframe=True,
            timestamp_ms=1000,
        )
        early_chunk2 = early_viewer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS, _PPS, _IDR), is_keyframe=True, timestamp_ms=2000
        )
        self.assertEqual(early_chunk2[12], 1)  # unchanged config - no repeated sequence header

        late_viewer = FlvMuxer()
        late_viewer.start()
        late_chunk = late_viewer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS, _PPS, _IDR), is_keyframe=True, timestamp_ms=2000
        )
        # A fresh muxer has never sent this config before - sequence header first, same as the
        # early viewer's own first frame, regardless of what the early viewer's muxer has
        # already done.
        self.assertEqual(late_chunk[12], 0)


class FeedAnnexBVideoSplitParameterSetTests(unittest.TestCase):
    """Regression coverage for the bug found in review: a reassembled JT/T 1078 frame is not
    guaranteed to carry SPS and PPS together (the wire format's own `data_type` has no distinct
    "parameter set" value), so `feed_annex_b_video` must not require both in the same call to
    build/update the `AVCDecoderConfigurationRecord` — see `FlvMuxer._latest_sps_list`/
    `_latest_pps_list`.
    """

    def _annex_b(self, *nalus: bytes) -> bytes:
        return b"".join(b"\x00\x00\x01" + nalu for nalu in nalus)

    def test_sps_then_separate_pps_call_then_idr_builds_a_complete_decoder_config(self) -> None:
        muxer = FlvMuxer()
        muxer.start()

        # Call 1: SPS only - no PPS, no VCL data.
        chunk1 = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS), is_keyframe=False, timestamp_ms=1000
        )
        self.assertGreater(len(chunk1), 0)
        self.assertEqual(chunk1[12], 0)  # sequence header, 0 PPS known so far

        # Call 2: PPS only, no SPS in this call - must not be silently dropped.
        chunk2 = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_PPS), is_keyframe=False, timestamp_ms=1010
        )
        self.assertGreater(len(chunk2), 0)
        self.assertEqual(chunk2[12], 0)  # a corrected sequence header, now carrying the PPS
        self.assertIn(_PPS, chunk2)
        self.assertIn(_SPS, chunk2)

        # Call 3: the IDR slice - the decoder already has both SPS and PPS by now, so only a
        # NALU tag is needed.
        chunk3 = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_IDR), is_keyframe=True, timestamp_ms=1040
        )
        self.assertEqual(chunk3[12], 1)  # NALU tag, no further sequence header
        self.assertIn(_IDR, chunk3)

    def test_pps_only_refresh_after_an_existing_sps_updates_the_sequence_header(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS, _PPS, _IDR), is_keyframe=True, timestamp_ms=1000
        )

        different_pps = b"\x68\xce\x3c\x00"  # a changed PPS; SPS unchanged, not resent
        chunk2 = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(different_pps), is_keyframe=False, timestamp_ms=1040
        )
        self.assertGreater(len(chunk2), 0)  # previously: b"" - the PPS was silently dropped
        self.assertEqual(chunk2[12], 0)  # a fresh sequence header
        self.assertIn(different_pps, chunk2)
        self.assertIn(_SPS, chunk2)  # decoder config still carries the previously-seen SPS

    def test_sps_and_pps_arriving_together_still_sends_one_sequence_header(self) -> None:
        """Existing (pre-fix) behavior, preserved: SPS+PPS bundled in one call still produces
        exactly one sequence-header tag with each parameter set appearing once."""
        muxer = FlvMuxer()
        muxer.start()
        chunk = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS, _PPS, _IDR), is_keyframe=True, timestamp_ms=1000
        )
        self.assertEqual(chunk[12], 0)
        self.assertEqual(chunk.count(_SPS), 1)
        self.assertEqual(chunk.count(_PPS), 1)
        self.assertIn(_IDR, chunk)

    def test_sps_and_pps_changes_are_each_picked_up_across_separate_calls(self) -> None:
        muxer = FlvMuxer()
        muxer.start()
        muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(_SPS, _PPS, _IDR), is_keyframe=True, timestamp_ms=1000
        )

        different_sps = b"\x67\x4d\x00\x1f\x00\x00"  # different profile/level bytes
        chunk_sps_change = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(different_sps), is_keyframe=False, timestamp_ms=1040
        )
        self.assertEqual(chunk_sps_change[12], 0)
        self.assertIn(different_sps, chunk_sps_change)
        self.assertIn(_PPS, chunk_sps_change)  # last-known PPS carried forward unchanged

        different_pps = b"\x68\xce\x3c\x00"
        chunk_pps_change = muxer.feed_annex_b_video(
            annex_b_payload=self._annex_b(different_pps), is_keyframe=False, timestamp_ms=1080
        )
        self.assertEqual(chunk_pps_change[12], 0)
        self.assertIn(different_sps, chunk_pps_change)  # last-known (updated) SPS carried forward
        self.assertIn(different_pps, chunk_pps_change)


if __name__ == "__main__":
    unittest.main()
