"""Domain-only tests for `video`'s single `VideoSession` aggregate (Backend Stabilization
phase). Stdlib `unittest` — no `pytest` (not an approved dependency), mirroring
`test_billing_domain.py`'s established precedent.

Covers: value-object validation (ULID `VideoSessionId`, opaque cross-module ids), construction
(including the playback window invariant), `request_live`/`request_playback` factories,
`activate`/`end`/`fail` transitions (idempotent same-state no-ops, per `entities.py`'s "no
guarded state machine" documented precedent), domain-event emission, and repository-interface
shape.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.video.domain.entities import VideoSession
from raad.modules.video.domain.repositories import VideoSessionRepository
from raad.modules.video.domain.value_objects import (
    CameraId,
    DeviceId,
    OrganizationId,
    UserId,
    VideoPurpose,
    VideoSessionId,
    VideoSessionStatus,
)

VALID_SESSION_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3VS"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_DEVICE_REF = "some-opaque-device-ref"
VALID_CAMERA_REF = "some-opaque-camera-ref"
VALID_USER_REF = "some-opaque-user-ref"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 7, 21, 8, 0, 0, tzinfo=timezone.utc))


class UlidValueObjectValidationTests(unittest.TestCase):
    def test_video_session_id_valid_ulid_constructs(self) -> None:
        self.assertEqual(str(VideoSessionId(VALID_SESSION_ULID)), VALID_SESSION_ULID)

    def test_video_session_id_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            VideoSessionId("TOOSHORT")

    def test_video_session_id_lowercase_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            VideoSessionId(VALID_SESSION_ULID.lower())


class OpaqueCrossModuleValueObjectTests(unittest.TestCase):
    def test_organization_id_non_empty_constructs(self) -> None:
        self.assertEqual(str(OrganizationId(VALID_ORG_ULID)), VALID_ORG_ULID)

    def test_organization_id_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            OrganizationId("")

    def test_device_id_arbitrary_non_ulid_string_is_accepted(self) -> None:
        self.assertEqual(str(DeviceId(VALID_DEVICE_REF)), VALID_DEVICE_REF)

    def test_device_id_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            DeviceId("")

    def test_camera_id_arbitrary_non_ulid_string_is_accepted(self) -> None:
        self.assertEqual(str(CameraId(VALID_CAMERA_REF)), VALID_CAMERA_REF)

    def test_user_id_arbitrary_non_ulid_string_is_accepted(self) -> None:
        self.assertEqual(str(UserId(VALID_USER_REF)), VALID_USER_REF)

    def test_user_id_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            UserId("")


class RequestLiveTests(unittest.TestCase):
    def test_request_live_starts_requested_with_live_purpose(self) -> None:
        session = VideoSession.request_live(
            id=VideoSessionId(VALID_SESSION_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            device_id=DeviceId(VALID_DEVICE_REF),
            camera_id=CameraId(VALID_CAMERA_REF),
            requested_by=UserId(VALID_USER_REF),
            clock=CLOCK,
        )
        self.assertEqual(session.status, VideoSessionStatus.REQUESTED)
        self.assertEqual(session.purpose, VideoPurpose.LIVE)
        self.assertIsNone(session.window_start)
        self.assertIsNone(session.window_end)
        self.assertIsNone(session.started_at)

    def test_request_live_records_video_session_requested_event(self) -> None:
        session = VideoSession.request_live(
            id=VideoSessionId(VALID_SESSION_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            device_id=DeviceId(VALID_DEVICE_REF),
            camera_id=CameraId(VALID_CAMERA_REF),
            requested_by=UserId(VALID_USER_REF),
            clock=CLOCK,
        )
        events = session.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "VideoSessionRequested")
        self.assertEqual(events[0].aggregate_type, "VideoSession")
        self.assertEqual(events[0].payload["purpose"], "live")


class RequestPlaybackTests(unittest.TestCase):
    def test_request_playback_requires_window_end_after_window_start(self) -> None:
        start = datetime(2026, 7, 20, 10, 0, 0)
        with self.assertRaises(DomainError):
            VideoSession.request_playback(
                id=VideoSessionId(VALID_SESSION_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                device_id=DeviceId(VALID_DEVICE_REF),
                camera_id=CameraId(VALID_CAMERA_REF),
                requested_by=UserId(VALID_USER_REF),
                window_start=start,
                window_end=start - timedelta(minutes=1),
                clock=CLOCK,
            )

    def test_request_playback_starts_requested_with_playback_purpose(self) -> None:
        start = datetime(2026, 7, 20, 10, 0, 0)
        end = start + timedelta(minutes=30)
        session = VideoSession.request_playback(
            id=VideoSessionId(VALID_SESSION_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            device_id=DeviceId(VALID_DEVICE_REF),
            camera_id=CameraId(VALID_CAMERA_REF),
            requested_by=UserId(VALID_USER_REF),
            window_start=start,
            window_end=end,
            clock=CLOCK,
        )
        self.assertEqual(session.purpose, VideoPurpose.PLAYBACK)
        self.assertEqual(session.window_start, start)
        self.assertEqual(session.window_end, end)


class LifecycleTransitionTests(unittest.TestCase):
    def _make_session(self) -> VideoSession:
        session = VideoSession.request_live(
            id=VideoSessionId(VALID_SESSION_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            device_id=DeviceId(VALID_DEVICE_REF),
            camera_id=CameraId(VALID_CAMERA_REF),
            requested_by=UserId(VALID_USER_REF),
            clock=CLOCK,
        )
        session.pull_domain_events()
        return session

    def test_activate_sets_active_and_started_at(self) -> None:
        session = self._make_session()
        session.activate(clock=CLOCK)
        self.assertEqual(session.status, VideoSessionStatus.ACTIVE)
        self.assertEqual(session.started_at, CLOCK.now())
        events = session.pull_domain_events()
        self.assertEqual(events[0].event_type, "VideoSessionStarted")

    def test_activate_twice_is_idempotent_no_op(self) -> None:
        session = self._make_session()
        session.activate(clock=CLOCK)
        session.pull_domain_events()
        session.activate(clock=CLOCK)
        self.assertEqual(session.pull_domain_events(), [])

    def test_end_sets_ended_and_records_event(self) -> None:
        session = self._make_session()
        session.activate(clock=CLOCK)
        session.pull_domain_events()
        session.end(clock=CLOCK)
        self.assertEqual(session.status, VideoSessionStatus.ENDED)
        self.assertIsNotNone(session.ended_at)
        events = session.pull_domain_events()
        self.assertEqual(events[0].event_type, "VideoSessionEnded")

    def test_end_twice_is_idempotent_no_op(self) -> None:
        session = self._make_session()
        session.end(clock=CLOCK)
        session.pull_domain_events()
        session.end(clock=CLOCK)
        self.assertEqual(session.pull_domain_events(), [])

    def test_fail_sets_failed_and_records_event(self) -> None:
        session = self._make_session()
        session.fail(clock=CLOCK)
        self.assertEqual(session.status, VideoSessionStatus.FAILED)
        events = session.pull_domain_events()
        self.assertEqual(events[0].event_type, "VideoSessionFailed")

    def test_fail_twice_is_idempotent_no_op(self) -> None:
        session = self._make_session()
        session.fail(clock=CLOCK)
        session.pull_domain_events()
        session.fail(clock=CLOCK)
        self.assertEqual(session.pull_domain_events(), [])


class VideoSessionRepositoryInterfaceShapeTests(unittest.TestCase):
    def test_repository_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            VideoSessionRepository()  # type: ignore[abstract]

    def test_repository_declares_expected_methods(self) -> None:
        for name in ("get", "add", "list_all"):
            self.assertTrue(hasattr(VideoSessionRepository, name))


if __name__ == "__main__":
    unittest.main()
