"""Message header parsing tests (Phase 9.3; JT/T 808-2013 §4.4.3, Table 2 + Fig. 2)."""

import unittest

from src.protocol.exceptions import MalformedFrameError
from src.protocol.header import parse_header


def bcd_phone(digits: str) -> bytes:
    """Independent reference encoder (not reusing `header._decode_bcd_phone`) — packs a
    12-digit string into 6 BCD bytes, high nibble first."""
    assert len(digits) == 12
    result = bytearray()
    for i in range(0, 12, 2):
        high, low = int(digits[i]), int(digits[i + 1])
        result.append((high << 4) | low)
    return bytes(result)


def build_header(
    *,
    message_id: int,
    body_length: int,
    encryption_method: int = 0,
    is_subpackaged: bool = False,
    terminal_phone: str = "013800138000",
    serial_no: int = 1,
    total_packages: int | None = None,
    package_sequence: int | None = None,
) -> bytes:
    body_attributes = body_length & 0x03FF
    body_attributes |= (encryption_method & 0x07) << 10
    if is_subpackaged:
        body_attributes |= 1 << 13
    data = bytearray()
    data += message_id.to_bytes(2, "big")
    data += body_attributes.to_bytes(2, "big")
    data += bcd_phone(terminal_phone)
    data += serial_no.to_bytes(2, "big")
    if is_subpackaged:
        assert total_packages is not None and package_sequence is not None
        data += total_packages.to_bytes(2, "big")
        data += package_sequence.to_bytes(2, "big")
    return bytes(data)


class ParseHeaderTests(unittest.TestCase):
    def test_base_header_no_subpackage(self) -> None:
        raw = build_header(message_id=0x0002, body_length=0, serial_no=0x0001)
        header, header_length = parse_header(raw)

        self.assertEqual(header.message_id, 0x0002)
        self.assertEqual(header.body_length, 0)
        self.assertEqual(header.encryption_method, 0)
        self.assertFalse(header.is_subpackaged)
        self.assertEqual(header.terminal_phone, "013800138000")
        self.assertEqual(header.serial_no, 1)
        self.assertIsNone(header.total_packages)
        self.assertIsNone(header.package_sequence)
        self.assertEqual(header_length, 12)

    def test_subpackaged_header(self) -> None:
        raw = build_header(
            message_id=0x0200,
            body_length=100,
            is_subpackaged=True,
            total_packages=3,
            package_sequence=2,
        )
        header, header_length = parse_header(raw)

        self.assertTrue(header.is_subpackaged)
        self.assertEqual(header.total_packages, 3)
        self.assertEqual(header.package_sequence, 2)
        self.assertEqual(header_length, 16)

    def test_encryption_method_bit10_rsa(self) -> None:
        raw = build_header(message_id=0x0200, body_length=0, encryption_method=0b001)
        header, _ = parse_header(raw)
        self.assertEqual(header.encryption_method, 0b001)

    def test_body_length_max_10_bits(self) -> None:
        raw = build_header(message_id=0x0200, body_length=1023)
        header, _ = parse_header(raw)
        self.assertEqual(header.body_length, 1023)

    def test_body_length_does_not_leak_into_encryption_or_subpackage_bits(self) -> None:
        # body_length=1023 (all 10 low bits set) must not be misread as encrypted/subpackaged.
        raw = build_header(message_id=0x0200, body_length=1023)
        header, _ = parse_header(raw)
        self.assertEqual(header.encryption_method, 0)
        self.assertFalse(header.is_subpackaged)

    def test_terminal_phone_leading_zero_preserved(self) -> None:
        raw = build_header(
            message_id=0x0002, body_length=0, terminal_phone="001234567890"
        )
        header, _ = parse_header(raw)
        self.assertEqual(header.terminal_phone, "001234567890")

    def test_truncated_header_raises(self) -> None:
        with self.assertRaises(MalformedFrameError):
            parse_header(bytes([0x00, 0x02, 0x00, 0x00]))  # only 4 of 12 bytes

    def test_subpackage_bit_set_but_block_missing_raises(self) -> None:
        # Base 12 bytes only, but subpackage bit is set in body_attributes.
        raw = bytearray(build_header(message_id=0x0200, body_length=0))
        raw[
            2
        ] |= 0b0010_0000  # set bit 13 of body_attributes (high byte, bit 5 of byte)
        with self.assertRaises(MalformedFrameError):
            parse_header(bytes(raw))

    def test_invalid_bcd_nibble_raises(self) -> None:
        raw = bytearray(build_header(message_id=0x0002, body_length=0))
        raw[4] = 0xFA  # nibble 0xF is not a valid BCD digit
        with self.assertRaises(MalformedFrameError):
            parse_header(bytes(raw))


if __name__ == "__main__":
    unittest.main()
