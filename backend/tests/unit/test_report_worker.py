"""Unit tests for `interfaces.workers.report_worker.ReportWorker` (Backend Stabilization
phase). Stdlib `unittest` — no `pytest` (not an approved dependency). Fakes bound into a real
`core.di.container.Container`, mirroring `test_notification_subscribers.py`'s identical
type-keyed substitution pattern.

Covers: a `queued` run with no `ReportRendererPort` bound ends `failed` (the documented "fail
loudly per unit of work" posture, `reporting/infra/adapters.py`'s own module docstring); a
`queued` run with a bound renderer that succeeds ends `succeeded` with the returned
`artifact_url`; a renderer that raises ends `failed`, not a crashed worker tick; multiple queued
runs are all processed in one `run_once()`.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from raad.core.di.container import Container
from raad.core.time.clock import Clock
from raad.interfaces.workers.report_worker import ReportWorker
from raad.modules.reporting.application.ports import ReportingUnitOfWork, ReportRendererPort
from raad.modules.reporting.application.services import ReportingApplicationService


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


@dataclass(frozen=True)
class _ReportRunDTO:
    id: str
    type: str
    params: dict[str, Any] | None
    organization_id: str
    status: str = "queued"


@dataclass
class RecordingReportingService:
    queued_runs: list[_ReportRunDTO]
    started: list[str] = field(default_factory=list)
    succeeded: list[tuple[str, str]] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    async def list_report_runs(self, query, *, uow):
        if query.status is None:
            return list(self.queued_runs)
        return [r for r in self.queued_runs if r.status == query.status]

    async def start_report(self, command, *, uow):
        self.started.append(command.report_run_id)

    async def mark_report_succeeded(self, command, *, uow):
        self.succeeded.append((command.report_run_id, command.artifact_url))

    async def mark_report_failed(self, command, *, uow):
        self.failed.append(command.report_run_id)


class RecordingRenderer(ReportRendererPort):
    def __init__(self, artifact_url: str = "https://objects.raad.example/r.pdf") -> None:
        self.artifact_url = artifact_url
        self.calls: list[dict[str, Any]] = []

    async def render(self, *, report_run_id, type, params, organization_id) -> str:
        self.calls.append(
            {
                "report_run_id": report_run_id,
                "type": type,
                "params": params,
                "organization_id": organization_id,
            }
        )
        return self.artifact_url


class FailingRenderer(ReportRendererPort):
    async def render(self, *, report_run_id, type, params, organization_id) -> str:
        raise RuntimeError("render engine unavailable")


def make_container(
    *, queued_runs: list[_ReportRunDTO], renderer: ReportRendererPort | None = None
) -> tuple[Container, RecordingReportingService]:
    container = Container()
    container.bind_singleton(Clock, FixedClock(datetime(2026, 7, 21, tzinfo=timezone.utc)))
    service = RecordingReportingService(queued_runs=queued_runs)
    container.bind_singleton(ReportingApplicationService, service)
    container.bind_singleton(ReportingUnitOfWork, object())
    if renderer is not None:
        container.bind_singleton(ReportRendererPort, renderer)
    return container, service


class ReportWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_renderer_bound_marks_run_failed(self) -> None:
        run = _ReportRunDTO(
            id="run-1", type="student_transport", params=None, organization_id="org-1"
        )
        container, service = make_container(queued_runs=[run])
        worker = ReportWorker(container)

        await worker.run_once()

        self.assertEqual(service.started, ["run-1"])
        self.assertEqual(service.failed, ["run-1"])
        self.assertEqual(service.succeeded, [])

    async def test_bound_renderer_succeeds_run(self) -> None:
        run = _ReportRunDTO(
            id="run-2",
            type="transport_payment",
            params={"period": "2026-07"},
            organization_id="org-1",
        )
        renderer = RecordingRenderer(artifact_url="https://objects.raad.example/x.pdf")
        container, service = make_container(queued_runs=[run], renderer=renderer)
        worker = ReportWorker(container)

        await worker.run_once()

        self.assertEqual(service.started, ["run-2"])
        self.assertEqual(service.succeeded, [("run-2", "https://objects.raad.example/x.pdf")])
        self.assertEqual(service.failed, [])
        self.assertEqual(renderer.calls[0]["report_run_id"], "run-2")
        self.assertEqual(renderer.calls[0]["params"], {"period": "2026-07"})

    async def test_renderer_raising_marks_run_failed_not_crash(self) -> None:
        run = _ReportRunDTO(
            id="run-3", type="student_transport", params=None, organization_id="org-1"
        )
        container, service = make_container(queued_runs=[run], renderer=FailingRenderer())
        worker = ReportWorker(container)

        await worker.run_once()  # must not raise

        self.assertEqual(service.failed, ["run-3"])
        self.assertEqual(service.succeeded, [])

    async def test_multiple_queued_runs_all_processed(self) -> None:
        runs = [
            _ReportRunDTO(id="run-4", type="a", params=None, organization_id="org-1"),
            _ReportRunDTO(id="run-5", type="b", params=None, organization_id="org-1"),
        ]
        renderer = RecordingRenderer()
        container, service = make_container(queued_runs=runs, renderer=renderer)
        worker = ReportWorker(container)

        await worker.run_once()

        self.assertEqual(set(service.started), {"run-4", "run-5"})
        self.assertEqual(len(service.succeeded), 2)

    async def test_no_queued_runs_is_a_clean_no_op(self) -> None:
        container, service = make_container(queued_runs=[])
        worker = ReportWorker(container)
        await worker.run_once()
        self.assertEqual(service.started, [])


if __name__ == "__main__":
    unittest.main()
