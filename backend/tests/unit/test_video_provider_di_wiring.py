"""`VideoProviderPort` conditional-binding tests (JT1078 backend-integration phase) —
`core/di/bootstrap.build_container` with a bare `Settings()` needs no real database or Redis
connection (every client this file constructs is lazy, matching `redis.asyncio.Redis`/SQLAlchemy
`AsyncEngine`'s own established "no I/O at construction" behavior) — this exercises the *real*
composition root, not a hand-rolled substitute, the strongest proof the wiring is actually correct
short of a live integration environment.

**A real ordering bug this phase's own implementation found and fixed**: `VideoApplicationService`
used to be bound *before* the broker block that conditionally binds `VideoProviderPort` -
`container.try_resolve(VideoProviderPort)` would have silently seen "nothing bound" even when a
broker *was* configured, since DI resolution order matters for `bind_singleton`-based containers.
`test_broker_and_signaling_url_wires_the_video_application_service_to_the_adapter` is this
specific regression's own coverage.
"""

from __future__ import annotations

import unittest

from raad.core.config.settings import BrokerSettings, DevicePlaneSettings, Settings
from raad.core.di.bootstrap import build_container
from raad.modules.video.application.ports import VideoProviderPort
from raad.modules.video.application.services import VideoApplicationService
from raad.modules.video.infra.adapters import Jt1078RelayAdapter

_BROKER_URL = "redis://localhost:6379/1"
_SIGNALING_URL = "ws://jt1078-relay:7911"


class VideoProviderDiWiringTests(unittest.TestCase):
    def test_unconfigured_settings_leave_video_provider_port_unbound(self) -> None:
        # `_env_file=None` only skips loading a `.env` FILE — pydantic-settings' `BaseSettings`
        # still reads real OS environment variables regardless, so this test silently asserted
        # against whatever ambient `RAAD_BROKER__URL`/`RAAD_DEVICE_PLANE__JT1078_SIGNALING_URL`
        # the *process* happened to have (both set to real values by `docker-compose.yml` inside
        # this repo's own dev containers, which never fail this in CI — CI sets neither — but
        # reliably did when this suite ran inside `raad-backend` itself, 2026-09-10). Passing both
        # explicitly as empty strings is what actually asserts "unconfigured," everywhere.
        settings = Settings(
            _env_file=None,
            broker=BrokerSettings(url=""),
            device_plane=DevicePlaneSettings(jt1078_signaling_url=""),
        )
        container = build_container(settings)
        with self.assertRaises(LookupError):
            container.resolve(VideoProviderPort)

    def test_broker_alone_without_signaling_url_leaves_it_unbound(self) -> None:
        settings = Settings(
            _env_file=None,
            broker=BrokerSettings(url=_BROKER_URL),
            device_plane=DevicePlaneSettings(jt1078_signaling_url=""),
        )
        container = build_container(settings)
        with self.assertRaises(LookupError):
            container.resolve(VideoProviderPort)

    def test_signaling_url_alone_without_a_broker_leaves_it_unbound(self) -> None:
        settings = Settings(
            _env_file=None,
            broker=BrokerSettings(url=""),
            device_plane=DevicePlaneSettings(jt1078_signaling_url=_SIGNALING_URL),
        )
        container = build_container(settings)
        with self.assertRaises(LookupError):
            container.resolve(VideoProviderPort)

    def test_broker_and_signaling_url_together_bind_a_real_jt1078_relay_adapter(self) -> None:
        settings = Settings(
            _env_file=None,
            broker=BrokerSettings(url=_BROKER_URL),
            device_plane=DevicePlaneSettings(jt1078_signaling_url=_SIGNALING_URL),
        )
        container = build_container(settings)
        provider = container.resolve(VideoProviderPort)
        self.assertIsInstance(provider, Jt1078RelayAdapter)

    def test_broker_and_signaling_url_wires_the_video_application_service_to_the_adapter(
        self,
    ) -> None:
        settings = Settings(
            _env_file=None,
            broker=BrokerSettings(url=_BROKER_URL),
            device_plane=DevicePlaneSettings(jt1078_signaling_url=_SIGNALING_URL),
        )
        container = build_container(settings)
        provider = container.resolve(VideoProviderPort)
        service = container.resolve(VideoApplicationService)
        self.assertIs(service._video_provider, provider)

    def test_video_application_service_stays_constructible_without_any_provider(self) -> None:
        """The always-constructible, optional-provider posture (mirrors `BillingApplicationService.
        payment_provider`) must still hold - a caller must never fail to even *resolve* the
        service just because no video provider is configured."""
        settings = Settings(
            _env_file=None,
            broker=BrokerSettings(url=""),
            device_plane=DevicePlaneSettings(jt1078_signaling_url=""),
        )
        container = build_container(settings)
        service = container.resolve(VideoApplicationService)
        self.assertIsNone(service._video_provider)


if __name__ == "__main__":
    unittest.main()
