"""Unit tests for ADR-0044 (MDVR recording playback): `VideoApplicationService.
search_recordings`/`get_recording_search`/`control_playback`, the Redis-backed
`RecordingSearchResultPort`, and the `RecordingSearchResultProcessor` that closes the loop
between them. Stdlib `unittest` — no `pytest` (not an approved dependency), mirroring
`test_video_application.py`'s exact structure and reusing its fakes.

The property these tests exist to protect is ADR-0044 §1: **RAAD never stores video.** Nothing
here transfers a media byte — a search asks the terminal what it holds, and a control steers
what the terminal is already sending. The tests therefore assert on *what reaches the device*
and *what the caller is allowed to read back*, never on stored media.

`FakeRedis` mirrors `test_tracking_redis_latest_position.py`'s own precedent (only the methods
the adapter actually calls), since `RedisRecordingSearchResultPort` is the production
implementation and its JSON round trip is exactly where a field-name typo would hide.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.di.container import Container
from raad.core.errors.exceptions import ConflictError, NotFoundError
from raad.core.tenancy.principal import Principal, Role
from raad.core.events.base import DomainEvent
from raad.modules.video.application.commands import (
    ControlPlaybackCommand,
    RequestPlaybackVideoCommand,
    SearchRecordingsCommand,
)
from raad.modules.video.application.ports import (
    RecordingSearchResult,
    RecordingSearchResultPort,
    RecordingSegment,
)
from raad.modules.video.application.queries import GetRecordingSearchQuery
from raad.modules.video.application.services import VideoApplicationService
from raad.modules.video.events.subscribers import RecordingSearchResultProcessor
from raad.modules.video.infra.recording_search import RedisRecordingSearchResultPort

from tests.unit.test_video_application import (
    CLOCK,
    VALID_ORG_ULID,
    FakeVideoProvider,
    SequentialIdGenerator,
    make_actor,
    make_uow,
)

OTHER_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3XY"
TERMINAL_ID = "00000000013800138000"
WINDOW_START = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc)


class InMemoryRecordingSearchResultPort(RecordingSearchResultPort):
    """Deliberately models the real port's own "a result for an unknown search is dropped"
    rule, so a test that relies on it is testing the contract rather than this fake."""

    def __init__(self) -> None:
        self.results: dict[str, RecordingSearchResult] = {}

    async def remember_request(
        self, *, search_id: str, organization_id: str, device_id: str
    ) -> None:
        self.results[search_id] = RecordingSearchResult(
            search_id=search_id,
            organization_id=organization_id,
            device_id=device_id,
            segments=None,
        )

    async def save_segments(
        self, *, search_id: str, segments: tuple[RecordingSegment, ...]
    ) -> None:
        existing = self.results.get(search_id)
        if existing is None:
            return
        self.results[search_id] = RecordingSearchResult(
            search_id=existing.search_id,
            organization_id=existing.organization_id,
            device_id=existing.device_id,
            segments=segments,
        )

    async def get(self, search_id: str) -> RecordingSearchResult | None:
        return self.results.get(search_id)


def make_service(
    provider: FakeVideoProvider | None = None,
    search_results: RecordingSearchResultPort | None = None,
) -> VideoApplicationService:
    return VideoApplicationService(
        clock=CLOCK,
        id_generator=SequentialIdGenerator(),
        video_provider=provider,
        recording_search_results=search_results,
    )


def make_segment(channel_no: int = 1) -> RecordingSegment:
    return RecordingSegment(
        channel_no=channel_no,
        start_time=WINDOW_START,
        end_time=WINDOW_END,
        alarm_flag=0,
        resource_type=0,
        stream_type=0,
        storage_type=1,
        size_bytes=12_345,
    )


def make_search_command(organization_id: str = VALID_ORG_ULID) -> SearchRecordingsCommand:
    return SearchRecordingsCommand(
        organization_id=organization_id,
        device_id="device-ref-1",
        terminal_id=TERMINAL_ID,
        channel_no=1,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        actor=make_actor(),
    )


class SearchRecordingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_asks_the_device_and_returns_a_pending_search(self) -> None:
        provider = FakeVideoProvider()
        port = InMemoryRecordingSearchResultPort()
        service = make_service(provider, port)

        result = await service.search_recordings(make_search_command())

        self.assertEqual(result.status, "pending")
        self.assertIsNone(result.segments)
        self.assertEqual(len(provider.search_recordings_calls), 1)
        call = provider.search_recordings_calls[0]
        self.assertEqual(call["terminal_id"], TERMINAL_ID)
        self.assertEqual(call["channel_no"], 1)
        self.assertEqual(call["window_start"], WINDOW_START)
        self.assertEqual(call["window_end"], WINDOW_END)
        # The correlation id the device echoes back IS the search id - this equality is what
        # lets `RecordingSearchResultProcessor` find the right search later.
        self.assertEqual(call["reference"], result.search_id)

    async def test_remembers_the_request_before_asking_the_device(self) -> None:
        """A `GET` arriving before the terminal answers must report `pending`, never 404 -
        which only holds if the request is remembered ahead of the device call."""
        provider = FakeVideoProvider()
        port = InMemoryRecordingSearchResultPort()
        service = make_service(provider, port)

        result = await service.search_recordings(make_search_command())

        stored = await port.get(result.search_id)
        self.assertIsNotNone(stored)
        self.assertIsNone(stored.segments)
        self.assertEqual(stored.organization_id, VALID_ORG_ULID)

    async def test_creates_no_video_session(self) -> None:
        """ADR-0044 §2: a search starts no media, so it must not consume a session ceiling."""
        provider = FakeVideoProvider()
        service = make_service(provider, InMemoryRecordingSearchResultPort())
        uow = make_uow()

        await service.search_recordings(make_search_command())

        self.assertEqual(len(uow.video_sessions.by_id), 0)
        self.assertEqual(provider.start_playback_calls, [])

    async def test_without_a_bound_search_port_fails_loudly(self) -> None:
        service = make_service(FakeVideoProvider(), search_results=None)

        with self.assertRaises(NotImplementedError):
            await service.search_recordings(make_search_command())

    async def test_without_a_bound_provider_fails_loudly(self) -> None:
        service = make_service(None, InMemoryRecordingSearchResultPort())

        with self.assertRaises(NotImplementedError):
            await service.search_recordings(make_search_command())


class GetRecordingSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_until_the_device_answers(self) -> None:
        port = InMemoryRecordingSearchResultPort()
        service = make_service(FakeVideoProvider(), port)
        created = await service.search_recordings(make_search_command())

        result = await service.get_recording_search(
            GetRecordingSearchQuery(search_id=created.search_id),
            organization_id=VALID_ORG_ULID,
        )

        self.assertEqual(result.status, "pending")
        self.assertIsNone(result.segments)

    async def test_ready_once_the_device_has_answered(self) -> None:
        port = InMemoryRecordingSearchResultPort()
        service = make_service(FakeVideoProvider(), port)
        created = await service.search_recordings(make_search_command())
        await port.save_segments(
            search_id=created.search_id, segments=(make_segment(1), make_segment(3))
        )

        result = await service.get_recording_search(
            GetRecordingSearchQuery(search_id=created.search_id),
            organization_id=VALID_ORG_ULID,
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(len(result.segments), 2)
        self.assertEqual([s.channel_no for s in result.segments], [1, 3])
        self.assertEqual(result.segments[0].size_bytes, 12_345)

    async def test_an_empty_answer_is_ready_not_pending(self) -> None:
        """"The device holds nothing for that window" is a real answer; conflating it with
        "still waiting" would leave an operator polling forever."""
        port = InMemoryRecordingSearchResultPort()
        service = make_service(FakeVideoProvider(), port)
        created = await service.search_recordings(make_search_command())
        await port.save_segments(search_id=created.search_id, segments=())

        result = await service.get_recording_search(
            GetRecordingSearchQuery(search_id=created.search_id),
            organization_id=VALID_ORG_ULID,
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.segments, ())

    async def test_unknown_search_is_not_found(self) -> None:
        service = make_service(FakeVideoProvider(), InMemoryRecordingSearchResultPort())

        with self.assertRaises(NotFoundError):
            await service.get_recording_search(
                GetRecordingSearchQuery(search_id="no-such-search"),
                organization_id=VALID_ORG_ULID,
            )

    async def test_another_organizations_search_is_not_found_never_forbidden(self) -> None:
        """ADR-0044 §3: a `search_id` is not a capability. A cross-tenant read answers exactly
        like an unknown id, so an id can never confirm another organization's search exists."""
        port = InMemoryRecordingSearchResultPort()
        service = make_service(FakeVideoProvider(), port)
        created = await service.search_recordings(make_search_command())

        with self.assertRaises(NotFoundError):
            await service.get_recording_search(
                GetRecordingSearchQuery(search_id=created.search_id),
                organization_id=OTHER_ORG_ULID,
            )

    async def test_raad_staff_with_no_single_organization_may_read(self) -> None:
        """`principal.org_id` is `None` for every RAAD-staff role by design; their region/
        support scope is enforced by the route's own device re-resolution, not here."""
        port = InMemoryRecordingSearchResultPort()
        service = make_service(FakeVideoProvider(), port)
        created = await service.search_recordings(make_search_command())

        result = await service.get_recording_search(
            GetRecordingSearchQuery(search_id=created.search_id), organization_id=None
        )

        self.assertEqual(result.search_id, created.search_id)


class ControlPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def _make_playback_session(
        self, service: VideoApplicationService, uow
    ) -> str:
        session = await service.request_playback_video(
            RequestPlaybackVideoCommand(
                organization_id=VALID_ORG_ULID,
                device_id="device-ref-1",
                camera_id="camera-ref-1",
                terminal_id=TERMINAL_ID,
                channel_no=1,
                window_start=WINDOW_START,
                window_end=WINDOW_END,
                actor=make_actor(),
            ),
            uow=uow,
        )
        return session.id

    def _command(self, session_id: str, **overrides) -> ControlPlaybackCommand:
        kwargs = {
            "video_session_id": session_id,
            "terminal_id": TERMINAL_ID,
            "channel_no": 1,
            "control": 1,  # pause
            "actor": make_actor(),
        }
        kwargs.update(overrides)
        return ControlPlaybackCommand(**kwargs)

    async def test_forwards_the_control_to_the_device(self) -> None:
        provider = FakeVideoProvider()
        service = make_service(provider, InMemoryRecordingSearchResultPort())
        uow = make_uow()
        session_id = await self._make_playback_session(service, uow)

        await service.control_playback(self._command(session_id), uow=uow)

        self.assertEqual(len(provider.control_playback_calls), 1)
        call = provider.control_playback_calls[0]
        self.assertEqual(call["terminal_id"], TERMINAL_ID)
        self.assertEqual(call["channel_no"], 1)
        self.assertEqual(call["control"], 1)
        self.assertEqual(call["reference"], session_id)

    async def test_another_user_cannot_control_someone_elses_playback(self) -> None:
        """Audit 2026-09-26: only the session's requester controls it; others get a 404."""
        provider = FakeVideoProvider()
        service = make_service(provider, InMemoryRecordingSearchResultPort())
        uow = make_uow()
        session_id = await self._make_playback_session(service, uow)
        colleague = Principal(user_id="admin-2", role=Role.ORG_ADMIN, org_id=VALID_ORG_ULID)

        with self.assertRaises(NotFoundError):
            await service.control_playback(self._command(session_id, actor=colleague), uow=uow)
        self.assertEqual(provider.control_playback_calls, [])

    async def test_forwards_speed_and_seek_position(self) -> None:
        provider = FakeVideoProvider()
        service = make_service(provider, InMemoryRecordingSearchResultPort())
        uow = make_uow()
        session_id = await self._make_playback_session(service, uow)

        await service.control_playback(
            self._command(session_id, control=5, position=WINDOW_START), uow=uow
        )
        await service.control_playback(
            self._command(session_id, control=3, speed_multiplier=4), uow=uow
        )

        self.assertEqual(provider.control_playback_calls[0]["position"], WINDOW_START)
        self.assertEqual(provider.control_playback_calls[1]["speed_multiplier"], 4)

    async def test_refuses_a_live_session(self) -> None:
        """A playback control reaching a live session would steer a stream this session does
        not own - refused before anything is sent to the device."""
        provider = FakeVideoProvider()
        service = make_service(provider, InMemoryRecordingSearchResultPort())
        uow = make_uow()
        from raad.modules.video.application.commands import RequestLiveVideoCommand

        live = await service.request_live_video(
            RequestLiveVideoCommand(
                organization_id=VALID_ORG_ULID,
                device_id="device-ref-1",
                camera_id="camera-ref-1",
                terminal_id=TERMINAL_ID,
                channel_no=1,
                actor=make_actor(),
            ),
            uow=uow,
        )

        with self.assertRaises(ConflictError):
            await service.control_playback(self._command(live.id), uow=uow)
        self.assertEqual(provider.control_playback_calls, [])

    async def test_refuses_an_already_ended_session(self) -> None:
        from raad.modules.video.application.commands import StopVideoSessionCommand

        provider = FakeVideoProvider()
        service = make_service(provider, InMemoryRecordingSearchResultPort())
        uow = make_uow()
        session_id = await self._make_playback_session(service, uow)
        await service.stop_video_session(
            StopVideoSessionCommand(video_session_id=session_id, actor=make_actor()), uow=uow
        )

        with self.assertRaises(ConflictError):
            await service.control_playback(self._command(session_id), uow=uow)
        self.assertEqual(provider.control_playback_calls, [])

    async def test_unknown_session_is_not_found(self) -> None:
        service = make_service(FakeVideoProvider(), InMemoryRecordingSearchResultPort())
        uow = make_uow()

        with self.assertRaises(NotFoundError):
            await service.control_playback(
                self._command("01J8Z3K9G6X8YV5T4N2R7QW3ZZ"), uow=uow
            )


