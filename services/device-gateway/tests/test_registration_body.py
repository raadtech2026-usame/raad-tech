"""`parse_registration_request` (JT/T 808-2019, `mdvrdocs/MDVR-808-1078-spec.pdf` §5.1.5
Table 5.3 — ADR-0025 §2): fixed-portion field decoding, null-padding stripping, GBK vehicle
identifier, and the too-short-body rejection.
"""

import unittest

from src.vendors.jt808.handlers.registration_body import parse_registration_request
from src.vendors.jt808.protocol.exceptions import MalformedFrameError


def _fixed_body(
    *,
    province_id: int = 11,
    city_county_id: int = 100,
    manufacturer_id: bytes = b"MFR01" + b"\x00" * 6,
    terminal_model: bytes = b"MODEL-X" + b"\x00" * 23,
    manufacturer_terminal_id: bytes = b"TERM001" + b"\x00" * 23,
    plate_color: int = 2,
    vehicle_identifier: bytes = b"",
) -> bytes:
    assert len(manufacturer_id) == 11
    assert len(terminal_model) == 30
    assert len(manufacturer_terminal_id) == 30
    return (
        province_id.to_bytes(2, "big")
        + city_county_id.to_bytes(2, "big")
        + manufacturer_id
        + terminal_model
        + manufacturer_terminal_id
        + bytes([plate_color])
        + vehicle_identifier
    )


class RegistrationBodyParsingTests(unittest.TestCase):
    def test_parses_all_fixed_fields(self) -> None:
        body = _fixed_body(province_id=11, city_county_id=100, plate_color=2)
        request = parse_registration_request(body)

        self.assertEqual(request.province_id, 11)
        self.assertEqual(request.city_county_id, 100)
        self.assertEqual(request.manufacturer_id, b"MFR01" + b"\x00" * 6)
        self.assertEqual(request.terminal_model, "MODEL-X")
        self.assertEqual(request.manufacturer_terminal_id, "TERM001")
        self.assertEqual(request.plate_color, 2)

    def test_strips_null_padding_from_terminal_model(self) -> None:
        body = _fixed_body(terminal_model=b"M" + b"\x00" * 29)
        request = parse_registration_request(body)
        self.assertEqual(request.terminal_model, "M")

    def test_vehicle_identifier_decodes_as_gbk(self) -> None:
        plate = "京A12345"
        body = _fixed_body(vehicle_identifier=plate.encode("gbk"))
        request = parse_registration_request(body)
        self.assertEqual(request.vehicle_identifier, plate)

    def test_empty_vehicle_identifier_is_empty_string(self) -> None:
        request = parse_registration_request(_fixed_body(vehicle_identifier=b""))
        self.assertEqual(request.vehicle_identifier, "")

    def test_too_short_body_raises_malformed_frame_error(self) -> None:
        with self.assertRaises(MalformedFrameError):
            parse_registration_request(
                b"\x00" * 75
            )  # one byte short of the fixed portion

    def test_empty_body_raises_malformed_frame_error(self) -> None:
        with self.assertRaises(MalformedFrameError):
            parse_registration_request(b"")

    def test_exactly_fixed_length_body_with_no_vehicle_identifier_parses(self) -> None:
        request = parse_registration_request(_fixed_body())
        self.assertEqual(request.vehicle_identifier, "")


if __name__ == "__main__":
    unittest.main()
