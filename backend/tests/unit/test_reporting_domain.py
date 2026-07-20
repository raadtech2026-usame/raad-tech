"""Domain-only tests for `reporting`'s `ReportRun` aggregate (Phase 17). Stdlib `unittest` — no
`pytest` (not an approved dependency), mirroring `test_billing_domain.py`/`test_notifications_
domain.py`'s established precedent.

Covers: value-object validation (`ReportId`, opaque cross-module VOs, `ReportType`'s length/
non-empty checks), construction, every documented lifecycle method (`request`/`start`/`succeed`/
`fail`, including the idempotent same-state no-op on `start`), domain-event emission, and
repository-interface shape.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.reporting.domain.entities import ReportRun
from raad.modules.reporting.domain.repositories import ReportRunRepository
from raad.modules.reporting.domain.value_objects import (
    OrganizationId,
    ReportId,
    ReportStatus,
    ReportType,
    UserId,
)

VALID_REPORT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3RP"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_REQUESTER_REF = "some-opaque-requester-ref"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


CLOCK = FixedClock(datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc))


# --- Value objects -----------------------------------------------------------------------


class ReportIdValidationTests(unittest.TestCase):
    def test_valid_ulid_constructs(self) -> None:
        self.assertEqual(str(ReportId(VALID_REPORT_ULID)), VALID_REPORT_ULID)

    def test_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            ReportId("TOOSHORT")

    def test_lowercase_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            ReportId(VALID_REPORT_ULID.lower())


class OpaqueCrossModuleValueObjectTests(unittest.TestCase):
    def test_organization_id_non_empty_constructs(self) -> None:
        self.assertEqual(str(OrganizationId(VALID_ORG_ULID)), VALID_ORG_ULID)

    def test_organization_id_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            OrganizationId("")

    def test_user_id_arbitrary_non_ulid_string_is_accepted(self) -> None:
        self.assertEqual(str(UserId(VALID_REQUESTER_REF)), VALID_REQUESTER_REF)

    def test_user_id_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            UserId("")


class ReportTypeValidationTests(unittest.TestCase):
    def test_non_empty_type_constructs(self) -> None:
        self.assertEqual(str(ReportType("student_transport")), "student_transport")

    def test_empty_type_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            ReportType("")

    def test_type_too_long_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            ReportType("x" * 81)

    def test_type_at_max_length_is_accepted(self) -> None:
        ReportType("x" * 80)


# --- ReportRun -------------------------------------------------------------------------------


class ReportRunTests(unittest.TestCase):
    def _make_report_run(self, **overrides) -> ReportRun:
        defaults = dict(
            id=ReportId(VALID_REPORT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            type=ReportType("student_transport"),
            params={"period": "2026-07"},
            requested_by=UserId(VALID_REQUESTER_REF),
            clock=CLOCK,
        )
        defaults.update(overrides)
        return ReportRun.request(**defaults)

    def test_request_starts_queued(self) -> None:
        report_run = self._make_report_run()
        self.assertEqual(report_run.status, ReportStatus.QUEUED)
        self.assertIsNone(report_run.artifact_url)
        self.assertIsNone(report_run.completed_at)

    def test_request_records_report_requested_event(self) -> None:
        report_run = self._make_report_run()
        events = report_run.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "ReportRequested")
        self.assertEqual(events[0].aggregate_type, "ReportRun")
        self.assertEqual(events[0].org_id, VALID_ORG_ULID)

    def test_request_with_no_params_is_accepted(self) -> None:
        report_run = self._make_report_run(params=None)
        self.assertIsNone(report_run.params)

    def test_start_transitions_to_running(self) -> None:
        report_run = self._make_report_run()
        report_run.pull_domain_events()
        report_run.start(clock=CLOCK)
        self.assertEqual(report_run.status, ReportStatus.RUNNING)
        events = report_run.pull_domain_events()
        self.assertEqual(events[0].event_type, "ReportStarted")

    def test_start_when_already_running_is_idempotent_no_op(self) -> None:
        report_run = self._make_report_run()
        report_run.start(clock=CLOCK)
        report_run.pull_domain_events()
        report_run.start(clock=CLOCK)
        self.assertEqual(report_run.pull_domain_events(), [])

    def test_succeed_sets_artifact_url_and_completed_at(self) -> None:
        report_run = self._make_report_run()
        report_run.start(clock=CLOCK)
        report_run.pull_domain_events()
        report_run.succeed(artifact_url="https://objects.raad.example/reports/01J...pdf", clock=CLOCK)
        self.assertEqual(report_run.status, ReportStatus.SUCCEEDED)
        self.assertEqual(
            report_run.artifact_url, "https://objects.raad.example/reports/01J...pdf"
        )
        self.assertEqual(report_run.completed_at, CLOCK.now())
        events = report_run.pull_domain_events()
        self.assertEqual(events[0].event_type, "ReportSucceeded")

    def test_fail_sets_completed_at(self) -> None:
        report_run = self._make_report_run()
        report_run.start(clock=CLOCK)
        report_run.pull_domain_events()
        report_run.fail(clock=CLOCK)
        self.assertEqual(report_run.status, ReportStatus.FAILED)
        self.assertEqual(report_run.completed_at, CLOCK.now())
        events = report_run.pull_domain_events()
        self.assertEqual(events[0].event_type, "ReportFailed")

    def test_report_status_enum_matches_documented_catalogue(self) -> None:
        expected = {"queued", "running", "succeeded", "failed"}
        self.assertEqual({s.value for s in ReportStatus}, expected)


# --- Repository interface shape -----------------------------------------------------------


class RepositoryInterfaceShapeTests(unittest.TestCase):
    def test_report_run_repository_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            ReportRunRepository()  # type: ignore[abstract]

    def test_report_run_repository_declares_expected_methods(self) -> None:
        for method in ("get", "add", "list_all"):
            self.assertTrue(hasattr(ReportRunRepository, method))


if __name__ == "__main__":
    unittest.main()
