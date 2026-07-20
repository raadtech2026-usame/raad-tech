"""Application-layer tests for `video`'s `VideoApplicationService` (Backend Stabilization
phase). Stdlib `unittest` — no `pytest` (not an approved dependency), mirroring
`test_billing_application.py`'s exact structure. Uses an in-memory fake repository bundled onto
a fake `VideoUnitOfWork`, plus a fake `VideoProviderPort` — no SQLAlchemy, no FastAPI, no real
database, no live vendor/hardware video API (this phase's own explicit constraint).

Covers: the documented "no provider bound -> NotImplementedError at the activation step,
VideoSession already persisted as REQUESTED" behavior for both `request_live_video` and
`request_playback_video`, the successful-activation path with a bound fake provider (stream_url
surfaced on the DTO), `stop_video_session` with and without a bound provider, and
`get_video_session_by_id`'s not-found path.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from raad.core.errors.exceptions import NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.video.application.commands import (
    RequestLiveVideoCommand,
    RequestPlaybackVideoCommand,
    StopVideoSessionCommand,
)
from raad.modules.video.application.ports import VideoProviderPort, VideoUnitOfWork
from raad.modules.video.application.queries import GetVideoSessionByIdQuery
from raad.modules.video.application.services import VideoApplicationService
from raad.modules.video.domain.entities import VideoSession
from raad.modules.video.domain.repositories import VideoSessionRepository
from raad.modules.video.domain.value_objects import VideoSessionId

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
NON_EXISTENT_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 7, 21, 8, 0, 0, tzinfo=timezone.utc))


class SequentialIdGenerator(IdGenerator):
    """26-char, valid-Crockford-Base32 ULID-shaped ids, unique per call — mirrors
    `test_billing_application.py`'s identical helper exactly."""

    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"  # 20 chars

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


def make_actor() -> Principal:
    return Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=VALID_ORG_ULID)


class InMemoryVideoSessionRepository(VideoSessionRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, VideoSession] = {}

    async def get(self, video_session_id: VideoSessionId) -> VideoSession | None:
        return self.by_id.get(str(video_session_id))

    def add(self, video_session: VideoSession) -> None:
        self.by_id[str(video_session.id)] = video_session

    async def list_all(self) -> list[VideoSession]:
        return list(self.by_id.values())


class FakeVideoUnitOfWork(VideoUnitOfWork):
    def __init__(self, video_sessions: InMemoryVideoSessionRepository) -> None:
        self.video_sessions = video_sessions
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeVideoProvider(VideoProviderPort):
    def __init__(self, stream_url: str = "https://stream.example/token-abc") -> None:
        self.stream_url = stream_url
        self.start_live_calls: list[dict] = []
        self.start_playback_calls: list[dict] = []
        self.stop_calls: list[dict] = []

    async def start_live(self, *, device_id: str, camera_id: str, reference: str) -> str:
        self.start_live_calls.append(
            {"device_id": device_id, "camera_id": camera_id, "reference": reference}
        )
        return self.stream_url

    async def start_playback(
        self,
        *,
        device_id: str,
        camera_id: str,
        window_start: datetime,
        window_end: datetime,
        reference: str,
    ) -> str:
        self.start_playback_calls.append(
            {
                "device_id": device_id,
                "camera_id": camera_id,
                "window_start": window_start,
                "window_end": window_end,
                "reference": reference,
            }
        )
        return self.stream_url

    async def stop(self, *, reference: str) -> None:
        self.stop_calls.append({"reference": reference})


def make_uow() -> FakeVideoUnitOfWork:
    return FakeVideoUnitOfWork(InMemoryVideoSessionRepository())


def make_service(provider: VideoProviderPort | None = None) -> VideoApplicationService:
    return VideoApplicationService(
        clock=CLOCK, id_generator=SequentialIdGenerator(), video_provider=provider
    )


