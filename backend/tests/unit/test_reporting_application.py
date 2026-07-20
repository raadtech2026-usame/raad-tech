"""Application-layer tests for `reporting`'s `ReportingApplicationService` (Phase 17). Stdlib
`unittest` — no `pytest` (not an approved dependency), mirroring `test_notifications_
application.py`'s exact structure. Uses an in-memory fake for the one repository, bundled onto
one fake `ReportingUnitOfWork` — no SQLAlchemy, no FastAPI, no real database.

Covers: `request_report` (persists `QUEUED` only), `get_report_run_by_id`'s ownership
enforcement (`NotFoundError` on a non-requester caller, matching the documented 404-over-403
posture), and the application-layer-only `start_report`/`mark_report_succeeded`/
`mark_report_failed` transitions (no HTTP route, the future Report Worker's own entry points).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.reporting.application.commands import (
    MarkReportFailedCommand,
    MarkReportSucceededCommand,
    RequestReportCommand,
    StartReportCommand,
)
from raad.modules.reporting.application.ports import ReportingUnitOfWork
from raad.modules.reporting.application.queries import GetReportRunByIdQuery
from raad.modules.reporting.application.services import ReportingApplicationService
from raad.modules.reporting.domain.entities import ReportRun
from raad.modules.reporting.domain.repositories import ReportRunRepository
from raad.modules.reporting.domain.value_objects import ReportId

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
REQUESTER_USER_ID = "requester-ref-001"
OTHER_USER_ID = "other-user-ref-002"
NON_EXISTENT_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc))


class SequentialIdGenerator(IdGenerator):
    """26-char, valid-Crockford-Base32 ULID-shaped ids, unique per call — mirrors
    `test_billing_application.py`'s identical helper exactly."""

    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"  # 20 chars

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


def make_actor(user_id: str = REQUESTER_USER_ID) -> Principal:
    return Principal(user_id=user_id, role=Role.ORG_ADMIN, org_id=VALID_ORG_ULID)


class InMemoryReportRunRepository(ReportRunRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, ReportRun] = {}

    async def get(self, report_run_id: ReportId) -> ReportRun | None:
        return self.by_id.get(str(report_run_id))

    def add(self, report_run: ReportRun) -> None:
        self.by_id[str(report_run.id)] = report_run

    async def list_all(self) -> list[ReportRun]:
        return list(self.by_id.values())


class FakeReportingUnitOfWork(ReportingUnitOfWork):
    def __init__(self, report_runs: InMemoryReportRunRepository) -> None:
        self.report_runs = report_runs
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def make_uow() -> FakeReportingUnitOfWork:
    return FakeReportingUnitOfWork(InMemoryReportRunRepository())


def make_service() -> ReportingApplicationService:
    return ReportingApplicationService(clock=CLOCK, id_generator=SequentialIdGenerator())


class ReportingApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_report_persists_queued_and_returns_dto(self) -> None:
        service = make_service()
        uow = make_uow()
        report_run = await service.request_report(
            RequestReportCommand(
                organization_id=VALID_ORG_ULID,
                type="student_transport",
                params={"period": "2026-07"},
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(report_run.status, "queued")
        self.assertIsNone(report_run.artifact_url)
        self.assertEqual(report_run.requested_by, REQUESTER_USER_ID)
        self.assertEqual(uow.commit_count, 1)
        self.assertEqual(len(uow.report_runs.by_id), 1)

    async def test_get_report_run_by_id_for_requester_succeeds(self) -> None:
        service = make_service()
        uow = make_uow()
        report_run = await service.request_report(
            RequestReportCommand(
                organization_id=VALID_ORG_ULID,
                type="transport_payment",
                params=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        fetched = await service.get_report_run_by_id(
            GetReportRunByIdQuery(
                report_run_id=report_run.id, requester_user_id=REQUESTER_USER_ID
            ),
            uow=uow,
        )
        self.assertEqual(fetched.id, report_run.id)

    async def test_get_report_run_by_id_for_non_requester_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        report_run = await service.request_report(
            RequestReportCommand(
                organization_id=VALID_ORG_ULID,
                type="transport_payment",
                params=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(NotFoundError):
            await service.get_report_run_by_id(
                GetReportRunByIdQuery(
                    report_run_id=report_run.id, requester_user_id=OTHER_USER_ID
                ),
                uow=uow,
            )

    async def test_get_report_run_by_id_missing_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.get_report_run_by_id(
                GetReportRunByIdQuery(
                    report_run_id=NON_EXISTENT_ID, requester_user_id=REQUESTER_USER_ID
                ),
                uow=uow,
            )

    async def test_start_then_succeed_lifecycle(self) -> None:
        service = make_service()
        uow = make_uow()
        report_run = await service.request_report(
            RequestReportCommand(
                organization_id=VALID_ORG_ULID,
                type="student_transport",
                params=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        started = await service.start_report(
            StartReportCommand(report_run_id=report_run.id, actor=make_actor()), uow=uow
        )
        self.assertEqual(started.status, "running")

        succeeded = await service.mark_report_succeeded(
            MarkReportSucceededCommand(
                report_run_id=report_run.id,
                artifact_url="https://objects.raad.example/reports/x.pdf",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(succeeded.status, "succeeded")
        self.assertEqual(succeeded.artifact_url, "https://objects.raad.example/reports/x.pdf")
        self.assertIsNotNone(succeeded.completed_at)

    async def test_mark_report_failed(self) -> None:
        service = make_service()
        uow = make_uow()
        report_run = await service.request_report(
            RequestReportCommand(
                organization_id=VALID_ORG_ULID,
                type="student_transport",
                params=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.start_report(
            StartReportCommand(report_run_id=report_run.id, actor=make_actor()), uow=uow
        )
        failed = await service.mark_report_failed(
            MarkReportFailedCommand(report_run_id=report_run.id, actor=make_actor()), uow=uow
        )
        self.assertEqual(failed.status, "failed")
        self.assertIsNotNone(failed.completed_at)

    async def test_start_report_missing_raises_not_found(self) -> None:
        service = make_service()
        uow = make_uow()
        with self.assertRaises(NotFoundError):
            await service.start_report(
                StartReportCommand(report_run_id=NON_EXISTENT_ID, actor=make_actor()), uow=uow
            )


if __name__ == "__main__":
    unittest.main()
