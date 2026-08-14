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
    MarkVideoSessionActiveCommand,
    MarkVideoSessionEndedCommand,
    MarkVideoSessionFailedCommand,
    RequestLiveVideoCommand,
    RequestPlaybackVideoCommand,
    StopVideoSessionCommand,
)
from raad.modules.video.application.ports import VideoProviderPort, VideoUnitOfWork
from raad.modules.video.application.queries import GetVideoSessionByIdQuery
from raad.modules.video.application.services import VideoApplicationService
from raad.modules.video.domain.entities import VideoSession
from raad.modules.video.domain.repositories import VideoSessionRepository
from raad.modules.video.domain.value_objects import (
    CameraId,
    DeviceId,
    OrganizationId,
    UserId,
    VideoSessionId,
)

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


SYSTEM_ACTOR = Principal(user_id="system", role=Role.FOUNDER, org_id=None)


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

    async def start_live(
        self, *, device_id: str, camera_id: str, terminal_id: str, channel_no: int, reference: str
    ) -> str:
        self.start_live_calls.append(
            {
                "device_id": device_id,
                "camera_id": camera_id,
                "terminal_id": terminal_id,
                "channel_no": channel_no,
                "reference": reference,
            }
        )
        return self.stream_url

    async def start_playback(
        self,
        *,
        device_id: str,
        camera_id: str,
        terminal_id: str,
        channel_no: int,
        window_start: datetime,
        window_end: datetime,
        reference: str,
    ) -> str:
        self.start_playback_calls.append(
            {
                "device_id": device_id,
                "camera_id": camera_id,
                "terminal_id": terminal_id,
                "channel_no": channel_no,
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
                    terminal_id="00000000013800138000",
                    channel_no=1,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.video_sessions.by_id), 1)
        persisted = next(iter(uow.video_sessions.by_id.values()))
        self.assertEqual(persisted.status.value, "requested")

    async def test_with_bound_provider_stays_requested_and_returns_stream_url(self) -> None:
        """ADR-0026 §7: no more eager `activate()` - `status` only flips to `active` once
        `events/subscribers.py` consumes the relay's own `VideoSessionActivated` event.
        `stream_url` is still returned immediately - it never depended on `status`."""
        provider = FakeVideoProvider()
        service = make_service(provider=provider)
        uow = make_uow()

        session = await service.request_live_video(
            RequestLiveVideoCommand(
                organization_id=VALID_ORG_ULID,
                device_id="device-ref-2",
                camera_id="camera-ref-2",
                terminal_id="00000000013800138000",
                channel_no=1,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(session.status, "requested")
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
                    terminal_id="00000000013800138000",
                    channel_no=1,
                    window_start=start,
                    window_end=end,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        persisted = next(iter(uow.video_sessions.by_id.values()))
        self.assertEqual(persisted.status.value, "requested")
        self.assertEqual(persisted.purpose.value, "playback")

    async def test_with_bound_provider_stays_requested_and_returns_stream_url(self) -> None:
        """ADR-0026 §7 - same reasoning as the live equivalent above."""
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
                terminal_id="00000000013800138000",
                channel_no=1,
                window_start=start,
                window_end=end,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(session.status, "requested")
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
                    terminal_id="00000000013800138000",
                    channel_no=1,
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
                terminal_id="00000000013800138000",
                channel_no=1,
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

    async def test_stopping_an_already_ended_session_does_not_re_signal_the_provider(
        self,
    ) -> None:
        """Stale-permission fix, focused D5 review 2026-08-13: a session already `ENDED` must
        short-circuit before any `VideoProviderPort.stop` call - repeated `stop_video_session`
        calls for the same session (a client retry, or the revoke-driven cleanup racing an
        already-completed stop) must never re-signal the relay/device a second time."""
        provider = FakeVideoProvider()
        service = make_service(provider=provider)
        uow = make_uow()
        session = await service.request_live_video(
            RequestLiveVideoCommand(
                organization_id=VALID_ORG_ULID,
                device_id="device-ref-idempotent",
                camera_id="camera-ref-idempotent",
                terminal_id="00000000013800138000",
                channel_no=1,
                actor=make_actor(),
            ),
            uow=uow,
        )

        first = await service.stop_video_session(
            StopVideoSessionCommand(video_session_id=session.id, actor=make_actor()), uow=uow
        )
        second = await service.stop_video_session(
            StopVideoSessionCommand(video_session_id=session.id, actor=make_actor()), uow=uow
        )

        self.assertEqual(first.status, "ended")
        self.assertEqual(second.status, "ended")
        self.assertEqual(len(provider.stop_calls), 1)


class GetVideoSessionByIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_not_found_raises(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.get_video_session_by_id(
                GetVideoSessionByIdQuery(video_session_id=NON_EXISTENT_ID), uow=uow
            )


class ListActiveSessionsForRequesterTests(unittest.IsolatedAsyncioTestCase):
    """`VideoApplicationService.list_active_sessions_for_requester` (stale-permission fix,
    focused D5 review 2026-08-13) — the read side `events/subscribers.
    ParentVideoLiveAccessRevokedProcessor`/`ParentVideoPlaybackAccessRevokedProcessor` use to
    find what to stop. Sessions are constructed directly via the domain factories, bypassing
    `request_live_video`'s own `NotImplementedError`-when-unbound behavior — irrelevant here."""

    def _live_session(self, *, requested_by: str, suffix: str) -> VideoSession:
        return VideoSession.request_live(
            id=VideoSessionId(f"01J8Z3K9G6X8YV5T4N2R{suffix:0>6}"),
            organization_id=OrganizationId(VALID_ORG_ULID),
            device_id=DeviceId(f"device-{suffix}"),
            camera_id=CameraId(f"camera-{suffix}"),
            requested_by=UserId(requested_by),
            clock=CLOCK,
        )

    def _playback_session(self, *, requested_by: str, suffix: str) -> VideoSession:
        start = datetime(2026, 7, 20, 9, 0, 0)
        return VideoSession.request_playback(
            id=VideoSessionId(f"01J8Z3K9G6X8YV5T4N2R{suffix:0>6}"),
            organization_id=OrganizationId(VALID_ORG_ULID),
            device_id=DeviceId(f"device-{suffix}"),
            camera_id=CameraId(f"camera-{suffix}"),
            requested_by=UserId(requested_by),
            window_start=start,
            window_end=start + timedelta(minutes=15),
            clock=CLOCK,
        )

    async def test_returns_only_open_sessions_for_the_matching_requester_and_purpose(
        self,
    ) -> None:
        service = make_service()
        uow = make_uow()

        mine_live = self._live_session(requested_by="parent-user-1", suffix="100001")
        mine_playback = self._playback_session(requested_by="parent-user-1", suffix="100002")
        someone_elses_live = self._live_session(requested_by="parent-user-2", suffix="100003")
        uow.video_sessions.add(mine_live)
        uow.video_sessions.add(mine_playback)
        uow.video_sessions.add(someone_elses_live)

        live_results = await service.list_active_sessions_for_requester(
            requested_by_user_id="parent-user-1", purpose="live", uow=uow
        )
        playback_results = await service.list_active_sessions_for_requester(
            requested_by_user_id="parent-user-1", purpose="playback", uow=uow
        )

        self.assertEqual([s.id for s in live_results], [mine_live.id.value])
        self.assertEqual([s.id for s in playback_results], [mine_playback.id.value])

    async def test_excludes_ended_and_failed_sessions(self) -> None:
        service = make_service()
        uow = make_uow()

        ended = self._live_session(requested_by="parent-user-1", suffix="100004")
        ended.activate(clock=CLOCK)
        ended.end(clock=CLOCK)
        failed = self._live_session(requested_by="parent-user-1", suffix="100005")
        failed.fail(clock=CLOCK)
        still_open = self._live_session(requested_by="parent-user-1", suffix="100006")
        uow.video_sessions.add(ended)
        uow.video_sessions.add(failed)
        uow.video_sessions.add(still_open)

        results = await service.list_active_sessions_for_requester(
            requested_by_user_id="parent-user-1", purpose="live", uow=uow
        )

        self.assertEqual([s.id for s in results], [still_open.id.value])

    async def test_handles_multiple_open_sessions_for_the_same_requester(self) -> None:
        service = make_service()
        uow = make_uow()

        first = self._live_session(requested_by="parent-user-1", suffix="100007")
        second = self._live_session(requested_by="parent-user-1", suffix="100008")
        uow.video_sessions.add(first)
        uow.video_sessions.add(second)

        results = await service.list_active_sessions_for_requester(
            requested_by_user_id="parent-user-1", purpose="live", uow=uow
        )

        self.assertEqual({s.id for s in results}, {first.id.value, second.id.value})

    async def test_no_matching_sessions_returns_empty_list(self) -> None:
        service = make_service()
        uow = make_uow()

        results = await service.list_active_sessions_for_requester(
            requested_by_user_id="parent-user-1", purpose="live", uow=uow
        )

        self.assertEqual(results, [])


class MarkSessionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0026 §7 - `mark_session_active`/`mark_session_ended`/`mark_session_failed`, the
    application-layer entry points `events/subscribers.py`'s processors call. No HTTP route
    calls these directly - only a broker-driven `SYSTEM_PRINCIPAL` actor."""

    async def _requested_session_id(self, service: VideoApplicationService, uow) -> str:
        with self.assertRaises(NotImplementedError):
            await service.request_live_video(
                RequestLiveVideoCommand(
                    organization_id=VALID_ORG_ULID,
                    device_id="device-ref-7",
                    camera_id="camera-ref-7",
                    terminal_id="00000000013800138000",
                    channel_no=1,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        return next(iter(uow.video_sessions.by_id.values())).id.value

    async def test_mark_session_active_transitions_status(self) -> None:
        service = make_service()
        uow = make_uow()
        session_id = await self._requested_session_id(service, uow)

        await service.mark_session_active(
            MarkVideoSessionActiveCommand(video_session_id=session_id, actor=SYSTEM_ACTOR),
            uow=uow,
        )
        self.assertEqual(uow.video_sessions.by_id[session_id].status.value, "active")

    async def test_mark_session_active_for_unknown_session_is_a_no_op_not_an_error(
        self,
    ) -> None:
        service = make_service()
        uow = make_uow()
        await service.mark_session_active(
            MarkVideoSessionActiveCommand(
                video_session_id=NON_EXISTENT_ID, actor=SYSTEM_ACTOR
            ),
            uow=uow,
        )  # must not raise
        self.assertEqual(uow.commit_count, 0)

    async def test_mark_session_ended_transitions_status_and_carries_reason(self) -> None:
        service = make_service()
        uow = make_uow()
        session_id = await self._requested_session_id(service, uow)

        await service.mark_session_ended(
            MarkVideoSessionEndedCommand(
                video_session_id=session_id,
                reason="viewer_idle_timeout",
                actor=SYSTEM_ACTOR,
            ),
            uow=uow,
        )
        self.assertEqual(uow.video_sessions.by_id[session_id].status.value, "ended")
        self.assertEqual(uow.recorded_events[-1].payload["reason"], "viewer_idle_timeout")

    async def test_mark_session_failed_transitions_status_and_carries_reason(self) -> None:
        service = make_service()
        uow = make_uow()
        session_id = await self._requested_session_id(service, uow)

        await service.mark_session_failed(
            MarkVideoSessionFailedCommand(
                video_session_id=session_id, reason="ingest_timeout", actor=SYSTEM_ACTOR
            ),
            uow=uow,
        )
        self.assertEqual(uow.video_sessions.by_id[session_id].status.value, "failed")
        self.assertEqual(uow.recorded_events[-1].payload["reason"], "ingest_timeout")

    async def test_mark_session_ended_for_unknown_session_is_a_no_op_not_an_error(self) -> None:
        service = make_service()
        uow = make_uow()
        await service.mark_session_ended(
            MarkVideoSessionEndedCommand(
                video_session_id=NON_EXISTENT_ID, reason=None, actor=SYSTEM_ACTOR
            ),
            uow=uow,
        )
        self.assertEqual(uow.commit_count, 0)

    async def test_mark_session_active_is_idempotent_no_double_event(self) -> None:
        """Mirrors `VideoSession.activate`'s own domain-level idempotency - a duplicate relay
        event (at-least-once delivery, LLD §10.3) must not re-fire the transition."""
        service = make_service()
        uow = make_uow()
        session_id = await self._requested_session_id(service, uow)

        await service.mark_session_active(
            MarkVideoSessionActiveCommand(video_session_id=session_id, actor=SYSTEM_ACTOR),
            uow=uow,
        )
        uow.recorded_events.clear()
        await service.mark_session_active(
            MarkVideoSessionActiveCommand(video_session_id=session_id, actor=SYSTEM_ACTOR),
            uow=uow,
        )
        self.assertEqual(uow.recorded_events, [])


if __name__ == "__main__":
    unittest.main()
