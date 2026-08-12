"""Shared `BCD[6]` datetime codec tests (`protocol/bcd_datetime.py`) — the encode/decode pair
promoted out of `handlers/position_body.py` for the JT/T 1078 video-signaling bodies."""

import unittest
from datetime import datetime, timezone

from src.vendors.jt808.protocol.bcd_datetime import (
    decode_bcd_datetime,
    decode_bcd_datetime_or_none,
    encode_bcd_datetime,
    encode_bcd_datetime_or_none,
)
from src.vendors.jt808.protocol.exceptions import MalformedFrameError


class BcdDatetimeTests(unittest.TestCase):
    def test_round_trips_through_gmt8(self) -> None:
        dt = datetime(2026, 8, 11, 3, 4, 5, tzinfo=timezone.utc)
        encoded = encode_bcd_datetime(dt)
        self.assertEqual(len(encoded), 6)
        decoded = decode_bcd_datetime(encoded)
        self.assertEqual(decoded, dt)

    def test_encodes_expected_bcd_bytes(self) -> None:
        # 2026-08-11 11:04:05 Beijing time (GMT+8) == 2026-08-11 03:04:05 UTC.
        dt = datetime(2026, 8, 11, 3, 4, 5, tzinfo=timezone.utc)
        encoded = encode_bcd_datetime(dt)
        self.assertEqual(encoded, bytes([0x26, 0x08, 0x11, 0x11, 0x04, 0x05]))

    def test_decode_rejects_invalid_bcd_nibble(self) -> None:
        with self.assertRaises(MalformedFrameError):
            decode_bcd_datetime(bytes([0xFA, 0x08, 0x11, 0x11, 0x04, 0x05]))

    def test_decode_rejects_invalid_calendar_date(self) -> None:
        with self.assertRaises(MalformedFrameError):
            decode_bcd_datetime(bytes([0x26, 0x13, 0x40, 0x11, 0x04, 0x05]))  # month 13, day 40

    def test_or_none_variants_treat_all_zero_as_no_constraint(self) -> None:
        self.assertIsNone(decode_bcd_datetime_or_none(b"\x00" * 6))
        self.assertEqual(encode_bcd_datetime_or_none(None), b"\x00" * 6)

    def test_or_none_variants_round_trip_a_real_value(self) -> None:
        dt = datetime(2026, 8, 11, 3, 4, 5, tzinfo=timezone.utc)
        encoded = encode_bcd_datetime_or_none(dt)
        self.assertNotEqual(encoded, b"\x00" * 6)
        self.assertEqual(decode_bcd_datetime_or_none(encoded), dt)


if __name__ == "__main__":
    unittest.main()
