"""Unit tests for `core.security.user_agent.parse_device_label` (ADR-0019). Stdlib `unittest`,
matching every other test file in this codebase.
"""

from __future__ import annotations

import unittest

from raad.core.security.user_agent import parse_device_label

_CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_SAFARI_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like "
    "Gecko) Version/17.0 Safari/605.1.15"
)
_SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
_FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
_EDGE_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
)
_CHROME_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)


class ParseDeviceLabelTests(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        self.assertIsNone(parse_device_label(None))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(parse_device_label(""))

    def test_chrome_on_windows(self) -> None:
        self.assertEqual(parse_device_label(_CHROME_WINDOWS), "Chrome on Windows")

    def test_safari_on_macos(self) -> None:
        self.assertEqual(parse_device_label(_SAFARI_MAC), "Safari on macOS")

    def test_safari_on_ios(self) -> None:
        self.assertEqual(parse_device_label(_SAFARI_IPHONE), "Safari on iOS")

    def test_firefox_on_linux(self) -> None:
        self.assertEqual(parse_device_label(_FIREFOX_LINUX), "Firefox on Linux")

    def test_edge_is_distinguished_from_chrome_despite_containing_chrome_token(
        self,
    ) -> None:
        self.assertEqual(parse_device_label(_EDGE_WINDOWS), "Edge on Windows")

    def test_chrome_on_android(self) -> None:
        self.assertEqual(parse_device_label(_CHROME_ANDROID), "Chrome on Android")

    def test_unrecognized_user_agent_degrades_to_truncated_raw_value(self) -> None:
        label = parse_device_label("SomeCustomApiClient/1.0")
        self.assertEqual(label, "SomeCustomApiClient/1.0")

    def test_never_raises_and_result_is_bounded_length(self) -> None:
        label = parse_device_label("x" * 500)
        self.assertIsNotNone(label)
        self.assertLessEqual(len(label), 64)


if __name__ == "__main__":
    unittest.main()
