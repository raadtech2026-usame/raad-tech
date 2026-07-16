"""Domain-only tests for `transport_ops`'s `Student` aggregate (Phase 10.1). Stdlib
`unittest` — no `pytest` (not an approved dependency anywhere in `backend/pyproject.toml`,
`.claude/rules/workflow.md` #1/#2), matching the `services/jt808/` service's own established
precedent for this repository. Covers: value-object validation, state transitions (idempotent
no-ops), repository-interface shape, and domain-event emission — the task's explicit
verification list for this phase.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain.entities import Student
from raad.modules.transport_ops.domain.repositories import StudentRepository
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    StudentId,
    StudentStatus,
)

VALID_STUDENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MC"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def make_student(**overrides) -> Student:
    defaults = dict(
        id=StudentId(VALID_STUDENT_ULID),
        organization_id=OrganizationId(VALID_ORG_ULID),
        full_name="Amina Ali",
        external_ref=None,
        status=StudentStatus.ACTIVE,
    )
    defaults.update(overrides)
    return Student(**defaults)


class StudentIdValidationTests(unittest.TestCase):
    def test_valid_ulid_constructs(self) -> None:
        student_id = StudentId(VALID_STUDENT_ULID)
        self.assertEqual(str(student_id), VALID_STUDENT_ULID)

    def test_too_short_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            StudentId("TOOSHORT")

    def test_lowercase_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            StudentId(VALID_STUDENT_ULID.lower())

    def test_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            StudentId("")

    def test_invalid_crockford_characters_raise_domain_error(self) -> None:
        # 'I', 'L', 'O', 'U' are excluded from Crockford Base32.
        with self.assertRaises(DomainError):
            StudentId("0" * 25 + "I")

    def test_equality_is_by_value(self) -> None:
        self.assertEqual(StudentId(VALID_STUDENT_ULID), StudentId(VALID_STUDENT_ULID))


class OrganizationIdValidationTests(unittest.TestCase):
    def test_non_empty_string_constructs(self) -> None:
        org_id = OrganizationId("any-opaque-value")
        self.assertEqual(str(org_id), "any-opaque-value")

    def test_empty_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            OrganizationId("")

    def test_does_not_re_validate_ulid_shape(self) -> None:
        # Cross-module reference: opaque non-empty string only, per .claude/rules/database.md
        # #3 - this must NOT reject a non-ULID-shaped id.
        OrganizationId("not-a-ulid-at-all")


class StudentConstructionValidationTests(unittest.TestCase):
    def test_valid_student_constructs(self) -> None:
        student = make_student()
        self.assertEqual(student.full_name, "Amina Ali")
        self.assertEqual(student.status, StudentStatus.ACTIVE)
        self.assertIsNone(student.external_ref)

    def test_empty_full_name_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            make_student(full_name="")

    def test_full_name_over_200_chars_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            make_student(full_name="A" * 201)

    def test_full_name_exactly_200_chars_is_valid(self) -> None:
        student = make_student(full_name="A" * 200)
        self.assertEqual(len(student.full_name), 200)

    def test_external_ref_over_64_chars_raises_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            make_student(external_ref="X" * 65)

    def test_external_ref_exactly_64_chars_is_valid(self) -> None:
        student = make_student(external_ref="X" * 64)
        self.assertEqual(len(student.external_ref), 64)

    def test_external_ref_none_is_valid(self) -> None:
        student = make_student(external_ref=None)
        self.assertIsNone(student.external_ref)

    def test_equality_is_by_id_not_by_field_values(self) -> None:
        a = make_student(full_name="Amina Ali")
        b = make_student(full_name="Different Name")  # same id, different name
        self.assertEqual(a, b)

    def test_inequality_across_different_ids(self) -> None:
        other_id = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
        a = make_student()
        b = make_student(id=StudentId(other_id))
        self.assertNotEqual(a, b)

    def test_hash_matches_id_hash(self) -> None:
        student = make_student()
        self.assertEqual(hash(student), hash(student.id))


class StudentEnrollTests(unittest.TestCase):
    def test_enroll_starts_active(self) -> None:
        clock = FixedClock(datetime(2026, 7, 16, tzinfo=timezone.utc))
        student = Student.enroll(
            id=StudentId(VALID_STUDENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            full_name="Amina Ali",
            clock=clock,
        )
        self.assertEqual(student.status, StudentStatus.ACTIVE)

    def test_enroll_records_student_enrolled_event(self) -> None:
        clock = FixedClock(datetime(2026, 7, 16, tzinfo=timezone.utc))
        student = Student.enroll(
            id=StudentId(VALID_STUDENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            full_name="Amina Ali",
            external_ref="SCH-042",
            clock=clock,
            actor_id="actor-1",
        )
        events = student.pull_domain_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "StudentEnrolled")
        self.assertEqual(event.aggregate_type, "Student")
        self.assertEqual(event.aggregate_id, VALID_STUDENT_ULID)
        self.assertEqual(event.org_id, VALID_ORG_ULID)
        self.assertEqual(event.occurred_at, clock.now())
        self.assertEqual(
            event.payload,
            {
                "full_name": "Amina Ali",
                "external_ref": "SCH-042",
                "actor_id": "actor-1",
            },
        )

    def test_enroll_with_invalid_full_name_raises_before_recording_event(self) -> None:
        clock = FixedClock(datetime(2026, 7, 16, tzinfo=timezone.utc))
        with self.assertRaises(DomainError):
            Student.enroll(
                id=StudentId(VALID_STUDENT_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                full_name="",
                clock=clock,
            )


class StudentStatusTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(datetime(2026, 7, 16, tzinfo=timezone.utc))

    def test_disable_changes_status_and_records_event(self) -> None:
        student = make_student(status=StudentStatus.ACTIVE)
        student.disable(clock=self.clock, actor_id="admin-1")
        self.assertEqual(student.status, StudentStatus.DISABLED)
        events = student.pull_domain_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "StudentDisabled")
        self.assertEqual(events[0].payload, {"actor_id": "admin-1"})

    def test_graduate_changes_status_and_records_event(self) -> None:
        student = make_student(status=StudentStatus.ACTIVE)
        student.graduate(clock=self.clock)
        self.assertEqual(student.status, StudentStatus.GRADUATED)
        events = student.pull_domain_events()
        self.assertEqual(events[0].event_type, "StudentGraduated")

    def test_transfer_changes_status_and_records_event(self) -> None:
        student = make_student(status=StudentStatus.ACTIVE)
        student.transfer(clock=self.clock)
        self.assertEqual(student.status, StudentStatus.TRANSFERRED)
        events = student.pull_domain_events()
        self.assertEqual(events[0].event_type, "StudentTransferred")

    def test_activate_changes_status_and_records_event(self) -> None:
        student = make_student(status=StudentStatus.DISABLED)
        student.activate(clock=self.clock)
        self.assertEqual(student.status, StudentStatus.ACTIVE)
        events = student.pull_domain_events()
        self.assertEqual(events[0].event_type, "StudentActivated")

    def test_disable_when_already_disabled_is_idempotent_no_op(self) -> None:
        student = make_student(status=StudentStatus.DISABLED)
        student.disable(clock=self.clock)
        self.assertEqual(student.status, StudentStatus.DISABLED)
        self.assertEqual(student.pull_domain_events(), [])

    def test_graduate_when_already_graduated_is_idempotent_no_op(self) -> None:
        student = make_student(status=StudentStatus.GRADUATED)
        student.graduate(clock=self.clock)
        self.assertEqual(student.pull_domain_events(), [])

    def test_transfer_when_already_transferred_is_idempotent_no_op(self) -> None:
        student = make_student(status=StudentStatus.TRANSFERRED)
        student.transfer(clock=self.clock)
        self.assertEqual(student.pull_domain_events(), [])

    def test_activate_when_already_active_is_idempotent_no_op(self) -> None:
        student = make_student(status=StudentStatus.ACTIVE)
        student.activate(clock=self.clock)
        self.assertEqual(student.pull_domain_events(), [])

    def test_status_is_freely_settable_between_any_two_values(self) -> None:
        # No transition diagram is documented (value_objects.py's StudentStatus docstring) -
        # every value must be reachable directly from every other, not just from ACTIVE.
        student = make_student(status=StudentStatus.GRADUATED)
        student.transfer(clock=self.clock)
        self.assertEqual(student.status, StudentStatus.TRANSFERRED)
        student.disable(clock=self.clock)
        self.assertEqual(student.status, StudentStatus.DISABLED)
        student.activate(clock=self.clock)
        self.assertEqual(student.status, StudentStatus.ACTIVE)

    def test_clock_is_never_called_internally_besides_via_parameter(self) -> None:
        # Determinism check: the same FixedClock instant is used for every recorded event.
        student = make_student(status=StudentStatus.ACTIVE)
        student.disable(clock=self.clock)
        event = student.pull_domain_events()[0]
        self.assertEqual(event.occurred_at, self.clock.now())


class DomainEventBufferingTests(unittest.TestCase):
    def test_pull_domain_events_drains_the_buffer(self) -> None:
        clock = FixedClock(datetime(2026, 7, 16, tzinfo=timezone.utc))
        student = Student.enroll(
            id=StudentId(VALID_STUDENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            full_name="Amina Ali",
            clock=clock,
        )
        first_pull = student.pull_domain_events()
        second_pull = student.pull_domain_events()
        self.assertEqual(len(first_pull), 1)
        self.assertEqual(second_pull, [])

    def test_multiple_mutations_buffer_multiple_events_in_order(self) -> None:
        clock = FixedClock(datetime(2026, 7, 16, tzinfo=timezone.utc))
        student = make_student(status=StudentStatus.ACTIVE)
        student.disable(clock=clock)
        student.activate(clock=clock)
        events = student.pull_domain_events()
        self.assertEqual(
            [e.event_type for e in events], ["StudentDisabled", "StudentActivated"]
        )


class StudentRepositoryInterfaceTests(unittest.TestCase):
    def test_cannot_instantiate_abstract_repository_directly(self) -> None:
        with self.assertRaises(TypeError):
            StudentRepository()  # abstract - no concrete get/add

    def test_concrete_implementation_satisfying_the_interface_can_be_instantiated(
        self,
    ) -> None:
        class InMemoryStudentRepository(StudentRepository):
            def __init__(self) -> None:
                self._students: dict[str, Student] = {}

            async def get(self, student_id: StudentId) -> Student | None:
                return self._students.get(str(student_id))

            def add(self, student: Student) -> None:
                self._students[str(student.id)] = student

        repo = InMemoryStudentRepository()
        student = make_student()
        repo.add(student)
        self.assertIs(repo._students[str(student.id)], student)

    def test_incomplete_implementation_missing_add_cannot_be_instantiated(self) -> None:
        class IncompleteRepository(StudentRepository):
            async def get(self, student_id: StudentId) -> Student | None:
                return None

        with self.assertRaises(TypeError):
            IncompleteRepository()


if __name__ == "__main__":
    unittest.main()
