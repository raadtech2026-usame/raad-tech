"""PostgreSQL-backed integration test for `reporting`'s `SqlAlchemyReportingUnitOfWork`/one
repository (Phase 17). Stdlib `unittest` — no `pytest` (not an approved dependency), using
`unittest.IsolatedAsyncioTestCase` against the real `SqlAlchemyReportingUnitOfWork` and the live
migrated schema (Alembic head `1292703c3024`), not fakes — mirroring `test_billing_repository.
py`/`test_notifications_repository.py`'s skip-guard/cleanup pattern exactly.

Covers what no in-memory unit test can prove: the round trip through the real identity-map/
`flush_tracked_changes` mechanics (including the `params_json`/`JSONB` round trip).

**Requires a reachable PostgreSQL database** configured via `RAAD_DB__URL` (`.env`). Skipped
entirely (not failed) when unavailable. Every test inserts rows tagged with a unique per-run
marker and deletes them in `tearDown`, leaving the schema exactly as found.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime

from sqlalchemy import text

from raad.core.config.settings import get_settings
from raad.core.db.engine import build_engine, build_session_factory
from raad.core.events.outbox import OutboxWriter
from raad.core.audit.writer import AuditWriter
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
class ReportingRepositoryRoundTripTests(unittest.IsolatedAsyncioTestCase):
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
        await self.engine.dispose()

    def _new_uow(self) -> SqlAlchemyReportingUnitOfWork:
        return SqlAlchemyReportingUnitOfWork(self.session_factory, self.outbox_writer, self.audit_writer)

    async def test_add_then_get_round_trips_report_run(self) -> None:
        org_id = self.id_generator.new_id()
        requester_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            report_run = ReportRun.request(
                id=ReportId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                type=ReportType(f"student_transport_{self.tag}"),
                params={"period": "2026-07", "route_ids": ["01J...", "01K..."]},
                requested_by=UserId(requester_id),
                clock=self.clock,
            )
            uow.report_runs.add(report_run)
            uow.record_events(report_run.pull_domain_events())
            await uow.commit()
            report_run_id = report_run.id
            self._created_report_run_ids.append(str(report_run_id))

        async with self._new_uow() as uow:
            fetched = await uow.report_runs.get(report_run_id)

        self.assertIsNotNone(fetched)
        self.assertEqual(str(fetched.organization_id), org_id)
        self.assertEqual(fetched.status.value, "queued")
        self.assertIsNone(fetched.artifact_url)
        self.assertEqual(
            fetched.params, {"period": "2026-07", "route_ids": ["01J...", "01K..."]}
        )

    async def test_mutation_after_get_persists_without_a_second_add(self) -> None:
        org_id = self.id_generator.new_id()
        requester_id = self.id_generator.new_id()
        async with self._new_uow() as uow:
            report_run = ReportRun.request(
                id=ReportId(self.id_generator.new_id()),
                organization_id=OrganizationId(org_id),
                type=ReportType(f"transport_payment_{self.tag}"),
                params=None,
                requested_by=UserId(requester_id),
                clock=self.clock,
            )
            uow.report_runs.add(report_run)
            uow.record_events(report_run.pull_domain_events())
            await uow.commit()
            report_run_id = report_run.id
            self._created_report_run_ids.append(str(report_run_id))

        async with self._new_uow() as uow:
            loaded = await uow.report_runs.get(report_run_id)
            loaded.start(clock=self.clock)
            loaded.succeed(
                artifact_url="https://objects.raad.example/reports/x.pdf", clock=self.clock
            )
            uow.record_events(loaded.pull_domain_events())
            await uow.commit()  # no uow.report_runs.add(loaded) - must still persist

        async with self._new_uow() as uow:
            refetched = await uow.report_runs.get(report_run_id)

        self.assertEqual(refetched.status.value, "succeeded")
        self.assertEqual(refetched.artifact_url, "https://objects.raad.example/reports/x.pdf")
        self.assertIsNotNone(refetched.completed_at)


if __name__ == "__main__":
    unittest.main()
