"""`RelayConfig.validate_on_startup` — P0 security fix (2026-09-10): a missing/empty/placeholder/
weak `JT1078_RELAY_VIEWER_TOKEN_SECRET` must fail loudly before the relay accepts a single
connection, in every environment except development. Mirrors
`raad.core.config.settings.Settings.validate_on_startup`'s own test coverage shape exactly.
"""

import unittest

from src.config import RelayConfig


def _prod_config(secret: str) -> RelayConfig:
    return RelayConfig(environment="prod", viewer_token_secret=secret.encode("utf-8"))


class ProductionSecretValidationTests(unittest.TestCase):
    def test_missing_secret_fails_in_production(self) -> None:
        config = RelayConfig(environment="prod", viewer_token_secret=b"")
        with self.assertRaisesRegex(ValueError, "must be set to a real, non-empty value"):
            config.validate_on_startup()

    def test_empty_secret_fails_in_production(self) -> None:
        config = _prod_config("")
        with self.assertRaisesRegex(ValueError, "must be set to a real, non-empty value"):
            config.validate_on_startup()

    def test_whitespace_only_secret_fails_in_production(self) -> None:
        config = _prod_config("   \t  ")
        with self.assertRaisesRegex(ValueError, "must be set to a real, non-empty value"):
            config.validate_on_startup()

    def test_placeholder_secret_fails_in_production(self) -> None:
        config = _prod_config("dev-only-change-me")
        with self.assertRaisesRegex(ValueError, "development placeholder"):
            config.validate_on_startup()

    def test_placeholder_secret_matches_case_insensitively_as_a_substring(self) -> None:
        # A real deployment that only appends to the template default (e.g.
        # "MY-dev-only-change-me-2026") is still shipping the known placeholder, not a real key.
        config = _prod_config("MY-Dev-Only-Change-Me-2026")
        with self.assertRaisesRegex(ValueError, "development placeholder"):
            config.validate_on_startup()

    def test_short_secret_fails_in_production(self) -> None:
        config = _prod_config("too-short")
        with self.assertRaisesRegex(ValueError, "shorter than 32 characters"):
            config.validate_on_startup()

    def test_valid_secret_passes_in_production(self) -> None:
        config = _prod_config("a" * 32)
        config.validate_on_startup()  # must not raise

    def test_valid_generated_secret_passes_in_production(self) -> None:
        import secrets

        config = _prod_config(secrets.token_urlsafe(32))
        config.validate_on_startup()  # must not raise


class DevelopmentBehaviorPreservedTests(unittest.TestCase):
    """The whole point of a template default is that dev/CI keep booting unchanged — only
    `environment == "prod"` triggers the checks above, matching `Settings.validate_on_startup`'s
    own `Environment.PROD`-only gate."""

    def test_default_environment_is_development(self) -> None:
        self.assertEqual(RelayConfig().environment, "dev")

    def test_missing_secret_does_not_fail_in_development(self) -> None:
        config = RelayConfig(environment="dev", viewer_token_secret=b"")
        config.validate_on_startup()  # must not raise

    def test_placeholder_secret_does_not_fail_in_development(self) -> None:
        config = RelayConfig(environment="dev", viewer_token_secret=b"dev-only-change-me")
        config.validate_on_startup()  # must not raise

    def test_short_secret_does_not_fail_outside_production(self) -> None:
        config = RelayConfig(environment="staging", viewer_token_secret=b"x")
        config.validate_on_startup()  # must not raise — only "prod" is gated


class FromEnvEnvironmentParsingTests(unittest.TestCase):
    def test_from_env_reads_environment_case_insensitively(self) -> None:
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"JT1078_RELAY_ENVIRONMENT": "PROD"}, clear=False):
            config = RelayConfig.from_env()
        self.assertEqual(config.environment, "prod")

    def test_from_env_defaults_environment_to_dev_when_unset(self) -> None:
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=True):
            config = RelayConfig.from_env()
        self.assertEqual(config.environment, "dev")


if __name__ == "__main__":
    unittest.main()
