"""`gps_validation.is_plausible_coordinate` — root-cause fix, RAAD Live Tracking wrong-location
investigation. See `src/gps_validation.py`'s own module docstring for the full rationale."""

import math
import unittest

from src.gps_validation import is_plausible_coordinate


class IsPlausibleCoordinateTests(unittest.TestCase):
    def test_a_real_world_coordinate_is_plausible(self) -> None:
        self.assertTrue(is_plausible_coordinate(2.0469, 45.3182))  # Mogadishu

    def test_null_island_is_not_plausible(self) -> None:
        self.assertFalse(is_plausible_coordinate(0.0, 0.0))

    def test_near_null_island_within_epsilon_is_not_plausible(self) -> None:
        self.assertFalse(is_plausible_coordinate(0.00001, -0.00002))

    def test_a_real_coordinate_near_the_equator_and_prime_meridian_is_still_plausible(
        self,
    ) -> None:
        # Guards against an overly-broad null-island epsilon swallowing genuine positions.
        self.assertTrue(is_plausible_coordinate(0.01, 0.01))

    def test_latitude_out_of_range_is_not_plausible(self) -> None:
        self.assertFalse(is_plausible_coordinate(90.0001, 0.5))
        self.assertFalse(is_plausible_coordinate(-90.0001, 0.5))

    def test_longitude_out_of_range_is_not_plausible(self) -> None:
        self.assertFalse(is_plausible_coordinate(10.0, 180.0001))
        self.assertFalse(is_plausible_coordinate(10.0, -180.0001))

    def test_boundary_values_are_plausible(self) -> None:
        self.assertTrue(is_plausible_coordinate(90.0, 180.0))
        self.assertTrue(is_plausible_coordinate(-90.0, -180.0))

    def test_nan_is_not_plausible(self) -> None:
        self.assertFalse(is_plausible_coordinate(math.nan, 45.0))
        self.assertFalse(is_plausible_coordinate(2.0, math.nan))

    def test_infinity_is_not_plausible(self) -> None:
        self.assertFalse(is_plausible_coordinate(math.inf, 45.0))
        self.assertFalse(is_plausible_coordinate(2.0, -math.inf))


if __name__ == "__main__":
    unittest.main()
