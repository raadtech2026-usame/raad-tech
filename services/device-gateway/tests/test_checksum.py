"""Checksum tests (Phase 9.3; JT/T 808-2013 §4.4.4: XOR of every byte, one result byte)."""

import unittest

from src.protocol.checksum import compute_checksum, verify_checksum


class ChecksumTests(unittest.TestCase):
    def test_single_byte(self) -> None:
        self.assertEqual(compute_checksum(bytes([0x5A])), 0x5A)

    def test_xor_of_multiple_bytes(self) -> None:
        # 0x01 ^ 0x02 ^ 0x03 = 0x00
        self.assertEqual(compute_checksum(bytes([0x01, 0x02, 0x03])), 0x00)

    def test_empty_is_zero(self) -> None:
        self.assertEqual(compute_checksum(b""), 0x00)

    def test_verify_matches(self) -> None:
        data = bytes(
            [0x00, 0x02, 0x00, 0x00, 0x01, 0x38, 0x00, 0x13, 0x80, 0x00, 0x00, 0x01]
        )
        expected = 0
        for b in data:
            expected ^= b
        self.assertTrue(verify_checksum(data, expected))

    def test_verify_mismatch(self) -> None:
        self.assertFalse(verify_checksum(bytes([0x01, 0x02]), 0xFF))


if __name__ == "__main__":
    unittest.main()
