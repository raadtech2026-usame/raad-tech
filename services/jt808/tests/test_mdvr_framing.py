"""LSZ MDVR frame boundary detection tests — mirrors `tests/test_framing.py`'s conventions
(stdlib `unittest` only)."""

import unittest

from src.vendors.lsz_mdvr.protocol.exceptions import MdvrFrameTooLargeError
from src.vendors.lsz_mdvr.protocol.framing import MdvrFrameBuffer


class MdvrFrameBufferTests(unittest.TestCase):
    def test_single_complete_frame(self) -> None:
        buf = MdvrFrameBuffer(max_frame_size=1024)
        frames = buf.feed(b"$$dc0010,1,V109#")
        self.assertEqual(frames, [b"$$dc0010,1,V109"])

    def test_frame_split_across_multiple_feeds(self) -> None:
        buf = MdvrFrameBuffer(max_frame_size=1024)
        self.assertEqual(buf.feed(b"$$dc0010,1"), [])
        self.assertEqual(buf.feed(b",V109"), [])
        self.assertEqual(buf.feed(b"#"), [b"$$dc0010,1,V109"])

    def test_frame_split_byte_by_byte(self) -> None:
        buf = MdvrFrameBuffer(max_frame_size=1024)
        frame = b"$$dc0010,1,V109#"
        results: list[bytes] = []
        for byte in frame:
            results.extend(buf.feed(bytes([byte])))
        self.assertEqual(results, [b"$$dc0010,1,V109"])

    def test_multiple_frames_in_one_feed(self) -> None:
        buf = MdvrFrameBuffer(max_frame_size=1024)
        data = b"$$dc0004,1#$$dc0004,2#"
        frames = buf.feed(data)
        self.assertEqual(frames, [b"$$dc0004,1", b"$$dc0004,2"])

    def test_noise_before_first_marker_is_dropped(self) -> None:
        buf = MdvrFrameBuffer(max_frame_size=1024)
        data = b"garbage-before$$dc0004,1#"
        frames = buf.feed(data)
        self.assertEqual(frames, [b"$$dc0004,1"])

    def test_no_start_marker_buffers_without_emitting(self) -> None:
        buf = MdvrFrameBuffer(max_frame_size=1024)
        self.assertEqual(buf.feed(b"no marker here at all"), [])

    def test_frame_too_large_without_terminator_raises(self) -> None:
        buf = MdvrFrameBuffer(max_frame_size=8)
        with self.assertRaises(MdvrFrameTooLargeError):
            buf.feed(b"$$dc0099,1,2,3,4,5,6,7,8,9")

    def test_reset_clears_partial_state(self) -> None:
        buf = MdvrFrameBuffer(max_frame_size=1024)
        buf.feed(b"$$dc0010,1")
        buf.reset()
        frames = buf.feed(b"garbage$$dc0004,9#")
        self.assertEqual(frames, [b"$$dc0004,9"])


if __name__ == "__main__":
    unittest.main()
