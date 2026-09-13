"""`CacheConfig` — root-cause fix, RAAD Live Tracking wrong-location investigation. See
`src/cache_config.py`'s own module docstring for the bug this closes."""

import os
import unittest

from src.cache_config import CacheConfig


class CacheConfigFromEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original = os.environ.pop("DEVICE_GATEWAY_REDIS_URL", None)

    def tearDown(self) -> None:
        if self._original is not None:
            os.environ["DEVICE_GATEWAY_REDIS_URL"] = self._original
        else:
            os.environ.pop("DEVICE_GATEWAY_REDIS_URL", None)

    def test_defaults_to_none_when_unset(self) -> None:
        self.assertIsNone(CacheConfig.from_env().url)

    def test_reads_a_configured_url(self) -> None:
        os.environ["DEVICE_GATEWAY_REDIS_URL"] = "redis://:pw@redis:6379/0"
        self.assertEqual(CacheConfig.from_env().url, "redis://:pw@redis:6379/0")

    def test_empty_string_is_treated_as_unset(self) -> None:
        os.environ["DEVICE_GATEWAY_REDIS_URL"] = ""
        self.assertIsNone(CacheConfig.from_env().url)


if __name__ == "__main__":
    unittest.main()
