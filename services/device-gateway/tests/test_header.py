"""Message header parsing tests (JT/T 808-2019, `mdvrdocs/MDVR-808-1078-spec.pdf` §4.1/§4.2
Table 4.1/4.2/4.3 — ADR-0025 §2)."""

import unittest

from src.vendors.jt808.protocol.exceptions import MalformedFrameError
from src.vendors.jt808.protocol.header import parse_header

_VERSION_FLAG_BIT = 1 << 14


def bcd_phone(digits: str) -> bytes:
    """Independent reference encoder (not reusing `header._decode_bcd_phone`) — packs a
    20-digit string into 10 BCD bytes, high nibble first."""
    assert len(digits) == 20
    result = bytearray()
    for i in range(0, 20, 2):
        high, low = int(digits[i]), int(digits[i + 1])
        result.append((high << 4) | low)
    return bytes(result)


def build_header(
    *,
    message_id: int,
    body_length: int,
    encryption_method: int = 0,
    is_subpackaged: bool = False,
    version_flag: bool = True,
    protocol_version: int = 0x01,
    terminal_phone: str = "00000013800138000",
    serial_no: int = 1,
    total_packages: int | None = None,
    package_sequence: int | None = None,
) -> bytes:
    terminal_phone = terminal_phone.rjust(20, "0")
    body_attributes = body_length & 0x03FF
    body_attributes |= (encryption_method & 0x07) << 10
    if is_subpackaged:
        body_attributes |= 1 << 13
    if version_flag:
        body_attributes |= _VERSION_FLAG_BIT
    data = bytearray()
    data += message_id.to_bytes(2, "big")
    data += body_attributes.to_bytes(2, "big")
    data += bytes([protocol_version])
    data += bcd_phone(terminal_phone)
    data += serial_no.to_bytes(2, "big")
    if is_subpackaged:
        assert total_packages is not None and package_sequence is not None
        data += total_packages.to_bytes(2, "big")
        data += package_sequence.to_bytes(2, "big")
    return bytes(data)


class ParseHeaderTests(unittest.TestCase):
    def test_base_header_no_subpackage(self) -> None:
        raw = build_header(
            message_id=0x0002,
            body_length=0,
            serial_no=0x0001,
            terminal_phone="00000000013800138000",
        )
        header, header_length = parse_header(raw)

        self.assertEqual(header.message_id, 0x0002)
        self.assertEqual(header.body_length, 0)
        self.assertEqual(header.encryption_method, 0)
        self.assertFalse(header.is_subpackaged)
        self.assertTrue(header.is_2019_version)
        self.assertEqual(header.protocol_version, 0x01)
        self.assertEqual(header.terminal_phone, "00000000013800138000")
        self.assertEqual(header.serial_no, 1)
        self.assertIsNone(header.total_packages)
        self.assertIsNone(header.package_sequence)
        self.assertEqual(header_length, 17)

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
        self.assertEqual(header_length, 21)

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

    def test_version_flag_bit_decoded(self) -> None:
        raw = build_header(message_id=0x0002, body_length=0, version_flag=False)
        header, _ = parse_header(raw)
        self.assertFalse(header.is_2019_version)

    def test_protocol_version_byte_decoded(self) -> None:
        raw = build_header(message_id=0x0002, body_length=0, protocol_version=0x02)
        header, _ = parse_header(raw)
        self.assertEqual(header.protocol_version, 0x02)

    def test_terminal_phone_leading_zero_preserved(self) -> None:
        phone = "00000000001234567890"
        self.assertEqual(len(phone), 20)
        raw = build_header(message_id=0x0002, body_length=0, terminal_phone=phone)
        header, _ = parse_header(raw)
        self.assertEqual(header.terminal_phone, phone)

    def test_truncated_header_raises(self) -> None:
        with self.assertRaises(MalformedFrameError):
            parse_header(bytes([0x00, 0x02, 0x00, 0x00]))  # only 4 of 17 bytes

    def test_subpackage_bit_set_but_block_missing_raises(self) -> None:
        # Base 17 bytes only, but subpackage bit is set in body_attributes.
        raw = bytearray(build_header(message_id=0x0200, body_length=0))
        raw[
            2
        ] |= 0b0010_0000  # set bit 13 of body_attributes (high byte, bit 5 of byte)
        with self.assertRaises(MalformedFrameError):
            parse_header(bytes(raw))

    def test_invalid_bcd_nibble_raises(self) -> None:
        raw = bytearray(build_header(message_id=0x0002, body_length=0))
        raw[5] = 0xFA  # nibble 0xF is not a valid BCD digit (offset 5 = start of phone)
        with self.assertRaises(MalformedFrameError):
            parse_header(bytes(raw))


if __name__ == "__main__":
    unittest.main()
