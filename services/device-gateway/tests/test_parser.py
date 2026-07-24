"""End-to-end PacketParser tests (Phase 9.3): unescape -> verify checksum -> parse header ->
extract/reassemble body -> InboundMessage. Frames are built by hand (escape + checksum) using
independent reference logic, not by reusing the modules under test.
"""

import unittest
from datetime import datetime, timezone

from src.protocol.checksum import compute_checksum
from src.protocol.escaping import ESCAPE_MARKER
from src.protocol.exceptions import ChecksumError, MalformedFrameError
from src.protocol.parser import PacketParser
from tests.test_header import bcd_phone


def escape(data: bytes) -> bytes:
    """Independent reference escaper (mirrors `escaping.unescape`'s rules, not implemented
    in `src/` since only the receive path is this phase's job — built here purely to
    construct realistic on-the-wire test fixtures)."""
    result = bytearray()
    for byte in data:
        if byte == 0x7E:
            result += bytes([ESCAPE_MARKER, 0x02])
        elif byte == ESCAPE_MARKER:
            result += bytes([ESCAPE_MARKER, 0x01])
        else:
            result.append(byte)
    return bytes(result)


def build_raw_frame(
    *,
    message_id: int,
    terminal_phone: str,
    serial_no: int,
    body: bytes = b"",
    encryption_method: int = 0,
    is_subpackaged: bool = False,
    total_packages: int | None = None,
    package_sequence: int | None = None,
    corrupt_checksum: bool = False,
) -> bytes:
    """Builds a raw frame exactly as Phase 9.1's `FrameBuffer` would hand it to the parser:
    delimiters already stripped, still escaped."""
    body_attributes = len(body) & 0x03FF
    body_attributes |= (encryption_method & 0x07) << 10
    if is_subpackaged:
        body_attributes |= 1 << 13

    header = bytearray()
    header += message_id.to_bytes(2, "big")
    header += body_attributes.to_bytes(2, "big")
    header += bcd_phone(terminal_phone)
    header += serial_no.to_bytes(2, "big")
    if is_subpackaged:
        assert total_packages is not None and package_sequence is not None
        header += total_packages.to_bytes(2, "big")
        header += package_sequence.to_bytes(2, "big")

    unescaped_payload = bytes(header) + body
    checksum = compute_checksum(unescaped_payload)
    if corrupt_checksum:
        checksum ^= 0xFF

    return escape(unescaped_payload + bytes([checksum]))