class RequestLiveVideoTests(unittest.IsolatedAsyncioTestCase):
    async def test_without_provider_persists_requested_then_raises(self) -> None:
        service = make_service(provider=None)
        uow = make_uow()

        with self.assertRaises(NotImplementedError):
            await service.request_live_video(
                RequestLiveVideoCommand(
                    organization_id=VALID_ORG_ULID,
                    device_id="device-ref-1",
                    camera_id="camera-ref-1",
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.video_sessions.by_id), 1)
        persisted = next(iter(uow.video_sessions.by_id.values()))
        self.assertEqual(persisted.status.value, "requested")

    async def test_with_bound_provider_activates_and_returns_stream_url(self) -> None:
        provider = FakeVideoProvider()
        service = make_service(provider=provider)
        uow = make_uow()

        session = await service.request_live_video(
            RequestLiveVideoCommand(
                organization_id=VALID_ORG_ULID,
                device_id="device-ref-2",
                camera_id="camera-ref-2",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(session.status, "active")
        self.assertEqual(session.stream_url, provider.stream_url)
        self.assertEqual(len(provider.start_live_calls), 1)


class RequestPlaybackVideoTests(unittest.IsolatedAsyncioTestCase):
    async def test_without_provider_persists_requested_then_raises(self) -> None:
        service = make_service(provider=None)
        uow = make_uow()
        start = datetime(2026, 7, 20, 9, 0, 0)
        end = start + timedelta(minutes=15)

        with self.assertRaises(NotImplementedError):
            await service.request_playback_video(
                RequestPlaybackVideoCommand(
                    organization_id=VALID_ORG_ULID,
                    device_id="device-ref-3",
                    camera_id="camera-ref-3",
                    window_start=start,
                    window_end=end,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        persisted = next(iter(uow.video_sessions.by_id.values()))
        self.assertEqual(persisted.status.value, "requested")
        self.assertEqual(persisted.purpose.value, "playback")

    async def test_with_bound_provider_activates_and_returns_stream_url(self) -> None:
        provider = FakeVideoProvider()
        service = make_service(provider=provider)
        uow = make_uow()
        start = datetime(2026, 7, 20, 9, 0, 0)
        end = start + timedelta(minutes=15)

        session = await service.request_playback_video(
            RequestPlaybackVideoCommand(
                organization_id=VALID_ORG_ULID,
                device_id="device-ref-4",
                camera_id="camera-ref-4",
                window_start=start,
                window_end=end,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(session.status, "active")
        self.assertEqual(session.stream_url, provider.stream_url)
        self.assertEqual(len(provider.start_playback_calls), 1)


class StopVideoSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_without_provider_still_ends_session_locally(self) -> None:
        service = make_service(provider=None)
        uow = make_uow()
        with self.assertRaises(NotImplementedError):
            await service.request_live_video(
                RequestLiveVideoCommand(
                    organization_id=VALID_ORG_ULID,
                    device_id="device-ref-5",
                    camera_id="camera-ref-5",
                    actor=make_actor(),
                ),
                uow=uow,
            )
        session_id = next(iter(uow.video_sessions.by_id.values())).id.value

        stopped = await service.stop_video_session(
            StopVideoSessionCommand(video_session_id=session_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(stopped.status, "ended")

    async def test_stop_with_bound_provider_calls_stop_and_ends_session(self) -> None:
        provider = FakeVideoProvider()
        service = make_service(provider=provider)
        uow = make_uow()
        session = await service.request_live_video(
            RequestLiveVideoCommand(
                organization_id=VALID_ORG_ULID,
                device_id="device-ref-6",
                camera_id="camera-ref-6",
                actor=make_actor(),
            ),
            uow=uow,
        )

        stopped = await service.stop_video_session(
            StopVideoSessionCommand(video_session_id=session.id, actor=make_actor()), uow=uow
        )
        self.assertEqual(stopped.status, "ended")
        self.assertEqual(len(provider.stop_calls), 1)

    async def test_stop_missing_session_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.stop_video_session(
                StopVideoSessionCommand(
                    video_session_id=NON_EXISTENT_ID, actor=make_actor()
                ),
                uow=uow,
            )


class GetVideoSessionByIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_not_found_raises(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.get_video_session_by_id(
                GetVideoSessionByIdQuery(video_session_id=NON_EXISTENT_ID), uow=uow
            )


if __name__ == "__main__":
    unittest.main()
