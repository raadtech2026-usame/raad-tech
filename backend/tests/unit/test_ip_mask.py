"""Unit tests for `core.security.ip_mask.mask_ip_address` (ADR-0019). Stdlib `unittest`,
matching every other test file in this codebase.
"""

from __future__ import annotations

import unittest

from raad.core.security.ip_mask import mask_ip_address


class MaskIpAddressTests(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        self.assertIsNone(mask_ip_address(None))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(mask_ip_address(""))

    def test_ipv4_masks_only_the_last_octet(self) -> None:
        self.assertEqual(mask_ip_address("192.168.1.42"), "192.168.1.xxx")

    def test_ipv4_loopback(self) -> None:
        self.assertEqual(mask_ip_address("127.0.0.1"), "127.0.0.xxx")

    def test_ipv6_masks_everything_after_the_first_two_groups(self) -> None:
        self.assertEqual(mask_ip_address("2001:db8::1"), "2001:db8:xxxx")

    def test_ipv6_full_form(self) -> None:
        self.assertEqual(
            mask_ip_address("2001:0db8:85a3:0000:0000:8a2e:0370:7334"),
            "2001:0db8:xxxx",
        )

    def test_malformed_input_is_masked_in_full_rather_than_partially_leaked(self) -> None:
        self.assertEqual(mask_ip_address("not-an-ip-address"), "xxx")


if __name__ == "__main__":
    unittest.main()
