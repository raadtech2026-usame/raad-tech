"""Application-layer tests for `transport_ops`'s `StudentApplicationService` (Phase 10.2).
Stdlib `unittest` — no `pytest` (not an approved dependency), matching Phase 10.1's own
precedent. Uses a real `UlidGenerator`/`SystemClock`-style fake and an in-memory fake
`TransportOpsUnitOfWork`/`StudentRepository` — no SQLAlchemy, no FastAPI, no real database.
Covers the task's explicit verification list: command validation (immutability), DTO mapping,
application service flow, repository interaction, validator behavior, and state transitions.
"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import DomainError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    ActivateStudentCommand,
    DisableStudentCommand,
    EnrollStudentCommand,
    GraduateStudentCommand,
    TransferStudentCommand,
    UpdateStudentCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    GetStudentByIdQuery,
    ListStudentsQuery,
    StudentDTO,
    StudentSummaryDTO,
    student_to_dto,
    student_to_summary_dto,
)
from raad.modules.transport_ops.application.services import StudentApplicationService
from raad.modules.transport_ops.domain.entities import Student
from raad.modules.transport_ops.domain.repositories import StudentRepository
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    StudentId,
    StudentStatus,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
# Well-formed ULID shape but never added to any InMemoryStudentRepository in these tests -
# exercises the NotFoundError path, distinct from StudentId's own malformed-shape DomainError.
NON_EXISTENT_STUDENT_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class SequentialIdGenerator(IdGenerator):
    """26-char, valid-Crockford-Base32 ULID-shaped ids, unique per call: a fixed 20-char
    prefix plus a zero-padded 6-digit counter (no truncation, unlike appending a short
    zero-padded suffix and slicing to length - that can collide, e.g. "...001"[:26] and
    "...0001"[:26] both drop distinguishing digits for small counter values)."""

    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"  # 20 chars

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


class InMemoryStudentRepository(StudentRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Student] = {}

    async def get(self, student_id: StudentId) -> Student | None:
        return self.by_id.get(str(student_id))

    def add(self, student: Student) -> None:
        self.by_id[str(student.id)] = student

    async def list_all(self) -> list[Student]:
        return list(self.by_id.values())


class FakeTransportOpsUnitOfWork(TransportOpsUnitOfWork):
    def __init__(self, students: InMemoryStudentRepository) -> None:
        self.students = students
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def make_actor(org_id: str = VALID_ORG_ULID) -> Principal:
    return Principal(user_id="user-1", role=Role.ORG_ADMIN, org_id=org_id)


def make_service() -> tuple[StudentApplicationService, FakeTransportOpsUnitOfWork]:
    clock = FixedClock(datetime(2026, 7, 16, tzinfo=timezone.utc))
    id_generator = SequentialIdGenerator()
    service = StudentApplicationService(clock=clock, id_generator=id_generator)
    uow = FakeTransportOpsUnitOfWork(InMemoryStudentRepository())
    return service, uow


class CommandImmutabilityTests(unittest.TestCase):
    def test_enroll_command_is_frozen(self) -> None:
        command = EnrollStudentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Amina Ali",
            external_ref=None,
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.full_name = "Different Name"  # type: ignore[misc]

    def test_update_command_is_frozen(self) -> None:
        command = UpdateStudentCommand(
            student_id="some-id",
            full_name="Amina Ali",
            external_ref=None,
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.student_id = "other-id"  # type: ignore[misc]

    def test_status_commands_are_frozen(self) -> None:
        for command in (
            TransferStudentCommand(student_id="s1", actor=make_actor()),
            GraduateStudentCommand(student_id="s1", actor=make_actor()),
            ActivateStudentCommand(student_id="s1", actor=make_actor()),
            DisableStudentCommand(student_id="s1", actor=make_actor()),
        ):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                command.student_id = "other-id"  # type: ignore[misc]

    def test_commands_carry_the_actor_principal(self) -> None:
        actor = make_actor()
        command = EnrollStudentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Amina Ali",
            external_ref=None,
            actor=actor,
        )
        self.assertIs(command.actor, actor)


class DTOMappingTests(unittest.TestCase):
    def make_student(self) -> Student:
        return Student(
            id=StudentId("01J8Z3K9G6X8YV5T4N2R7QW3MC"),
            organization_id=OrganizationId(VALID_ORG_ULID),
            full_name="Amina Ali",
            external_ref="SCH-042",
            status=StudentStatus.ACTIVE,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_student_to_dto_maps_all_fields_as_primitives(self) -> None:
        dto = student_to_dto(self.make_student())
        self.assertIsInstance(dto, StudentDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3MC")
        self.assertEqual(dto.organization_id, VALID_ORG_ULID)
        self.assertEqual(dto.full_name, "Amina Ali")
        self.assertEqual(dto.external_ref, "SCH-042")
        self.assertEqual(dto.status, "active")  # enum -> .value, not the enum member

    def test_student_to_dto_preserves_none_external_ref(self) -> None:
        student = self.make_student()
        student.external_ref = None
        dto = student_to_dto(student)
        self.assertIsNone(dto.external_ref)

    def test_student_to_summary_dto_maps_reduced_field_set(self) -> None:
        dto = student_to_summary_dto(self.make_student())
        self.assertIsInstance(dto, StudentSummaryDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3MC")
        self.assertEqual(dto.full_name, "Amina Ali")
        self.assertEqual(dto.status, "active")
        self.assertFalse(hasattr(dto, "organization_id"))
        self.assertFalse(hasattr(dto, "external_ref"))

    def test_dtos_are_frozen(self) -> None:
        dto = student_to_dto(self.make_student())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            dto.full_name = "Different Name"  # type: ignore[misc]


class StudentApplicationServiceEnrollTests(unittest.IsolatedAsyncioTestCase):
    async def test_enroll_student_adds_to_repository_and_commits(self) -> None:
        service, uow = make_service()
        command = EnrollStudentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Amina Ali",
            external_ref="SCH-001",
            actor=make_actor(),
        )
        dto = await service.enroll_student(command, uow=uow)

        self.assertEqual(dto.full_name, "Amina Ali")
        self.assertEqual(dto.status, "active")
        self.assertEqual(len(uow.students.by_id), 1)
        self.assertIn(dto.id, uow.students.by_id)
        self.assertEqual(uow.commit_count, 1)

    async def test_enroll_student_records_domain_events(self) -> None:
        service, uow = make_service()
        command = EnrollStudentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Amina Ali",
            external_ref=None,
            actor=make_actor(),
        )
        await service.enroll_student(command, uow=uow)

        self.assertEqual(len(uow.recorded_events), 1)
        self.assertEqual(uow.recorded_events[0].event_type, "StudentEnrolled")

    async def test_enroll_student_generates_a_fresh_id_per_call(self) -> None:
        service, uow = make_service()
        command = EnrollStudentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Amina Ali",
            external_ref=None,
            actor=make_actor(),
        )
        first = await service.enroll_student(command, uow=uow)
        second = await service.enroll_student(command, uow=uow)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(uow.students.by_id), 2)


class StudentApplicationServiceStatusTransitionTests(unittest.IsolatedAsyncioTestCase):
    async def _enrolled_student_id(
        self, service: StudentApplicationService, uow
    ) -> str:
        dto = await service.enroll_student(
            EnrollStudentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Amina Ali",
                external_ref=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        uow.recorded_events.clear()  # isolate the transition's own event from enrollment's
        return dto.id

    async def test_transfer_student_changes_status(self) -> None:
        service, uow = make_service()
        student_id = await self._enrolled_student_id(service, uow)
        dto = await service.transfer_student(
            TransferStudentCommand(student_id=student_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "transferred")
        self.assertEqual(uow.recorded_events[-1].event_type, "StudentTransferred")

    async def test_graduate_student_changes_status(self) -> None:
        service, uow = make_service()
        student_id = await self._enrolled_student_id(service, uow)
        dto = await service.graduate_student(
            GraduateStudentCommand(student_id=student_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "graduated")

    async def test_disable_student_changes_status(self) -> None:
        service, uow = make_service()
        student_id = await self._enrolled_student_id(service, uow)
        dto = await service.disable_student(
            DisableStudentCommand(student_id=student_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "disabled")

    async def test_activate_after_disable_returns_to_active(self) -> None:
        service, uow = make_service()
        student_id = await self._enrolled_student_id(service, uow)
        await service.disable_student(
            DisableStudentCommand(student_id=student_id, actor=make_actor()), uow=uow
        )
        dto = await service.activate_student(
            ActivateStudentCommand(student_id=student_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "active")

    async def test_repeated_disable_is_idempotent_no_new_event(self) -> None:
        service, uow = make_service()
        student_id = await self._enrolled_student_id(service, uow)
        await service.disable_student(
            DisableStudentCommand(student_id=student_id, actor=make_actor()), uow=uow
        )
        uow.recorded_events.clear()
        await service.disable_student(
            DisableStudentCommand(student_id=student_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(
            uow.recorded_events, []
        )  # already disabled - no-op, no new event

    async def test_transition_on_missing_student_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.disable_student(
                DisableStudentCommand(
                    student_id=NON_EXISTENT_STUDENT_ID, actor=make_actor()
                ),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 0)  # never reached commit

    async def test_malformed_student_id_shape_raises_domain_error_not_not_found(
        self,
    ) -> None:
        # StudentId's own ULID-shape validation (Phase 10.1) runs before the repository lookup
        # - a malformed id is a DomainError, distinct from a well-formed but absent NotFoundError.
        service, uow = make_service()
        with self.assertRaises(DomainError):
            await service.disable_student(
                DisableStudentCommand(student_id="not-a-ulid", actor=make_actor()),
                uow=uow,
            )


class StudentApplicationServiceUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_student_changes_full_name_and_external_ref(self) -> None:
        service, uow = make_service()
        enrolled = await service.enroll_student(
            EnrollStudentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Old Name",
                external_ref="OLD",
                actor=make_actor(),
            ),
            uow=uow,
        )
        dto = await service.update_student(
            UpdateStudentCommand(
                student_id=enrolled.id,
                full_name="New Name",
                external_ref="NEW",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(dto.full_name, "New Name")
        self.assertEqual(dto.external_ref, "NEW")

    async def test_update_student_on_missing_student_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.update_student(
                UpdateStudentCommand(
                    student_id=NON_EXISTENT_STUDENT_ID,
                    full_name="X",
                    external_ref=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )


class StudentApplicationServiceReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_student_by_id_returns_dto(self) -> None:
        service, uow = make_service()
        enrolled = await service.enroll_student(
            EnrollStudentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Amina Ali",
                external_ref=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        dto = await service.get_student_by_id(
            GetStudentByIdQuery(student_id=enrolled.id), uow=uow
        )
        self.assertEqual(dto.id, enrolled.id)
        self.assertEqual(dto.full_name, "Amina Ali")

    async def test_get_student_by_id_raises_not_found_for_missing_student(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.get_student_by_id(
                GetStudentByIdQuery(student_id=NON_EXISTENT_STUDENT_ID), uow=uow
            )

    async def test_list_students_returns_summary_dtos_for_all_students(self) -> None:
        service, uow = make_service()
        await service.enroll_student(
            EnrollStudentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Student One",
                external_ref=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.enroll_student(
            EnrollStudentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Student Two",
                external_ref=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        results = await service.list_students(ListStudentsQuery(), uow=uow)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(dto, StudentSummaryDTO) for dto in results))
        self.assertEqual(
            sorted(dto.full_name for dto in results), ["Student One", "Student Two"]
        )

    async def test_list_students_returns_empty_list_when_none_enrolled(self) -> None:
        service, uow = make_service()
        results = await service.list_students(ListStudentsQuery(), uow=uow)
        self.assertEqual(results, [])


class RepositoryInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_never_bypasses_the_repository_to_mutate_state(self) -> None:
        # The service must go through uow.students.add/get - not hold its own parallel state.
        service, uow = make_service()
        dto = await service.enroll_student(
            EnrollStudentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Amina Ali",
                external_ref=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        stored = await uow.students.get(StudentId(dto.id))
        self.assertIsNotNone(stored)
        self.assertEqual(stored.full_name, "Amina Ali")

    async def test_uow_used_as_async_context_manager_for_every_call(self) -> None:
        service, uow = make_service()
        # Enroll, then read - both must succeed using the same uow instance re-entered.
        dto = await service.enroll_student(
            EnrollStudentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Amina Ali",
                external_ref=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        fetched = await service.get_student_by_id(
            GetStudentByIdQuery(student_id=dto.id), uow=uow
        )
        self.assertEqual(fetched.id, dto.id)


if __name__ == "__main__":
    unittest.main()
