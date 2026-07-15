"""Frame boundary detection tests (Phase 9.1). Stdlib `unittest` only — no new dependency;
`pytest` is not actually installed/approved anywhere in this repo yet (`backend/pyproject.toml`
itself flags dev tooling as "not yet decided by approved documentation")."""

import unittest

from src.protocol.framing import FrameBuffer, FrameTooLargeError


class FrameBufferTests(unittest.TestCase):
    def test_single_complete_frame(self) -> None:
        buf = FrameBuffer(max_frame_size=1024)
        frames = buf.feed(bytes([0x7E, 0x01, 0x02, 0x03, 0x7E]))
        self.assertEqual(frames, [bytes([0x01, 0x02, 0x03])])

    def test_frame_split_across_multiple_feeds(self) -> None:
        buf = FrameBuffer(max_frame_size=1024)
        self.assertEqual(buf.feed(bytes([0x7E, 0x01, 0x02])), [])
        self.assertEqual(buf.feed(bytes([0x03])), [])
        self.assertEqual(buf.feed(bytes([0x7E])), [bytes([0x01, 0x02, 0x03])])

    def test_frame_split_byte_by_byte(self) -> None:
        buf = FrameBuffer(max_frame_size=1024)
        frame = bytes([0x7E, 0xAA, 0xBB, 0xCC, 0x7E])
        results: list[bytes] = []
        for b in frame:
            results.extend(buf.feed(bytes([b])))
        self.assertEqual(results, [bytes([0xAA, 0xBB, 0xCC])])

    def test_multiple_frames_in_one_feed(self) -> None:
        buf = FrameBuffer(max_frame_size=1024)
        data = bytes([0x7E, 0xAA, 0x7E, 0x7E, 0xBB, 0xCC, 0x7E])
        frames = buf.feed(data)
        self.assertEqual(frames, [bytes([0xAA]), bytes([0xBB, 0xCC])])

    def test_back_to_back_frames_sharing_no_gap(self) -> None:
        buf = FrameBuffer(max_frame_size=1024)
        # frame1 = 0x11, frame2 = 0x22, delimiters not shared (4 delimiter bytes total)
        data = bytes([0x7E, 0x11, 0x7E, 0x7E, 0x22, 0x7E])
        self.assertEqual(buf.feed(data), [bytes([0x11]), bytes([0x22])])

    def test_noise_before_first_delimiter_is_dropped(self) -> None:
        buf = FrameBuffer(max_frame_size=1024)
        data = bytes([0x00, 0x11, 0x7E, 0x22, 0x7E])
        frames = buf.feed(data)
        self.assertEqual(frames, [bytes([0x22])])

    def test_empty_frame_between_two_delimiters_is_not_emitted(self) -> None:
        buf = FrameBuffer(max_frame_size=1024)
        frames = buf.feed(bytes([0x7E, 0x7E]))
        self.assertEqual(frames, [])

    def test_frame_too_large_raises(self) -> None:
        buf = FrameBuffer(max_frame_size=4)
        with self.assertRaises(FrameTooLargeError):
            buf.feed(bytes([0x7E, 0x01, 0x02, 0x03, 0x04, 0x05]))

    def test_reset_clears_partial_state(self) -> None:
        buf = FrameBuffer(max_frame_size=1024)
        buf.feed(bytes([0x7E, 0x01, 0x02]))
        buf.reset()
        # After reset, 0x03 arrives with no preceding delimiter in this feed -> dropped as
        # pre-delimiter noise, matching a fresh buffer's behavior.
        frames = buf.feed(bytes([0x03, 0x7E]))
        self.assertEqual(frames, [])


if __name__ == "__main__":
    unittest.main()
