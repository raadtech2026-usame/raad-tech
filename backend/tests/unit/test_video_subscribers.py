"""Unit tests for `modules.video.events.subscribers` (ADR-0026 §7, plus the stale-permission fix
from the focused D5 review, 2026-08-13). Stdlib `unittest` - no `pytest`. Mirrors
`test_fleet_device_subscribers.py`'s exact convention: fakes bound directly into a real
`core.di.container.Container`, keyed by the real types each processor resolves.

Covers: each of `VideoSessionActivated`/`Ended`/`Failed` dispatches to the matching
`VideoApplicationService.mark_session_*` command with `SYSTEM_PRINCIPAL` as actor, `reason` is
threaded through for `Ended`/`Failed`, and a missing/`None` `session_id` in the payload is
dropped, not passed through as `None`. `ParentVideoLiveAccessRevokedProcessor`/
`ParentVideoPlaybackAccessRevokedProcessor` are exercised against the *real*
`VideoApplicationService` (not a recording fake) composed with an in-memory `VideoUnitOfWork` and
a fake `VideoProviderPort` — the thing actually worth proving here is the end-to-end wiring
(event -> resolve parent's `user_id` -> find open sessions -> reuse `stop_video_session`), not
just that some command gets called.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from raad.core.di.container import Container
from raad.core.errors.exceptions import NotFoundError
from raad.core.events.base import DomainEvent
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.services import ParentApplicationService
from raad.modules.video.application.commands import (
    MarkVideoSessionActiveCommand,
    MarkVideoSessionEndedCommand,
    MarkVideoSessionFailedCommand,
    RequestLiveVideoCommand,
    RequestPlaybackVideoCommand,
)
from raad.modules.video.application.ports import (
    IntercomStreamUrls,
    VideoProviderPort,
    VideoUnitOfWork,
)
from raad.modules.video.application.services import VideoApplicationService
from raad.modules.video.domain.entities import VideoSession
from raad.modules.video.domain.repositories import VideoSessionRepository
from raad.modules.video.domain.value_objects import VideoSessionId
from raad.modules.video.events.subscribers import (
    SYSTEM_PRINCIPAL,
    ParentVideoLiveAccessRevokedProcessor,
    ParentVideoPlaybackAccessRevokedProcessor,
    VideoSessionActivatedProcessor,
    VideoSessionEndedProcessor,
    VideoSessionFailedProcessor,
    register_video_processors,
)
from raad.core.events.processor import EventProcessorRegistry

_OCCURRED_AT = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
_VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"


class _FakeUnitOfWork:
    """`Container.resolve` is a plain type-keyed lookup with no `isinstance` enforcement - the
    fake service below never actually uses `uow`."""


class _RecordingVideoApplicationService:
    def __init__(self) -> None:
        self.activated: list[MarkVideoSessionActiveCommand] = []
        self.ended: list[MarkVideoSessionEndedCommand] = []
        self.failed: list[MarkVideoSessionFailedCommand] = []

    async def mark_session_active(self, command: MarkVideoSessionActiveCommand, *, uow) -> None:
        self.activated.append(command)

    async def mark_session_ended(self, command: MarkVideoSessionEndedCommand, *, uow) -> None:
        self.ended.append(command)

    async def mark_session_failed(self, command: MarkVideoSessionFailedCommand, *, uow) -> None:
        self.failed.append(command)


def _make_event(*, event_type: str, payload: dict) -> DomainEvent:
    return DomainEvent(
        event_id="evt-1",
        event_type=event_type,
        version=1,
        occurred_at=_OCCURRED_AT,
        org_id=payload.get("organization_id"),
        correlation_id=payload.get("correlation_id"),
        payload=payload,
        aggregate_type="VideoSession",
        aggregate_id=payload.get("session_id") or "",
    )


def _make_parent_revoke_event(*, event_type: str, parent_id: str | None) -> DomainEvent:
    """Mirrors `transport_ops_events.parent_video_live_access_revoked`/`..._playback_...`'s own
    real shape exactly: `parent_id` lives in `aggregate_id`, never in `payload` (`payload`
    carries only `actor_id`, per that module's own event factories)."""
    return DomainEvent(
        event_id="evt-1",
        event_type=event_type,
        version=1,
        occurred_at=_OCCURRED_AT,
        org_id=_VALID_ORG_ULID,
        correlation_id=None,
        payload={"actor_id": "admin-1"},
        aggregate_type="Parent",
        aggregate_id=parent_id,
    )


class VideoSessionProcessorsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.container = Container()
        self.service = _RecordingVideoApplicationService()
        self.container.bind_singleton(VideoApplicationService, self.service)
        self.container.bind_singleton(VideoUnitOfWork, _FakeUnitOfWork())

    async def test_activated_dispatches_with_system_principal(self) -> None:
        processor = VideoSessionActivatedProcessor(self.container)
        event = _make_event(
            event_type="VideoSessionActivated",
            payload={"session_id": "vs-1", "terminal_id": "00007"},
        )

        await processor.process(event)

        self.assertEqual(len(self.service.activated), 1)
        command = self.service.activated[0]
        self.assertEqual(command.video_session_id, "vs-1")
        self.assertIs(command.actor, SYSTEM_PRINCIPAL)

    async def test_ended_dispatches_with_reason(self) -> None:
        processor = VideoSessionEndedProcessor(self.container)
        event = _make_event(
            event_type="VideoSessionEnded",
            payload={"session_id": "vs-1", "reason": "viewer_idle_timeout"},
        )

        await processor.process(event)

        self.assertEqual(len(self.service.ended), 1)
        command = self.service.ended[0]
        self.assertEqual(command.video_session_id, "vs-1")
        self.assertEqual(command.reason, "viewer_idle_timeout")
        self.assertIs(command.actor, SYSTEM_PRINCIPAL)

    async def test_failed_dispatches_with_reason(self) -> None:
        processor = VideoSessionFailedProcessor(self.container)
        event = _make_event(
            event_type="VideoSessionFailed",
            payload={"session_id": "vs-1", "reason": "ingest_timeout"},
        )

        await processor.process(event)

        self.assertEqual(len(self.service.failed), 1)
        self.assertEqual(self.service.failed[0].reason, "ingest_timeout")

    async def test_missing_session_id_is_dropped_not_passed_through(self) -> None:
        processor = VideoSessionActivatedProcessor(self.container)
        event = _make_event(event_type="VideoSessionActivated", payload={"session_id": None})

        await processor.process(event)

        self.assertEqual(self.service.activated, [])

    async def test_event_type_class_attributes(self) -> None:
        self.assertEqual(VideoSessionActivatedProcessor(self.container).event_type,
                          "VideoSessionActivated")
        self.assertEqual(VideoSessionEndedProcessor(self.container).event_type,
                          "VideoSessionEnded")
        self.assertEqual(VideoSessionFailedProcessor(self.container).event_type,
                          "VideoSessionFailed")


class RegisterVideoProcessorsTests(unittest.TestCase):
    def test_registers_all_three_event_types(self) -> None:
        registry = EventProcessorRegistry()
        container = Container()
        register_video_processors(registry, container)

        self.assertIsNotNone(registry.get("VideoSessionActivated"))
        self.assertIsNotNone(registry.get("VideoSessionEnded"))
        self.assertIsNotNone(registry.get("VideoSessionFailed"))

    def test_registers_both_parent_video_access_revoked_event_types(self) -> None:
        """Stale-permission fix, focused D5 review 2026-08-13."""
        registry = EventProcessorRegistry()
        container = Container()
        register_video_processors(registry, container)

        self.assertIsNotNone(registry.get("ParentVideoLiveAccessRevoked"))
        self.assertIsNotNone(registry.get("ParentVideoPlaybackAccessRevoked"))


# --- ParentVideoLiveAccessRevokedProcessor / ParentVideoPlaybackAccessRevokedProcessor ---------


@dataclass(frozen=True)
class _ParentDTO:
    id: str
    user_id: str


class FakeParentService:
    """Mirrors `test_policy_guards.py`'s own `FakeParentService` shape - `get_parent_by_id`
    never touches `uow`."""

    def __init__(self, parents_by_id: dict[str, _ParentDTO]) -> None:
        self._by_id = parents_by_id

    async def get_parent_by_id(self, query, *, uow):
        parent = self._by_id.get(query.parent_id)
        if parent is None:
            raise NotFoundError(f"Parent {query.parent_id} not found.")
        return parent


class _FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


_CLOCK = _FixedClock(_OCCURRED_AT)


class _SequentialIdGenerator(IdGenerator):
    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


class _InMemoryVideoSessionRepository(VideoSessionRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, VideoSession] = {}

    async def get(self, video_session_id: VideoSessionId) -> VideoSession | None:
        return self.by_id.get(str(video_session_id))

    def add(self, video_session: VideoSession) -> None:
        self.by_id[str(video_session.id)] = video_session

    async def list_all(self) -> list[VideoSession]:
        return list(self.by_id.values())


class _FakeVideoUnitOfWork(VideoUnitOfWork):
    def __init__(self, video_sessions: _InMemoryVideoSessionRepository) -> None:
        self.video_sessions = video_sessions

    def record_events(self, events) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class _FakeVideoProvider(VideoProviderPort):
    def __init__(self) -> None:
        self.stop_calls: list[str] = []

    async def start_live(self, **kwargs) -> str:
        return "https://stream.example/token"

    async def start_playback(self, **kwargs) -> str:
        return "https://stream.example/token"

    async def start_intercom(self, **kwargs) -> IntercomStreamUrls:
        return IntercomStreamUrls(
            downlink_url="https://stream.example/token",
            uplink_url="https://stream.example/token-uplink",
        )

    async def stop(self, *, reference: str) -> None:
        self.stop_calls.append(reference)


PARENT_1 = _ParentDTO(id="parent-1", user_id="parent-user-1")
PARENT_2 = _ParentDTO(id="parent-2", user_id="parent-user-2")


def _parent_actor(user_id: str) -> Principal:
    return Principal(user_id=user_id, role=Role.PARENT, org_id=_VALID_ORG_ULID)


class ParentVideoAccessRevokedProcessorTests(unittest.IsolatedAsyncioTestCase):
    """Stale-permission fix (focused D5 review, 2026-08-13): revoking `has_video_live_access`/
    `has_video_playback_access` must tear down any `REQUESTED`/`ACTIVE` session the parent
    still has open for that purpose, by reusing `VideoApplicationService.stop_video_session` -
    never a parallel stop mechanism."""

    def setUp(self) -> None:
        self.container = Container()
        self.container.bind_singleton(
            ParentApplicationService,
            FakeParentService({PARENT_1.id: PARENT_1, PARENT_2.id: PARENT_2}),
        )
        self.container.bind_singleton(TransportOpsUnitOfWork, _FakeUnitOfWork())

        self.provider = _FakeVideoProvider()
        self.repo = _InMemoryVideoSessionRepository()
        self.video_uow = _FakeVideoUnitOfWork(self.repo)
        self.video_service = VideoApplicationService(
            clock=_CLOCK, id_generator=_SequentialIdGenerator(), video_provider=self.provider
        )
        self.container.bind_singleton(VideoApplicationService, self.video_service)
        self.container.bind_singleton(VideoUnitOfWork, self.video_uow)

    async def _request_live(self, *, requested_by: str, device_id: str = "device-1") -> str:
        """Requests a live session as `requested_by` (a real `Principal`, so `VideoSession.
        requested_by` is set correctly by `VideoApplicationService.request_live_video` itself -
        no post-hoc mutation needed). Returns the new session's id."""
        session = await self.video_service.request_live_video(
            RequestLiveVideoCommand(
                organization_id=_VALID_ORG_ULID,
                device_id=device_id,
                camera_id="camera-1",
                terminal_id="00000000013800138000",
                channel_no=1,
                actor=_parent_actor(requested_by),
            ),
            uow=self.video_uow,
        )
        return session.id

    async def _request_playback(self, *, requested_by: str) -> str:
        start = datetime(2026, 7, 20, 9, 0, 0)
        session = await self.video_service.request_playback_video(
            RequestPlaybackVideoCommand(
                organization_id=_VALID_ORG_ULID,
                device_id="device-1",
                camera_id="camera-1",
                terminal_id="00000000013800138000",
                channel_no=1,
                window_start=start,
                window_end=start + timedelta(minutes=15),
                actor=_parent_actor(requested_by),
            ),
            uow=self.video_uow,
        )
        return session.id

    def _status(self, session_id: str) -> str:
        return self.repo.by_id[session_id].status.value

    async def test_live_revoke_stops_the_parents_open_live_session(self) -> None:
        session_id = await self._request_live(requested_by=PARENT_1.user_id)

        processor = ParentVideoLiveAccessRevokedProcessor(self.container)
        event = _make_parent_revoke_event(
            event_type="ParentVideoLiveAccessRevoked", parent_id=PARENT_1.id
        )
        await processor.process(event)

        self.assertEqual(self._status(session_id), "ended")
        self.assertEqual(self.provider.stop_calls, [session_id])

    async def test_playback_revoke_stops_the_parents_open_playback_session_only(self) -> None:
        live_session_id = await self._request_live(requested_by=PARENT_1.user_id)
        playback_session_id = await self._request_playback(requested_by=PARENT_1.user_id)

        processor = ParentVideoPlaybackAccessRevokedProcessor(self.container)
        event = _make_parent_revoke_event(
            event_type="ParentVideoPlaybackAccessRevoked", parent_id=PARENT_1.id
        )
        await processor.process(event)

        self.assertEqual(self._status(playback_session_id), "ended")
        # The live session, same parent, is untouched - live/playback stay independent.
        self.assertEqual(self._status(live_session_id), "requested")
        self.assertEqual(self.provider.stop_calls, [playback_session_id])

    async def test_handles_multiple_open_sessions_for_the_same_parent(self) -> None:
        first_id = await self._request_live(requested_by=PARENT_1.user_id, device_id="device-1")
        second_id = await self._request_live(requested_by=PARENT_1.user_id, device_id="device-2")

        processor = ParentVideoLiveAccessRevokedProcessor(self.container)
        event = _make_parent_revoke_event(
            event_type="ParentVideoLiveAccessRevoked", parent_id=PARENT_1.id
        )
        await processor.process(event)

        self.assertEqual(self._status(first_id), "ended")
        self.assertEqual(self._status(second_id), "ended")
        self.assertEqual(set(self.provider.stop_calls), {first_id, second_id})

    async def test_repeated_revoke_is_idempotent_no_duplicate_stop_signal(self) -> None:
        """At-least-once event delivery (LLD §10.3): processing the same revoke event twice
        must not re-signal the relay for a session the first processing already stopped."""
        session_id = await self._request_live(requested_by=PARENT_1.user_id)

        processor = ParentVideoLiveAccessRevokedProcessor(self.container)
        event = _make_parent_revoke_event(
            event_type="ParentVideoLiveAccessRevoked", parent_id=PARENT_1.id
        )
        await processor.process(event)
        await processor.process(event)  # redelivered

        self.assertEqual(self._status(session_id), "ended")
        self.assertEqual(self.provider.stop_calls, [session_id])

    async def test_a_different_parents_session_is_not_touched(self) -> None:
        other_parents_session_id = await self._request_live(requested_by=PARENT_2.user_id)

        processor = ParentVideoLiveAccessRevokedProcessor(self.container)
        event = _make_parent_revoke_event(
            event_type="ParentVideoLiveAccessRevoked", parent_id=PARENT_1.id
        )
        await processor.process(event)

        self.assertEqual(self._status(other_parents_session_id), "requested")
        self.assertEqual(self.provider.stop_calls, [])

    async def test_missing_parent_id_is_a_no_op_not_an_error(self) -> None:
        processor = ParentVideoLiveAccessRevokedProcessor(self.container)
        event = _make_parent_revoke_event(
            event_type="ParentVideoLiveAccessRevoked", parent_id=None
        )
        await processor.process(event)  # must not raise
        self.assertEqual(self.provider.stop_calls, [])

    async def test_unknown_parent_id_is_a_no_op_not_an_error(self) -> None:
        """The `Parent` row is gone by the time this event is processed - a real, expected
        race, mirrors every relay-event processor's own "no row -> no-op" contract."""
        processor = ParentVideoLiveAccessRevokedProcessor(self.container)
        event = _make_parent_revoke_event(
            event_type="ParentVideoLiveAccessRevoked", parent_id="no-such-parent"
        )
        await processor.process(event)  # must not raise
        self.assertEqual(self.provider.stop_calls, [])

    async def test_event_type_class_attributes(self) -> None:
        self.assertEqual(
            ParentVideoLiveAccessRevokedProcessor(self.container).event_type,
            "ParentVideoLiveAccessRevoked",
        )
        self.assertEqual(
            ParentVideoPlaybackAccessRevokedProcessor(self.container).event_type,
            "ParentVideoPlaybackAccessRevoked",
        )


if __name__ == "__main__":
    unittest.main()
