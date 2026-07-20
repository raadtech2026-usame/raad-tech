"""PostgreSQL-backed integration test for `video`'s `SqlAlchemyVideoUnitOfWork`/one repository
(Backend Stabilization phase). Stdlib `unittest` — no `pytest` (not an approved dependency),
using `unittest.IsolatedAsyncioTestCase` against the real `SqlAlchemyVideoUnitOfWork` and the
live migrated schema (Alembic head `65009ecd235a`), not fakes — mirroring
`test_reporting_repository.py`'s skip-guard/cleanup pattern exactly.

Covers what no in-memory unit test can prove: the round trip through the real identity-map/
`flush_tracked_changes` mechanics, including the nullable `window_start`/`window_end` pair for a
live session (both `NULL`) versus a playback session (both populated).

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run id
and deletes them in `tearDown`, leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.audit.writer import AuditWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.time.clock import SystemClock
from raad.modules.video.domain.entities import VideoSession
from raad.modules.video.domain.value_objects import (
    CameraId,
    DeviceId,
    OrganizationId,
    UserId,
    VideoSessionId,
)
from raad.modules.video.infra.repositories import SqlAlchemyVideoUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class VideoSessionRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_session_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_session_ids:
                await conn.execute(
                    text("DELETE FROM video_sessions WHERE id = ANY(:ids)"),
                    {"ids": self._created_session_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyVideoUnitOfWork:
        return SqlAlchemyVideoUnitOfWork(self.session_factory, self.outbox_writer, self.audit_writer)

    async def test_add_then_get_round_trips_live_session(self) -> None:
        org_id = self.id_generator.new_id()
        device_id = f"device-{self.tag}"
        camera_id = f"camera-{self.tag}"
        requester_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            session = VideoSession.request_live(
                id=VideoSessionId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                device_id=DeviceId(device_id),
                camera_id=CameraId(camera_id),
                requested_by=UserId(requester_id),
                clock=self.clock,
            )
            uow.video_sessions.add(session)
            uow.record_events(session.pull_domain_events())
            await uow.commit()
            session_id = session.id
            self._created_session_ids.append(str(session_id))

        async with self._new_uow() as uow:
            fetched = await uow.video_sessions.get(session_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(fetched.purpose.value, "live")
        self.assertEqual(fetched.status.value, "requested")
        self.assertIsNone(fetched.window_start)
        self.assertIsNone(fetched.window_end)

    async def test_mutation_after_get_persists_without_a_second_add(self) -> None:
        org_id = self.id_generator.new_id()
        device_id = f"device-{self.tag}-2"
        camera_id = f"camera-{self.tag}-2"
        requester_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            session = VideoSession.request_live(
                id=VideoSessionId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                device_id=DeviceId(device_id),
                camera_id=CameraId(camera_id),
                requested_by=UserId(requester_id),
                clock=self.clock,
            )
            uow.video_sessions.add(session)
            uow.record_events(session.pull_domain_events())
            await uow.commit()
            session_id = session.id
            self._created_session_ids.append(str(session_id))

        async with self._new_uow() as uow:
            loaded = await uow.video_sessions.get(session_id)
            loaded.activate(clock=self.clock)
            loaded.end(clock=self.clock)
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.video_sessions.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.video_sessions.get(session_id)

        self.assertEqual(refetched.status.value, "ended")
        self.assertIsNotNone(refetched.started_at)
        self.assertIsNotNone(refetched.ended_at)

    async def test_playback_session_round_trips_window(self) -> None:
        org_id = self.id_generator.new_id()
        device_id = f"device-{self.tag}-3"
        camera_id = f"camera-{self.tag}-3"
        requester_id = self.id_generator.new_id()
        start = datetime(2026, 7, 20, 9, 0, 0)
        end = start + timedelta(minutes=20)
        async with self._new_uow() as uow:
            session = VideoSession.request_playback(
                id=VideoSessionId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                device_id=DeviceId(device_id),
                camera_id=CameraId(camera_id),
                requested_by=UserId(requester_id),
                window_start=start,
                window_end=end,
                clock=self.clock,
            )
            uow.video_sessions.add(session)
            uow.record_events(session.pull_domain_events())
            await uow.commit()
            session_id = session.id
            self._created_session_ids.append(str(session_id))

        async with self._new_uow() as uow:
            fetched = await uow.video_sessions.get(session_id)

        self.assertEqual(fetched.purpose.value, "playback")
        self.assertEqual(fetched.window_start, start)
        self.assertEqual(fetched.window_end, end)


if __name__ == "__main__":
    unittest.main()