class PacketParserTests(unittest.TestCase):
    def test_parses_simple_heartbeat_message(self) -> None:
        raw = build_raw_frame(
            message_id=0x0002, terminal_phone="013800138000", serial_no=1
        )
        parser = PacketParser()
        message = parser.parse(raw, received_at=datetime.now(timezone.utc))

        self.assertIsNotNone(message)
        self.assertEqual(message.message_id, 0x0002)
        self.assertEqual(message.terminal_id, "013800138000")
        self.assertEqual(message.serial_no, 1)
        self.assertEqual(message.body, b"")
        self.assertEqual(message.encryption_method, 0)
        self.assertIsNotNone(message.raw_ref)

    def test_parses_message_with_body(self) -> None:
        body = bytes(range(20))
        raw = build_raw_frame(
            message_id=0x0200, terminal_phone="013800138000", serial_no=42, body=body
        )
        message = PacketParser().parse(raw, received_at=datetime.now(timezone.utc))
        self.assertEqual(message.body, body)

    def test_parses_message_whose_body_contains_delimiter_and_escape_bytes(
        self,
    ) -> None:
        """Confirms escaping/unescaping round-trips correctly even when the body itself
        contains bytes that must be escaped on the wire (0x7e, 0x7d) - the exact case the
        spec's own worked example (§4.4.2) demonstrates."""
        body = bytes([0x30, 0x7E, 0x08, 0x7D, 0x55])
        raw = build_raw_frame(
            message_id=0x0200, terminal_phone="013800138000", serial_no=1, body=body
        )
        message = PacketParser().parse(raw, received_at=datetime.now(timezone.utc))
        self.assertEqual(message.body, body)

    def test_checksum_mismatch_raises(self) -> None:
        raw = build_raw_frame(
            message_id=0x0002,
            terminal_phone="013800138000",
            serial_no=1,
            corrupt_checksum=True,
        )
        with self.assertRaises(ChecksumError):
            PacketParser().parse(raw, received_at=datetime.now(timezone.utc))

    def test_frame_too_short_to_have_a_checksum_raises(self) -> None:
        # Checksum verification runs before header parsing (§4.4.2's documented receive
        # order): a single 0x01 byte splits into an empty payload + checksum_byte=0x01, and
        # compute_checksum(b"") == 0x00 != 0x01, so this fails checksum before ever reaching
        # header parsing. (0x00 would coincidentally "pass" checksum against an empty
        # payload - deliberately avoided here.)
        with self.assertRaises(ChecksumError):
            PacketParser().parse(bytes([0x01]), received_at=datetime.now(timezone.utc))

    def test_truncated_header_with_valid_checksum_raises_malformed(self) -> None:
        # A short payload that *does* pass checksum verification, so the failure genuinely
        # comes from header parsing (too few bytes for the 12-byte base), not checksum.
        payload = bytes([0x00, 0x02])
        checksum = compute_checksum(payload)
        raw = escape(payload + bytes([checksum]))
        with self.assertRaises(MalformedFrameError):
            PacketParser().parse(raw, received_at=datetime.now(timezone.utc))

    def test_body_shorter_than_declared_length_raises(self) -> None:
        # Hand-craft a header claiming body_length=10 but supply no body bytes.
        header = bytearray()
        header += (0x0200).to_bytes(2, "big")
        header += (10).to_bytes(2, "big")  # body_attributes: body_length=10, no flags
        header += bcd_phone("013800138000")
        header += (1).to_bytes(2, "big")
        checksum = compute_checksum(bytes(header))
        raw = escape(bytes(header) + bytes([checksum]))
        with self.assertRaises(MalformedFrameError):
            PacketParser().parse(raw, received_at=datetime.now(timezone.utc))

    def test_encrypted_body_passed_through_unexamined(self) -> None:
        encrypted_looking_body = bytes([0xDE, 0xAD, 0xBE, 0xEF])
        raw = build_raw_frame(
            message_id=0x0200,
            terminal_phone="013800138000",
            serial_no=1,
            body=encrypted_looking_body,
            encryption_method=0b001,  # bit 10 = RSA per §4.4.2
        )
        message = PacketParser().parse(raw, received_at=datetime.now(timezone.utc))
        self.assertEqual(message.encryption_method, 0b001)
        self.assertEqual(
            message.body, encrypted_looking_body
        )  # untouched, not decrypted

    def test_subpackaged_message_returns_none_until_complete(self) -> None:
        parser = PacketParser()
        part1 = build_raw_frame(
            message_id=0x0200,
            terminal_phone="013800138000",
            serial_no=1,
            body=b"AAAA",
            is_subpackaged=True,
            total_packages=2,
            package_sequence=1,
        )
        part2 = build_raw_frame(
            message_id=0x0200,
            terminal_phone="013800138000",
            serial_no=2,
            body=b"BBBB",
            is_subpackaged=True,
            total_packages=2,
            package_sequence=2,
        )

        result1 = parser.parse(part1, received_at=datetime.now(timezone.utc))
        self.assertIsNone(result1)

        result2 = parser.parse(part2, received_at=datetime.now(timezone.utc))
        self.assertIsNotNone(result2)
        self.assertEqual(result2.body, b"AAAABBBB")
        self.assertEqual(result2.terminal_id, "013800138000")

    def test_different_terminals_subpackaging_independently(self) -> None:
        parser = PacketParser()
        t1_part = build_raw_frame(
            message_id=0x0200,
            terminal_phone="013800138000",
            serial_no=1,
            body=b"X",
            is_subpackaged=True,
            total_packages=2,
            package_sequence=1,
        )
        t2_part = build_raw_frame(
            message_id=0x0200,
            terminal_phone="013900139000",
            serial_no=1,
            body=b"Y",
            is_subpackaged=True,
            total_packages=2,
            package_sequence=1,
        )
        self.assertIsNone(parser.parse(t1_part, received_at=datetime.now(timezone.utc)))
        self.assertIsNone(parser.parse(t2_part, received_at=datetime.now(timezone.utc)))
        self.assertEqual(len(parser._reassembler), 2)


if __name__ == "__main__":
    unittest.main()
