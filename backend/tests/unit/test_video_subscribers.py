"""Unit tests for `modules.video.events.subscribers` (ADR-0026 §7). Stdlib `unittest` - no
`pytest`. Mirrors `test_fleet_device_subscribers.py`'s exact convention: fakes bound directly
into a real `core.di.container.Container`, keyed by the real types each processor resolves.

Covers: each of `VideoSessionActivated`/`Ended`/`Failed` dispatches to the matching
`VideoApplicationService.mark_session_*` command with `SYSTEM_PRINCIPAL` as actor, `reason` is
threaded through for `Ended`/`Failed`, and a missing/`None` `session_id` in the payload is
dropped, not passed through as `None`.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.di.container import Container
from raad.core.events.base import DomainEvent
from raad.modules.video.application.commands import (
    MarkVideoSessionActiveCommand,
    MarkVideoSessionEndedCommand,
    MarkVideoSessionFailedCommand,
)
from raad.modules.video.application.ports import VideoUnitOfWork
from raad.modules.video.application.services import VideoApplicationService
from raad.modules.video.events.subscribers import (
    SYSTEM_PRINCIPAL,
    VideoSessionActivatedProcessor,
    VideoSessionEndedProcessor,
    VideoSessionFailedProcessor,
    register_video_processors,
)
from raad.core.events.processor import EventProcessorRegistry

_OCCURRED_AT = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)


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


if __name__ == "__main__":
    unittest.main()