class FakeRedis:
    """Only the two methods the adapter calls, mirroring
    `test_tracking_redis_latest_position.FakeRedis`."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        self.expirations[key] = ex


class RedisRecordingSearchResultPortTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_trips_every_segment_field(self) -> None:
        redis = FakeRedis()
        port = RedisRecordingSearchResultPort(redis)
        await port.remember_request(
            search_id="search-1", organization_id=VALID_ORG_ULID, device_id="device-ref-1"
        )
        await port.save_segments(search_id="search-1", segments=(make_segment(3),))

        result = await port.get("search-1")

        self.assertEqual(result.organization_id, VALID_ORG_ULID)
        self.assertEqual(result.device_id, "device-ref-1")
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(result.segments[0], make_segment(3))

    async def test_keys_are_namespaced_and_expire(self) -> None:
        """The TTL is the mechanism that keeps RAAD from holding a stale copy of the device's
        archive index (ADR-0044 §2) - an unexpiring key would quietly become one."""
        redis = FakeRedis()
        port = RedisRecordingSearchResultPort(redis, ttl_seconds=60)

        await port.remember_request(
            search_id="search-1", organization_id=VALID_ORG_ULID, device_id="device-ref-1"
        )

        self.assertIn("video:recording_search:search-1", redis.values)
        self.assertEqual(redis.expirations["video:recording_search:search-1"], 60)

    async def test_pending_is_distinct_from_an_empty_answer(self) -> None:
        redis = FakeRedis()
        port = RedisRecordingSearchResultPort(redis)
        await port.remember_request(
            search_id="search-1", organization_id=VALID_ORG_ULID, device_id="device-ref-1"
        )

        self.assertIsNone((await port.get("search-1")).segments)

        await port.save_segments(search_id="search-1", segments=())

        self.assertEqual((await port.get("search-1")).segments, ())

    async def test_a_result_for_an_unknown_search_is_dropped(self) -> None:
        """No remembered request means no organization to scope the result by - storing it
        would create unscoped data."""
        redis = FakeRedis()
        port = RedisRecordingSearchResultPort(redis)

        await port.save_segments(search_id="never-asked", segments=(make_segment(),))

        self.assertIsNone(await port.get("never-asked"))

    async def test_unknown_search_reads_as_none(self) -> None:
        self.assertIsNone(await RedisRecordingSearchResultPort(FakeRedis()).get("nope"))


def make_container(port: RecordingSearchResultPort | None) -> Container:
    """A real `Container` with only this one binding — no full composition root needed, and
    `try_resolve`'s own "unbound -> None" behavior is the real one rather than a fake's."""
    container = Container()
    if port is not None:
        container.bind_singleton(RecordingSearchResultPort, port)
    return container


def make_resource_list_event(correlation_id: str | None, items: list[dict]) -> DomainEvent:
    """The wire shape `device-gateway`'s own `DeviceResourceListReported` publisher emits
    (`services/device-gateway/src/events/redis_event_publisher.py`'s `_fields_for`)."""
    payload = {
        "terminal_id": TERMINAL_ID,
        "organization_id": VALID_ORG_ULID,
        "device_id": "device-ref-1",
        "total_resource_count": len(items),
        "items": items,
    }
    if correlation_id is not None:
        payload["correlation_id"] = correlation_id
    return DomainEvent(
        event_id="evt-1",
        event_type="DeviceResourceListReported",
        version=1,
        occurred_at=CLOCK.now(),
        org_id=VALID_ORG_ULID,
        correlation_id=correlation_id,
        payload=payload,
        aggregate_type="Device",
        aggregate_id=TERMINAL_ID,
    )


RAW_ITEM = {
    "logical_channel": 3,
    "start_time": WINDOW_START.isoformat(),
    "end_time": WINDOW_END.isoformat(),
    "alarm_flag": 0,
    "resource_type": 0,
    "stream_type": 0,
    "storage_type": 1,
    "file_size_bytes": 12_345,
}


class RecordingSearchResultProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_the_devices_answer_under_the_search_id(self) -> None:
        port = InMemoryRecordingSearchResultPort()
        await port.remember_request(
            search_id="search-1", organization_id=VALID_ORG_ULID, device_id="device-ref-1"
        )
        processor = RecordingSearchResultProcessor(make_container(port))

        await processor.process(make_resource_list_event("search-1", [RAW_ITEM]))

        stored = await port.get("search-1")
        self.assertEqual(stored.segments, (make_segment(3),))

    async def test_maps_file_size_bytes_onto_size_bytes(self) -> None:
        """The gateway's own field name differs from the domain's - a silent mismatch here
        would show every recording as 0 bytes."""
        port = InMemoryRecordingSearchResultPort()
        await port.remember_request(
            search_id="search-1", organization_id=VALID_ORG_ULID, device_id="device-ref-1"
        )
        processor = RecordingSearchResultProcessor(make_container(port))

        await processor.process(make_resource_list_event("search-1", [RAW_ITEM]))

        self.assertEqual((await port.get("search-1")).segments[0].size_bytes, 12_345)

    async def test_an_empty_report_is_a_real_ready_answer(self) -> None:
        port = InMemoryRecordingSearchResultPort()
        await port.remember_request(
            search_id="search-1", organization_id=VALID_ORG_ULID, device_id="device-ref-1"
        )
        processor = RecordingSearchResultProcessor(make_container(port))

        await processor.process(make_resource_list_event("search-1", []))

        self.assertEqual((await port.get("search-1")).segments, ())

    async def test_missing_correlation_id_is_a_no_op(self) -> None:
        port = InMemoryRecordingSearchResultPort()
        processor = RecordingSearchResultProcessor(make_container(port))

        await processor.process(make_resource_list_event(None, [RAW_ITEM]))

        self.assertEqual(port.results, {})

    async def test_no_bound_port_is_a_no_op_not_a_crash(self) -> None:
        """A deployment with no Redis must not wedge the shared event consumer every other
        processor runs on."""
        processor = RecordingSearchResultProcessor(make_container(None))

        await processor.process(make_resource_list_event("search-1", [RAW_ITEM]))

    async def test_event_type_matches_the_gateways_own(self) -> None:
        self.assertEqual(
            RecordingSearchResultProcessor.event_type, "DeviceResourceListReported"
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
