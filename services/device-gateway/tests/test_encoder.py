"""Outbound frame encoding tests (Phase 9.4) — round-trips against Phase 9.3's decoder."""

import unittest

from src.protocol.encoder import build_frame
from src.protocol.exceptions import MalformedFrameError
from src.protocol.header import encode_bcd_phone
from src.protocol.parser import PacketParser
from datetime import datetime, timezone


class BuildFrameTests(unittest.TestCase):
    def test_round_trips_through_the_real_parser(self) -> None:
        frame = build_frame(
            message_id=0x8001,
            terminal_phone="013800138000",
            serial_no=7,
            body=b"\x00\x01\x00\x02\x03",
        )
        # Strip delimiters the way Phase 9.1's FrameBuffer would before handing to the parser.
        raw = frame[1:-1]
        message = PacketParser().parse(raw, received_at=datetime.now(timezone.utc))
        self.assertEqual(message.message_id, 0x8001)
        self.assertEqual(message.terminal_id, "013800138000")
        self.assertEqual(message.serial_no, 7)
        self.assertEqual(message.body, b"\x00\x01\x00\x02\x03")

    def test_body_with_delimiter_and_escape_bytes_round_trips(self) -> None:
        body = bytes([0x30, 0x7E, 0x08, 0x7D, 0x55])
        frame = build_frame(
            message_id=0x8001, terminal_phone="013800138000", serial_no=1, body=body
        )
        message = PacketParser().parse(
            frame[1:-1], received_at=datetime.now(timezone.utc)
        )
        self.assertEqual(message.body, body)

    def test_frame_starts_and_ends_with_delimiter(self) -> None:
        frame = build_frame(
            message_id=0x0002, terminal_phone="013800138000", serial_no=1
        )
        self.assertEqual(frame[0], 0x7E)
        self.assertEqual(frame[-1], 0x7E)

    def test_body_too_large_raises(self) -> None:
        with self.assertRaises(MalformedFrameError):
            build_frame(
                message_id=0x8001,
                terminal_phone="013800138000",
                serial_no=1,
                body=b"x" * 1024,
            )

    def test_encode_bcd_phone_round_trips_with_decode(self) -> None:
        from src.protocol.header import parse_header

        encoded = encode_bcd_phone("013800138000")
        header_bytes = (
            (0x0002).to_bytes(2, "big")
            + (0).to_bytes(2, "big")
            + encoded
            + (1).to_bytes(2, "big")
        )
        header, _ = parse_header(header_bytes)
        self.assertEqual(header.terminal_phone, "013800138000")

    def test_encode_bcd_phone_rejects_wrong_length(self) -> None:
        with self.assertRaises(MalformedFrameError):
            encode_bcd_phone("123")

    def test_encode_bcd_phone_rejects_non_digits(self) -> None:
        with self.assertRaises(MalformedFrameError):
            encode_bcd_phone("01380013800A")


if __name__ == "__main__":
    unittest.main()
