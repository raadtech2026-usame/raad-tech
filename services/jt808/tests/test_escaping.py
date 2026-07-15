"""Byte unescaping tests (Phase 9.3; JT/T 808-2013 §4.4.2).

`test_spec_worked_example` uses the primary spec's own worked example verbatim (§4.4.2):
"发送一包内容为0x30 0x7e 0x08 0x7d 0x55 的数据包，则经过封装如下：0x7e 0x30 7d 0x02 0x08 0x7d
0x01 0x55 0x7e" — sending content [0x30, 0x7e, 0x08, 0x7d, 0x55] encapsulates as
[0x7e, 0x30, 0x7d, 0x02, 0x08, 0x7d, 0x01, 0x55, 0x7e]. Stripping the leading/trailing 0x7e
delimiters (Phase 9.1's `FrameBuffer` job, not this module's) leaves the escaped payload this
test feeds to `unescape()`, expecting the original content back.
"""

import unittest

from src.protocol.escaping import unescape
from src.protocol.exceptions import UnescapeError


class UnescapeTests(unittest.TestCase):
    def test_spec_worked_example(self) -> None:
        escaped_payload = bytes([0x30, 0x7D, 0x02, 0x08, 0x7D, 0x01, 0x55])
        original_content = bytes([0x30, 0x7E, 0x08, 0x7D, 0x55])
        self.assertEqual(unescape(escaped_payload), original_content)

    def test_no_escaping_needed(self) -> None:
        data = bytes([0x01, 0x02, 0x03, 0x04])
        self.assertEqual(unescape(data), data)

    def test_escaped_delimiter_only(self) -> None:
        self.assertEqual(unescape(bytes([0x7D, 0x02])), bytes([0x7E]))

    def test_escaped_marker_only(self) -> None:
        self.assertEqual(unescape(bytes([0x7D, 0x01])), bytes([0x7D]))

    def test_multiple_escapes_in_sequence(self) -> None:
        data = bytes([0x7D, 0x02, 0x7D, 0x01, 0x7D, 0x02])
        self.assertEqual(unescape(data), bytes([0x7E, 0x7D, 0x7E]))

    def test_empty_input(self) -> None:
        self.assertEqual(unescape(b""), b"")

    def test_dangling_escape_marker_raises(self) -> None:
        with self.assertRaises(UnescapeError):
            unescape(bytes([0x01, 0x7D]))

    def test_invalid_escape_sequence_raises(self) -> None:
        with self.assertRaises(UnescapeError):
            unescape(bytes([0x7D, 0x03]))  # only 0x01/0x02 are valid per §4.4.2


if __name__ == "__main__":
    unittest.main()
