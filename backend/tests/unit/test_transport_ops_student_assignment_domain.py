"""Domain-only tests for `transport_ops`'s `StudentAssignment` aggregate (Phase 13). Stdlib
`unittest` — no `pytest` (not an approved dependency), mirroring
`test_transport_ops_trip_domain.py`'s established precedent exactly. Covers: value-object
validation (`StudentAssignmentId`), construction, `assign()` (incl. cross-organization
rejection), every status-transition method (idempotent same-state no-ops, `ended_at` stamped
only on the actual departure from `ACTIVE`), domain-event emission (incl. the exact
LLD-documented `event_type` strings), and repository-interface shape.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain.entities import StudentAssignment
from raad.modules.transport_ops.domain.repositories import StudentAssignmentRepository
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    RouteId,
    StopId,
    StudentAssignmentId,
    StudentAssignmentStatus,
    StudentId,
    VehicleId,
)

VALID_ASSIGNMENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3AS"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ZY"
VALID_STUDENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ST"
VALID_ROUTE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3RT"
VALID_PICKUP_STOP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3P1"
VALID_DROPOFF_STOP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3D1"
VALID_VEHICLE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3VE"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def make_assignment(**overrides) -> StudentAssignment:
    defaults = dict(
        id=StudentAssignmentId(VALID_ASSIGNMENT_ULID),
        organization_id=OrganizationId(VALID_ORG_ULID),
        student_id=StudentId(VALID_STUDENT_ULID),
        route_id=RouteId(VALID_ROUTE_ULID),
        pickup_stop_id=StopId(VALID_PICKUP_STOP_ULID),
        dropoff_stop_id=StopId(VALID_DROPOFF_STOP_ULID),
        vehicle_id=VehicleId(VALID_VEHICLE_ULID),
        status=StudentAssignmentStatus.ACTIVE,
        assigned_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        ended_at=None,
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return StudentAssignment(**defaults)


class StudentAssignmentIdValidationTests(unittest.TestCase):
    def test_valid_ulid_constructs(self) -> None:
        assignment_id = StudentAssignmentId(VALID_ASSIGNMENT_ULID)
        self.assertEqual(str(assignment_id), VALID_ASSIGNMENT_ULID)

    def test_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            StudentAssignmentId("TOOSHORT")

    def test_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            StudentAssignmentId("")

    def test_equality_is_by_value(self) -> None:
        self.assertEqual(
            StudentAssignmentId(VALID_ASSIGNMENT_ULID),
            StudentAssignmentId(VALID_ASSIGNMENT_ULID),
        )


class StudentAssignmentConstructionTests(unittest.TestCase):
    def test_valid_assignment_constructs(self) -> None:
        assignment = make_assignment()
        self.assertEqual(assignment.status, StudentAssignmentStatus.ACTIVE)
        self.assertIsNone(assignment.ended_at)

    def test_vehicle_id_is_optional(self) -> None:
        assignment = make_assignment(vehicle_id=None)
        self.assertIsNone(assignment.vehicle_id)

    def test_equality_is_by_id_not_by_field_values(self) -> None:
        a = make_assignment(status=StudentAssignmentStatus.ACTIVE)
        b = make_assignment(status=StudentAssignmentStatus.REMOVED)  # same id
        self.assertEqual(a, b)

    def test_inequality_across_different_ids(self) -> None:
        other_id = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"
        a = make_assignment()
        b = make_assignment(id=StudentAssignmentId(other_id))
        self.assertNotEqual(a, b)

    def test_hash_matches_id_hash(self) -> None:
        assignment = make_assignment()
        self.assertEqual(hash(assignment), hash(assignment.id))


class StudentAssignmentAssignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc))

    def _assign(self, **overrides):
        defaults = dict(
            id=StudentAssignmentId(VALID_ASSIGNMENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            student_id=StudentId(VALID_STUDENT_ULID),
            student_organization_id=OrganizationId(VALID_ORG_ULID),
            route_id=RouteId(VALID_ROUTE_ULID),
            route_organization_id=OrganizationId(VALID_ORG_ULID),
            pickup_stop_id=StopId(VALID_PICKUP_STOP_ULID),
            dropoff_stop_id=StopId(VALID_DROPOFF_STOP_ULID),
            vehicle_id=VehicleId(VALID_VEHICLE_ULID),
            clock=self.clock,
        )
        defaults.update(overrides)
        return StudentAssignment.assign(**defaults)

    def test_assign_starts_active(self) -> None:
        assignment = self._assign()
        self.assertEqual(assignment.status, StudentAssignmentStatus.ACTIVE)
        self.assertEqual(assignment.assigned_at, self.clock.now())
        self.assertIsNone(assignment.ended_at)

    def test_assign_with_no_vehicle_succeeds(self) -> None:
        assignment = self._assign(vehicle_id=None)
        self.assertIsNone(assignment.vehicle_id)

    def test_assign_records_student_assignment_created_event(self) -> None:
        assignment = self._assign(actor_id="admin-1")
        events = assignment.pull_domain_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "StudentAssignmentCreated")
        self.assertEqual(event.aggregate_type, "StudentAssignment")
        self.assertEqual(event.aggregate_id, VALID_ASSIGNMENT_ULID)
        self.assertEqual(event.org_id, VALID_ORG_ULID)
        self.assertEqual(event.payload["student_id"], VALID_STUDENT_ULID)
        self.assertEqual(event.payload["route_id"], VALID_ROUTE_ULID)
        self.assertEqual(event.payload["pickup_stop_id"], VALID_PICKUP_STOP_ULID)
        self.assertEqual(event.payload["dropoff_stop_id"], VALID_DROPOFF_STOP_ULID)
        self.assertEqual(event.payload["vehicle_id"], VALID_VEHICLE_ULID)
        self.assertEqual(event.payload["actor_id"], "admin-1")

    def test_assign_with_no_vehicle_records_null_vehicle_in_payload(self) -> None:
        assignment = self._assign(vehicle_id=None)
        events = assignment.pull_domain_events()
        self.assertIsNone(events[0].payload["vehicle_id"])

    def test_assign_rejects_cross_organization_student(self) -> None:
        with self.assertRaises(DomainError):
            self._assign(student_organization_id=OrganizationId(OTHER_ORG_ULID))

    def test_assign_rejects_cross_organization_route(self) -> None:
        with self.assertRaises(DomainError):
            self._assign(route_organization_id=OrganizationId(OTHER_ORG_ULID))


class StudentAssignmentStatusTransitionTests(unittest.TestCase):
    """No documented transition graph (unlike `Trip`) - every status directly settable,
    idempotent same-state no-op, mirroring `Student`'s own precedent exactly."""

    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc))

    def test_remove_changes_status_stamps_ended_at_and_records_event(self) -> None:
        assignment = make_assignment(status=StudentAssignmentStatus.ACTIVE)
        assignment.remove(clock=self.clock, actor_id="admin-1")
        self.assertEqual(assignment.status, StudentAssignmentStatus.REMOVED)
        self.assertEqual(assignment.ended_at, self.clock.now())
        events = assignment.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "StudentAssignmentRemoved")
        self.assertEqual(events[0].aggregate_type, "StudentAssignment")
        self.assertEqual(events[0].payload, {"actor_id": "admin-1"})

    def test_transfer_changes_status_stamps_ended_at_and_records_event(self) -> None:
        assignment = make_assignment(status=StudentAssignmentStatus.ACTIVE)
        assignment.transfer(clock=self.clock)
        self.assertEqual(assignment.status, StudentAssignmentStatus.TRANSFERRED)
        self.assertEqual(assignment.ended_at, self.clock.now())
        events = assignment.pull_domain_events()
        self.assertEqual(events[0].event_type, "StudentTransferred")

    def test_graduate_changes_status_stamps_ended_at_and_records_event(self) -> None:
        assignment = make_assignment(status=StudentAssignmentStatus.ACTIVE)
        assignment.graduate(clock=self.clock)
        self.assertEqual(assignment.status, StudentAssignmentStatus.GRADUATED)
        self.assertEqual(assignment.ended_at, self.clock.now())
        events = assignment.pull_domain_events()
        self.assertEqual(events[0].event_type, "StudentGraduated")

    def test_disable_changes_status_stamps_ended_at_and_records_event(self) -> None:
        assignment = make_assignment(status=StudentAssignmentStatus.ACTIVE)
        assignment.disable(clock=self.clock)
        self.assertEqual(assignment.status, StudentAssignmentStatus.DISABLED)
        self.assertEqual(assignment.ended_at, self.clock.now())
        events = assignment.pull_domain_events()
        self.assertEqual(events[0].event_type, "StudentDisabled")

    def test_remove_when_already_removed_is_idempotent_no_op(self) -> None:
        assignment = make_assignment(status=StudentAssignmentStatus.REMOVED)
        assignment.remove(clock=self.clock)
        self.assertEqual(assignment.pull_domain_events(), [])

    def test_transfer_when_already_transferred_is_idempotent_no_op(self) -> None:
        assignment = make_assignment(status=StudentAssignmentStatus.TRANSFERRED)
        assignment.transfer(clock=self.clock)
        self.assertEqual(assignment.pull_domain_events(), [])

    def test_moving_between_two_non_active_statuses_does_not_restamp_ended_at(
        self,
    ) -> None:
        """The literal reading of 'ended_at set when status leaves active' - see
        `domain/entities.py`'s module docstring for why a later non-active-to-non-active move
        does not touch `ended_at` again."""
        original_ended_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        assignment = make_assignment(
            status=StudentAssignmentStatus.REMOVED, ended_at=original_ended_at
        )
        assignment.disable(clock=self.clock)
        self.assertEqual(assignment.status, StudentAssignmentStatus.DISABLED)
        self.assertEqual(assignment.ended_at, original_ended_at)

    def test_no_status_restriction_removed_can_be_re_disabled(self) -> None:
        # No documented transition graph forbids this - same "no invented restriction graph"
        # precedent `Student`'s own status methods already establish.
        assignment = make_assignment(status=StudentAssignmentStatus.REMOVED)
        assignment.disable(clock=self.clock)
        self.assertEqual(assignment.status, StudentAssignmentStatus.DISABLED)


class StudentAssignmentRepositoryInterfaceShapeTests(unittest.TestCase):
    def test_repository_is_abstract(self) -> None:
        with self.assertRaises(TypeError):
            StudentAssignmentRepository()  # type: ignore[abstract]

    def test_repository_declares_expected_methods(self) -> None:
        for method_name in (
            "get",
            "add",
            "list_all",
            "active_assignment_for_student",
        ):
            self.assertTrue(hasattr(StudentAssignmentRepository, method_name))


if __name__ == "__main__":
    unittest.main()
