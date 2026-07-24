"""ServerConfig tests (Phase 9.1)."""

import os
import unittest

from src.config import ServerConfig


class ServerConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        config = ServerConfig()
        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 7808)

    def test_from_env_overrides(self) -> None:
        os.environ["JT808_HOST"] = "127.0.0.1"
        os.environ["JT808_PORT"] = "9999"
        try:
            config = ServerConfig.from_env()
            self.assertEqual(config.host, "127.0.0.1")
            self.assertEqual(config.port, 9999)
        finally:
            del os.environ["JT808_HOST"]
            del os.environ["JT808_PORT"]

    def test_from_env_falls_back_to_defaults(self) -> None:
        for key in [
            "JT808_HOST",
            "JT808_PORT",
            "JT808_READ_CHUNK_SIZE",
            "JT808_MAX_FRAME_SIZE",
            "JT808_IDLE_TIMEOUT_SECONDS",
            "JT808_SWEEP_INTERVAL_SECONDS",
        ]:
            os.environ.pop(key, None)
        config = ServerConfig.from_env()
        self.assertEqual(config, ServerConfig())


if __name__ == "__main__":
    unittest.main()
