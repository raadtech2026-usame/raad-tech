"""`FrameReassembler` tests (`ingest/frame_reassembly.py`) — synthetic fragment sequences, no
hardware needed.
"""

import unittest

from src.ingest.extended_rtp import (
    DATA_TYPE_AUDIO,
    DATA_TYPE_I_FRAME,
    SUBPACKAGE_ATOMIC,
    SUBPACKAGE_FIRST,
    SUBPACKAGE_LAST,
    SUBPACKAGE_MIDDLE,
    ExtendedRtpFrame,
)
from src.ingest.frame_reassembly import FrameReassembler


def _frame(
    *,
    channel: int = 1,
    data_type: int = DATA_TYPE_I_FRAME,
    subpackage_marker: int,
    body: bytes,
) -> ExtendedRtpFrame:
    return ExtendedRtpFrame(
        packet_sequence=0,
        sim_card_number="138001380000",
        logical_channel=channel,
        data_type=data_type,
        subpackage_marker=subpackage_marker,
        timestamp_ms=1000,
        last_i_frame_interval_ms=0,
        last_frame_interval_ms=40,
        body=body,
    )


class FrameReassemblerTests(unittest.TestCase):
    def test_atomic_frame_completes_immediately(self) -> None:
        reassembler = FrameReassembler()
        result = reassembler.feed(_frame(subpackage_marker=SUBPACKAGE_ATOMIC, body=b"ABC"))
        self.assertIsNotNone(result)
        self.assertEqual(result.body, b"ABC")

    def test_first_middle_last_sequence_concatenates_in_order(self) -> None:
        reassembler = FrameReassembler()
        self.assertIsNone(reassembler.feed(_frame(subpackage_marker=SUBPACKAGE_FIRST, body=b"A")))
        self.assertIsNone(
            reassembler.feed(_frame(subpackage_marker=SUBPACKAGE_MIDDLE, body=b"B"))
        )
        self.assertIsNone(
            reassembler.feed(_frame(subpackage_marker=SUBPACKAGE_MIDDLE, body=b"C"))
        )
        result = reassembler.feed(_frame(subpackage_marker=SUBPACKAGE_LAST, body=b"D"))
        self.assertIsNotNone(result)
        self.assertEqual(result.body, b"ABCD")

    def test_first_last_with_no_middle_fragments_still_completes(self) -> None:
        reassembler = FrameReassembler()
        self.assertIsNone(reassembler.feed(_frame(subpackage_marker=SUBPACKAGE_FIRST, body=b"A")))
        result = reassembler.feed(_frame(subpackage_marker=SUBPACKAGE_LAST, body=b"B"))
        self.assertEqual(result.body, b"AB")

    def test_distinct_channel_and_data_type_sequences_do_not_interleave(self) -> None:
        reassembler = FrameReassembler()
        reassembler.feed(_frame(channel=1, data_type=DATA_TYPE_I_FRAME, subpackage_marker=SUBPACKAGE_FIRST, body=b"V1"))
        # An atomic audio frame arrives *between* the video fragments - must not corrupt the
        # in-progress video sequence.
        audio_result = reassembler.feed(
            _frame(channel=1, data_type=DATA_TYPE_AUDIO, subpackage_marker=SUBPACKAGE_ATOMIC, body=b"A1")
        )
        self.assertEqual(audio_result.body, b"A1")

        video_result = reassembler.feed(
            _frame(channel=1, data_type=DATA_TYPE_I_FRAME, subpackage_marker=SUBPACKAGE_LAST, body=b"V2")
        )
        self.assertEqual(video_result.body, b"V1V2")

    def test_middle_fragment_with_no_prior_first_is_discarded_not_raised(self) -> None:
        reassembler = FrameReassembler()
        result = reassembler.feed(
            _frame(subpackage_marker=SUBPACKAGE_MIDDLE, body=b"orphan")
        )
        self.assertIsNone(result)

    def test_last_fragment_with_no_prior_first_is_discarded_not_raised(self) -> None:
        reassembler = FrameReassembler()
        result = reassembler.feed(_frame(subpackage_marker=SUBPACKAGE_LAST, body=b"orphan"))
        self.assertIsNone(result)

    def test_a_new_first_abandons_an_incomplete_prior_sequence_and_counts_it(self) -> None:
        reassembler = FrameReassembler()
        reassembler.feed(_frame(subpackage_marker=SUBPACKAGE_FIRST, body=b"lost-1"))
        reassembler.feed(_frame(subpackage_marker=SUBPACKAGE_FIRST, body=b"new-1"))
        self.assertEqual(reassembler.dropped_sequence_count, 1)

        result = reassembler.feed(_frame(subpackage_marker=SUBPACKAGE_LAST, body=b"new-2"))
        self.assertEqual(result.body, b"new-1new-2")  # only the new sequence survives


if __name__ == "__main__":
    unittest.main()
