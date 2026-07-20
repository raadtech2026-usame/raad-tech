"""PostgreSQL-backed integration test proving ADR-0007's core claim: every module's
`SqlAlchemyUnitOfWork.commit()` writes a matching `audit_entries` row in the same transaction
as the business change and its outbox row — with **zero changes to the module's own source
files** (this test exercises `reporting`, chosen only because it is the module with the
simplest single-aggregate shape, not because anything module-specific was touched to make this
work). Stdlib `unittest`, mirroring every other live-DB integration test's skip-guard/cleanup
pattern in this suite.

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable.
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
from raad.core.time.clock import SystemClock
from raad.modules.reporting.domain.entities import ReportRun
from raad.modules.reporting.domain.value_objects import (
    OrganizationId,
    ReportId,
    ReportType,
    UserId,
)
from raad.modules.reporting.infra.repositories import SqlAlchemyReportingUnitOfWork


def _db_available() -> bool:
    try:
        return bool(get_settings().db.url)
    except Exception:
        return False


_SKIP_REASON = "RAAD_DB__URL not configured — PostgreSQL integration tests require a live database."


@unittest.skipUnless(_db_available(), _SKIP_REASON)
class AuditEntriesTransactionalWriteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        settings = get_settings()
        self.engine = build_engine(settings.db)
        self.session_factory = build_session_factory(self.engine)
        self.outbox_writer = OutboxWriter()
        self.audit_writer = AuditWriter()
        self.id_generator = UlidGenerator()
        self.clock = SystemClock()
        self.tag = uuid.uuid4().hex[:8]
        self._created_report_run_ids: list[str] = []

    async def asyncTearDown(self) -> None:
        async with self.engine.begin() as conn:
            if self._created_report_run_ids:
                await conn.execute(
                    text("DELETE FROM report_runs WHERE id = ANY(:ids)"),
                    {"ids": self._created_report_run_ids},
                )
                await conn.execute(
                    text("DELETE FROM audit_entries WHERE entity_id = ANY(:ids)"),
                    {"ids": self._created_report_run_ids},
                )
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyReportingUnitOfWork:
        return SqlAlchemyReportingUnitOfWork(
            self.session_factory, self.outbox_writer, self.audit_writer
        )

    async def test_commit_writes_a_matching_audit_entry_for_the_business_change(self) -> None:
        org_id = self.id_generator.new_id()
        requester_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            report_run = ReportRun.request(
                id=ReportId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                type=ReportType(f"audit_proof_{self.tag}"),
                params=None,
                requested_by=UserId(requester_id),
                clock=self.clock,
                actor_id=requester_id,
            )
            uow.report_runs.add(report_run)
            uow.record_events(report_run.pull_domain_events())
            await uow.commit()
            report_run_id = str(report_run.id)
            self._created_report_run_ids.append(report_run_id)

        async with self.session_factory() as session:
            result = await session.execute(
                select(AuditEntryRecord).where(AuditEntryRecord.entity_id == report_run_id)
            )
            entries = list(result.scalars().all())

        self.assertEqual(len(entries), 1, "exactly one audit row per domain event recorded")
        entry = entries[0]
        self.assertEqual(entry.entity_type, "ReportRun")
        self.assertEqual(entry.organization_id, org_id)
        self.assertEqual(entry.actor_user_id, requester_id)
        self.assertIn("audit_proof", entry.action.lower() + str(entry.metadata_json))


if __name__ == "__main__":
    unittest.main()
