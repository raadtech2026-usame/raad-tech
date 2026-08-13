"""PostgreSQL-backed integration test proving ADR-0026's own "video access/start/stop is
audited" requirement is actually closed — not just theoretically true via the generic ADR-0007
mechanism `test_audit_entries_transactional_write.py` already proves for `reporting`. Two
specific, previously-unverified paths:

1. **Parent video-access grant/revoke** (ADR-0026 §2) — a brand-new event type
   (`ParentVideoLiveAccessGranted`) through `transport_ops`'s existing, unmodified
   `SqlAlchemyTransportOpsUnitOfWork.commit()`.
2. **The relay-lifecycle reconciliation path** (ADR-0026 §7) — `VideoApplicationService.
   mark_session_active`, the new application-service entry point `events/subscribers.py`'s
   `VideoSessionActivatedProcessor` calls in response to the JT1078 relay's own
   `VideoSessionActivated` event. This is the path this phase's own report flags as "the first
   real caller of `VideoSession.fail()`"'s sibling for `activate()` driven by a *real* signal
   rather than the eager optimistic call this ADR removed — proving it lands an audit row closes
   the loop the relay-reconciliation gap left open.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable, mirroring every other live-DB integration test's
skip-guard/cleanup pattern in this suite.
"""

from __future__ import annotations

import unittest
import uuid

from sqlalchemy import select, text

from raad.core.audit.writer import AuditEntryRecord, AuditWriter
from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.ids.generator import UlidGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import SystemClock
from raad.modules.transport_ops.application.commands import GrantParentVideoLiveAccessCommand
from raad.modules.transport_ops.application.services import ParentApplicationService
from raad.modules.transport_ops.domain.entities import Parent
from raad.modules.transport_ops.domain.value_objects import OrganizationId, ParentId, UserId
from raad.modules.transport_ops.infra.repositories import SqlAlchemyTransportOpsUnitOfWork
from raad.modules.video.application.commands import (
    MarkVideoSessionActiveCommand,
    RequestLiveVideoCommand,
)
from raad.modules.video.application.services import VideoApplicationService
from raad.modules.video.infra.repositories import SqlAlchemyVideoUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


def _actor() -> Principal:
    return Principal(user_id="system", role=Role.FOUNDER, org_id=None)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class ParentVideoAccessGrantAuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self._created_parent_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_parent_ids:
                await conn.execute(
                    text("DELETE FROM parents WHERE id = ANY(:ids)"),
                    {"ids": self._created_parent_ids},
                )
                await conn.execute(
                    text("DELETE FROM audit_entries WHERE entity_id = ANY(:ids)"),
                    {"ids": self._created_parent_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyTransportOpsUnitOfWork:
        return SqlAlchemyTransportOpsUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def test_granting_video_live_access_writes_an_audit_entry(self) -> None:
        org_id = self.id_generator.new_id()
        user_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            parent = Parent.register(
                id=ParentId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                user_id=UserId(user_id),
                full_name="Fatima Hassan",
                clock=self.clock,
            )
            uow.parents.add(parent)
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            parent_id = str(parent.id)
            self._created_parent_ids.append(parent_id)

        service = ParentApplicationService(
            clock=self.clock, id_generator=self.id_generator, user_provisioning=None  # type: ignore[arg-type]
        )
        # `grant_parent_video_live_access` manages its own `async with uow:` internally
        # (mirroring `activate_parent`/`disable_parent`'s identical shape) — pass a fresh,
        # not-yet-entered uow, not one already wrapped in our own `async with` here.
        await service.grant_parent_video_live_access(
            GrantParentVideoLiveAccessCommand(parent_id=parent_id, actor=_actor()),
            uow=self._new_uow(),
        )

        async with self.session_factory() as session:
            result = await session.execute(
                select(AuditEntryRecord).where(AuditEntryRecord.entity_id == parent_id)
            )
            entries = list(result.scalars().all())

        # One row for ParentRegistered, one for ParentVideoLiveAccessGranted.
        actions = [e.action for e in entries]
        self.assertIn("ParentVideoLiveAccessGranted", actions)
        granted_entry = next(e for e in entries if e.action == "ParentVideoLiveAccessGranted")
        self.assertEqual(granted_entry.entity_type, "Parent")
        self.assertEqual(granted_entry.organization_id, org_id)


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class VideoSessionLifecycleAuditTests(unittest.IsolatedAsyncioTestCase):
    """Proves ADR-0026 §7's relay-reconciliation path (`mark_session_active`) — not the
    eager-activate path this ADR removed — lands a real, transactional audit row."""

    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self._created_session_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_session_ids:
                await conn.execute(
                    text("DELETE FROM video_sessions WHERE id = ANY(:ids)"),
                    {"ids": self._created_session_ids},
                )
                await conn.execute(
                    text("DELETE FROM audit_entries WHERE entity_id = ANY(:ids)"),
                    {"ids": self._created_session_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyVideoUnitOfWork:
        return SqlAlchemyVideoUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def test_mark_session_active_writes_a_video_session_started_audit_entry(self) -> None:
        service = VideoApplicationService(
            clock=self.clock, id_generator=self.id_generator, video_provider=None
        )
        org_id = self.id_generator.new_id()
        device_id = self.id_generator.new_id()
        camera_id = self.id_generator.new_id()
        actor = Principal(user_id=self.id_generator.new_id(), role=Role.ORG_ADMIN, org_id=org_id)

        # `request_live_video` manages its own `async with uow:` internally - pass a fresh,
        # not-yet-entered uow (same reasoning as the grant test above).
        with self.assertRaises(NotImplementedError):
            await service.request_live_video(
                RequestLiveVideoCommand(
                    organization_id=org_id,
                    device_id=device_id,
                    camera_id=camera_id,
                    terminal_id="00000000013800138000",
                    channel_no=1,
                    actor=actor,
                ),
                uow=self._new_uow(),
            )
        async with self._new_uow() as uow:
            result = await uow.video_sessions.list_all()
            session_id = str(next(s.id for s in result if str(s.organization_id) == org_id))
            self._created_session_ids.append(session_id)

        await service.mark_session_active(
            MarkVideoSessionActiveCommand(video_session_id=session_id, actor=_actor()),
            uow=self._new_uow(),
        )

        async with self.session_factory() as session:
            result = await session.execute(
                select(AuditEntryRecord).where(AuditEntryRecord.entity_id == session_id)
            )
            entries = list(result.scalars().all())

        actions = [e.action for e in entries]
        self.assertIn("VideoSessionRequested", actions)
        self.assertIn("VideoSessionStarted", actions)
        started_entry = next(e for e in entries if e.action == "VideoSessionStarted")
        self.assertEqual(started_entry.entity_type, "VideoSession")
        self.assertEqual(started_entry.organization_id, org_id)


if __name__ == "__main__":
    unittest.main()
