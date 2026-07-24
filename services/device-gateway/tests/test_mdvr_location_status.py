"""GPS-normalization ACL tests (`protocol/location_status.py`), against the same real device-00007
worked examples `test_mdvr_parser.py` uses, cross-validated to real-world Shenzhen coordinates —
see `location_status.py`'s own module docstring for the full derivation."""

import unittest

from src.vendors.lsz.protocol.exceptions import MdvrMalformedMessageError
from src.vendors.lsz.protocol.location_status import parse_location_status

# The 18 location-and-status tokens from the V114 worked example in test_mdvr_parser.py.
_TOKENS = [
    "A0010",
    "114",
    "3",
    "338214000",
    "22",
    "40",
    "220920000",
    "0.00",
    "1521000",
    "000E00010101D383",
    "0000000000000000",
    "0.00",
    "0.00",
    "0.00",
    "0",
    "0.00",
    "2266",
    "0|0.00|0|0|0|0|0|0|0",
]


class LocationStatusParsingTests(unittest.TestCase):
    def test_fix_valid_and_satellite_count(self) -> None:
        status, _ = parse_location_status(_TOKENS + ["1"])
        self.assertTrue(status.fix_valid)
        self.assertEqual(status.satellite_count, 10)

    def test_latitude_matches_real_world_shenzhen_coordinate(self) -> None:
        status, _ = parse_location_status(_TOKENS + ["1"])
        # 22 deg + 40 min + 22.092 arcsec (220920000 / 10_000_000) - Shenzhen's real latitude.
        self.assertAlmostEqual(status.latitude, 22.672803, places=5)

    def test_longitude_matches_real_world_shenzhen_coordinate(self) -> None:
        status, _ = parse_location_status(_TOKENS + ["1"])
        # 114 deg + 3 min + 33.8214 arcsec (338214000 / 10_000_000) - Shenzhen's real longitude.
        self.assertAlmostEqual(status.longitude, 114.059395, places=5)

    def test_negative_degrees_yields_negative_result(self) -> None:
        tokens = list(_TOKENS)
        tokens[1] = "-114"  # longitude degrees
        status, _ = parse_location_status(tokens + ["1"])
        self.assertLess(status.longitude, 0)

    def test_remainder_is_whatever_follows_the_18_tokens(self) -> None:
        _, remainder = parse_location_status(_TOKENS + ["1"])
        self.assertEqual(remainder, ["1"])

    def test_component_status_alarm_parsed_as_hex(self) -> None:
        status, _ = parse_location_status(_TOKENS + ["1"])
        self.assertEqual(status.component_status_alarm, 0x000E00010101D383)

    def test_ground_speed_and_mileage_best_effort_fields(self) -> None:
        status, _ = parse_location_status(_TOKENS + ["1"])
        self.assertEqual(status.ground_speed_kph, 0.0)
        self.assertEqual(status.mileage_m, 0)

    def test_too_few_tokens_raises(self) -> None:
        with self.assertRaises(MdvrMalformedMessageError):
            parse_location_status(["A0010", "114"])

    def test_empty_positioning_status_raises(self) -> None:
        tokens = list(_TOKENS)
        tokens[0] = ""
        with self.assertRaises(MdvrMalformedMessageError):
            parse_location_status(tokens + ["1"])


if __name__ == "__main__":
    unittest.main()
