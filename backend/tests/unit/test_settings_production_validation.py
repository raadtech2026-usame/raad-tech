"""Audit finding B3 — `Settings.validate_on_startup`'s production guardrails.

**The bug these tests exist to prevent recurring.** The check used to be one line: reject an
*empty* `jwt_secret_key` when `environment=prod`. `docker/.env.example` ships that key with the
literal value `dev-only-change-me`, which is not empty — so an operator who copied the template
verbatim and set `RAAD_ENVIRONMENT=prod` got a deployment that started perfectly while signing
every JWT with a value published in this repository. The check existed and caught nothing.

Every rule is prod-only by design: dev and staging must keep booting from the template
unchanged, which is what placeholders are for.
"""

from __future__ import annotations

import unittest

from raad.core.config.settings import (
    AuthSettings,
    BrokerSettings,
    CorsSettings,
    DbSettings,
    Environment,
    RedisSettings,
    Settings,
)

_REAL_SECRET = "x7Qv2m9LpR4tZs8Nc1Wy6Kb3Ef0Hj5Ud" + "aB9dQ2fL7gT4nM1"


def _settings(**overrides) -> Settings:
    """A production `Settings` that is valid unless a test deliberately breaks one field."""
    base = dict(
        environment=Environment.PROD,
        auth=AuthSettings(jwt_secret_key=_REAL_SECRET),
        cors=CorsSettings(allowed_origins=["https://app.example.com"]),
        db=DbSettings(url="postgresql+asyncpg://raad:s3cure-p@ssw0rd@db:5432/raad"),
        redis=RedisSettings(url="redis://:s3cure-p@ssw0rd@redis:6379/0"),
        broker=BrokerSettings(url="redis://:s3cure-p@ssw0rd@redis:6379/1"),
    )
    base.update(overrides)
    return Settings(**base)


class ProductionValidationTests(unittest.TestCase):
    def test_a_fully_configured_production_settings_object_validates(self) -> None:
        _settings().validate_on_startup()  # must not raise

    def test_placeholder_jwt_secret_is_rejected(self) -> None:
        """The exact value `docker/.env.example` ships. This is the whole point of B3."""
        with self.assertRaises(ValueError) as ctx:
            _settings(
                auth=AuthSettings(jwt_secret_key="dev-only-change-me")
            ).validate_on_startup()
        self.assertIn("RAAD_AUTH__JWT_SECRET_KEY", str(ctx.exception))
        self.assertIn("placeholder", str(ctx.exception))

    def test_other_placeholder_markers_are_rejected(self) -> None:
        for value in (
            "change-me",
            "CHANGEME",
            "ci-only-not-a-real-secret",
            "some-placeholder-value-that-is-long-enough-to-pass-length",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _settings(
                        auth=AuthSettings(jwt_secret_key=value)
                    ).validate_on_startup()

    def test_empty_jwt_secret_is_still_rejected(self) -> None:
        """The original check must not be lost while widening it."""
        with self.assertRaises(ValueError) as ctx:
            _settings(auth=AuthSettings(jwt_secret_key="")).validate_on_startup()
        self.assertIn("must be set", str(ctx.exception))

    def test_short_jwt_secret_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _settings(auth=AuthSettings(jwt_secret_key="short")).validate_on_startup()
        self.assertIn("shorter than", str(ctx.exception))

    def test_localhost_cors_origin_is_rejected(self) -> None:
        """A localhost origin in prod is either a copied dev template (so the real dashboard's
        origin is missing and every browser request fails, looking like a frontend bug) or a
        genuine attempt to allow a local origin against production. Both are wrong."""
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            with self.subTest(origin=origin):
                with self.assertRaises(ValueError) as ctx:
                    _settings(
                        cors=CorsSettings(allowed_origins=[origin])
                    ).validate_on_startup()
                self.assertIn("RAAD_CORS__ALLOWED_ORIGINS", str(ctx.exception))

    def test_wildcard_cors_origin_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _settings(cors=CorsSettings(allowed_origins=["*"])).validate_on_startup()

    def test_placeholder_password_inside_a_connection_url_is_rejected(self) -> None:
        """Matched against the whole value, so a placeholder embedded in a URL is caught — which
        is exactly how `docker-compose.yml` composes these (`redis://:PASSWORD@redis:6379/1`)."""
        cases = {
            "RAAD_DB__URL": dict(
                db=DbSettings(
                    url="postgresql+asyncpg://raad:dev-only-change-me@db:5432/raad"
                )
            ),
            "RAAD_REDIS__URL": dict(
                redis=RedisSettings(url="redis://:dev-only-change-me@redis:6379/0")
            ),
            "RAAD_BROKER__URL": dict(
                broker=BrokerSettings(url="redis://:dev-only-change-me@redis:6379/1")
            ),
        }
        for expected, override in cases.items():
            with self.subTest(variable=expected):
                with self.assertRaises(ValueError) as ctx:
                    _settings(**override).validate_on_startup()
                self.assertIn(expected, str(ctx.exception))

    def test_every_problem_is_reported_at_once(self) -> None:
        """A deploy that fixes one variable only to fail on the next is a bad experience; the
        operator should see the whole list in one go."""
        with self.assertRaises(ValueError) as ctx:
            _settings(
                auth=AuthSettings(jwt_secret_key="dev-only-change-me"),
                cors=CorsSettings(allowed_origins=["http://localhost:5173"]),
            ).validate_on_startup()
        message = str(ctx.exception)
        self.assertIn("RAAD_AUTH__JWT_SECRET_KEY", message)
        self.assertIn("RAAD_CORS__ALLOWED_ORIGINS", message)

    def test_dev_and_staging_are_untouched(self) -> None:
        """The placeholders exist so dev works out of the box. Tightening prod must not break
        that — a dev environment that refuses to start from its own template is useless."""
        for environment in (Environment.DEV, Environment.STAGING):
            with self.subTest(environment=environment):
                Settings(
                    environment=environment,
                    auth=AuthSettings(jwt_secret_key="dev-only-change-me"),
                    cors=CorsSettings(allowed_origins=["http://localhost:5173"]),
                    broker=BrokerSettings(
                        url="redis://:dev-only-change-me@redis:6379/1"
                    ),
                ).validate_on_startup()  # must not raise

    def test_broker_stream_cap_is_deliberately_not_required(self) -> None:
        """Audit finding B2's *prescription* was wrong and must not be reintroduced. Requiring
        `stream_max_length > 0` would mandate the configuration that caused a live outage on
        2026-09-02 — trimming evicts the device-registration events `DeviceRegistryProjection`
        rebuilds from on cold start, and the physical MDVR stopped authenticating entirely.
        This test pins that 0 stays valid in production, so a future well-intentioned change
        cannot quietly re-break device auth."""
        _settings(
            broker=BrokerSettings(
                url="redis://:s3cure-p@ssw0rd@redis:6379/1", stream_max_length=0
            )
        ).validate_on_startup()  # must not raise


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
