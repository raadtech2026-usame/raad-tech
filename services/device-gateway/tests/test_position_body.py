"""`parse_position_report_body` (Phase 9.6; JT/T 808-2013 §8.18 Table 23): fixed 28-byte field
decoding, hemisphere sign application (status bits 2/3), speed unit conversion (1/10 km/h ->
whole km/h), heading passthrough, and BCD GMT+8 time -> UTC conversion.
"""

import unittest
from datetime import datetime, timezone

from src.handlers.position_body import parse_position_report_body
from src.protocol.exceptions import MalformedFrameError


def _bcd_byte(tens: int, ones: int) -> int:
    return (tens << 4) | ones


def _encode_bcd_time(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> bytes:
    yy = year - 2000
    return bytes(
        [
            _bcd_byte(yy // 10, yy % 10),
            _bcd_byte(month // 10, month % 10),
            _bcd_byte(day // 10, day % 10),
            _bcd_byte(hour // 10, hour % 10),
            _bcd_byte(minute // 10, minute % 10),
            _bcd_byte(second // 10, second % 10),
        ]
    )


def _build_body(
    *,
    alarm_flags: int = 0,
    status: int = 0b0011,  # ACC on, positioned, north, east
    raw_latitude: int = 39_123_456,
    raw_longitude: int = 116_123_456,
    altitude_m: int = 50,
    raw_speed: int = 137,  # 13.7 km/h
    heading_deg: int = 270,
    time_bytes: bytes = None,
) -> bytes:
    if time_bytes is None:
        time_bytes = _encode_bcd_time(2026, 7, 15, 10, 20, 30)
    return (
        alarm_flags.to_bytes(4, "big")
        + status.to_bytes(4, "big")
        + raw_latitude.to_bytes(4, "big")
        + raw_longitude.to_bytes(4, "big")
        + altitude_m.to_bytes(2, "big")
        + raw_speed.to_bytes(2, "big")
        + heading_deg.to_bytes(2, "big")
        + time_bytes
    )


class PositionBodyParsingTests(unittest.TestCase):
    def test_parses_alarm_flags_and_status_verbatim(self) -> None:
        report = parse_position_report_body(
            _build_body(alarm_flags=0x00000001, status=0b1011)
        )
        self.assertEqual(report.alarm_flags, 0x00000001)
        self.assertEqual(report.status, 0b1011)

    def test_north_east_hemisphere_yields_positive_lat_lng(self) -> None:
        report = parse_position_report_body(
            _build_body(
                status=0b0000, raw_latitude=39_123_456, raw_longitude=116_123_456
            )
        )
        self.assertAlmostEqual(report.latitude, 39.123456)
        self.assertAlmostEqual(report.longitude, 116.123456)

    def test_south_latitude_bit_negates_latitude(self) -> None:
        report = parse_position_report_body(
            _build_body(
                status=0b0100, raw_latitude=39_123_456, raw_longitude=116_123_456
            )
        )
        self.assertAlmostEqual(report.latitude, -39.123456)
        self.assertAlmostEqual(report.longitude, 116.123456)

    def test_west_longitude_bit_negates_longitude(self) -> None:
        report = parse_position_report_body(
            _build_body(
                status=0b1000, raw_latitude=39_123_456, raw_longitude=116_123_456
            )
        )
        self.assertAlmostEqual(report.latitude, 39.123456)
        self.assertAlmostEqual(report.longitude, -116.123456)

    def test_south_and_west_both_negate(self) -> None:
        report = parse_position_report_body(
            _build_body(status=0b1100, raw_latitude=1_000_000, raw_longitude=2_000_000)
        )
        self.assertAlmostEqual(report.latitude, -1.0)
        self.assertAlmostEqual(report.longitude, -2.0)

    def test_latitude_longitude_precision_is_one_millionth_degree(self) -> None:
        report = parse_position_report_body(
            _build_body(raw_latitude=1, raw_longitude=1, status=0b0000)
        )
        self.assertAlmostEqual(report.latitude, 0.000001)
        self.assertAlmostEqual(report.longitude, 0.000001)

    def test_altitude_parses_as_meters(self) -> None:
        report = parse_position_report_body(_build_body(altitude_m=1234))
        self.assertEqual(report.altitude_m, 1234)

    def test_speed_converts_from_tenths_kph_to_whole_kph(self) -> None:
        report = parse_position_report_body(_build_body(raw_speed=137))  # 13.7 -> 14
        self.assertEqual(report.speed_kph, 14)

    def test_zero_speed_maps_to_zero(self) -> None:
        report = parse_position_report_body(_build_body(raw_speed=0))
        self.assertEqual(report.speed_kph, 0)

    def test_heading_passes_through_unchanged(self) -> None:
        report = parse_position_report_body(_build_body(heading_deg=359))
        self.assertEqual(report.heading_deg, 359)

    def test_north_heading_is_zero(self) -> None:
        report = parse_position_report_body(_build_body(heading_deg=0))
        self.assertEqual(report.heading_deg, 0)

    def test_bcd_time_decodes_from_gmt8_to_utc(self) -> None:
        report = parse_position_report_body(
            _build_body(time_bytes=_encode_bcd_time(2026, 7, 15, 10, 20, 30))
        )
        self.assertEqual(
            report.event_time, datetime(2026, 7, 15, 2, 20, 30, tzinfo=timezone.utc)
        )

    def test_event_time_is_timezone_aware_utc(self) -> None:
        report = parse_position_report_body(_build_body())
        self.assertEqual(report.event_time.tzinfo, timezone.utc)

    def test_trailing_additional_info_bytes_are_ignored_not_an_error(self) -> None:
        body = (
            _build_body() + b"\x01\x04\x00\x00\x00\x00"
        )  # a fake additional-info item
        report = parse_position_report_body(body)
        self.assertEqual(report.altitude_m, 50)

    def test_too_short_body_raises_malformed_frame_error(self) -> None:
        with self.assertRaises(MalformedFrameError):
            parse_position_report_body(b"\x00" * 27)

    def test_empty_body_raises_malformed_frame_error(self) -> None:
        with self.assertRaises(MalformedFrameError):
            parse_position_report_body(b"")

    def test_invalid_bcd_nibble_in_time_raises_malformed_frame_error(self) -> None:
        bad_time = bytes([0xFF, 0x07, 0x15, 0x10, 0x20, 0x30])
        with self.assertRaises(MalformedFrameError):
            parse_position_report_body(_build_body(time_bytes=bad_time))

    def test_invalid_calendar_date_raises_malformed_frame_error(self) -> None:
        bad_time = _encode_bcd_time(2026, 13, 40, 25, 61, 61)  # month 13, day 40, etc.
        with self.assertRaises(MalformedFrameError):
            parse_position_report_body(_build_body(time_bytes=bad_time))


if __name__ == "__main__":
    unittest.main()
