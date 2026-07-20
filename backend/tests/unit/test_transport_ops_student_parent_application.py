"""Application-layer tests for `transport_ops`'s `StudentParentApplicationService`
(Phase 10.7). Stdlib `unittest` — no `pytest` (not an approved dependency), mirroring
`test_transport_ops_parent_application.py`'s exact structure. Uses in-memory fakes for
`StudentRepository`/`ParentRepository`/`StudentParentRepository`, bundled onto one fake
`TransportOpsUnitOfWork` — no SQLAlchemy, no FastAPI, no real database. Covers: command
immutability, DTO mapping, link/unlink orchestration, cross-organization rejection,
duplicate-link rejection, not-found paths, and the two "list X for Y" read paths.
"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import ConflictError, DomainError, NotFoundError
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    LinkParentToStudentCommand,
    UnlinkParentFromStudentCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    ListParentsForStudentQuery,
    ListStudentsForParentQuery,
    ParentForStudentDTO,
    StudentForParentDTO,
    StudentParentDTO,
)
from raad.modules.transport_ops.application.services import (
    StudentParentApplicationService,
)
from raad.modules.transport_ops.domain.entities import Parent, Student, StudentParent
from raad.modules.transport_ops.domain.repositories import (
    ParentRepository,
    StudentParentRepository,
    StudentRepository,
)
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    ParentId,
    ParentStatus,
    StudentId,
    StudentStatus,
    UserId,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ZY"
VALID_STUDENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MC"
VALID_PARENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
NON_EXISTENT_STUDENT_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"
NON_EXISTENT_PARENT_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZX"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class InMemoryStudentRepository(StudentRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Student] = {}

    async def get(self, student_id: StudentId) -> Student | None:
        return self.by_id.get(str(student_id))

    def add(self, student: Student) -> None:
        self.by_id[str(student.id)] = student

    async def list_all(self) -> list[Student]:
        return list(self.by_id.values())


class InMemoryParentRepository(ParentRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Parent] = {}

    async def get(self, parent_id: ParentId) -> Parent | None:
        return self.by_id.get(str(parent_id))

    async def get_by_user_id(self, user_id) -> Parent | None:
        return next(
            (p for p in self.by_id.values() if str(p.user_id) == str(user_id)), None
        )

    def add(self, parent: Parent) -> None:
        self.by_id[str(parent.id)] = parent

    async def list_all(self) -> list[Parent]:
        return list(self.by_id.values())


class InMemoryStudentParentRepository(StudentParentRepository):
    def __init__(self) -> None:
        self.by_key: dict[tuple[str, str], StudentParent] = {}

    async def get(
        self, student_id: StudentId, parent_id: ParentId
    ) -> StudentParent | None:
        return self.by_key.get((str(student_id), str(parent_id)))

    def add(self, link: StudentParent) -> None:
        self.by_key[(str(link.student_id), str(link.parent_id))] = link

    async def remove(self, link: StudentParent) -> None:
        self.by_key.pop((str(link.student_id), str(link.parent_id)), None)

    async def list_by_student(self, student_id: StudentId) -> list[StudentParent]:
        return [
            link
            for link in self.by_key.values()
            if str(link.student_id) == str(student_id)
        ]

    async def list_by_parent(self, parent_id: ParentId) -> list[StudentParent]:
        return [
            link
            for link in self.by_key.values()
            if str(link.parent_id) == str(parent_id)
        ]


class FakeTransportOpsUnitOfWork(TransportOpsUnitOfWork):
    def __init__(
        self,
        students: InMemoryStudentRepository,
        parents: InMemoryParentRepository,
        student_parents: InMemoryStudentParentRepository,
    ) -> None:
        self.students = students
        self.parents = parents
        self.student_parents = student_parents
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
    return Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=org_id)


def make_service() -> (
    tuple[StudentParentApplicationService, FakeTransportOpsUnitOfWork]
):
    clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
    service = StudentParentApplicationService(clock=clock)
    uow = FakeTransportOpsUnitOfWork(
        InMemoryStudentRepository(),
        InMemoryParentRepository(),
        InMemoryStudentParentRepository(),
    )
    return service, uow


def seed_student(
    uow: FakeTransportOpsUnitOfWork,
    *,
    student_id: str = VALID_STUDENT_ULID,
    organization_id: str = VALID_ORG_ULID,
) -> Student:
    student = Student(
        id=StudentId(student_id),
        organization_id=OrganizationId(organization_id),
        full_name="Amina Ali",
        external_ref=None,
        status=StudentStatus.ACTIVE,
    )
    uow.students.add(student)
    return student


def seed_parent(
    uow: FakeTransportOpsUnitOfWork,
    *,
    parent_id: str = VALID_PARENT_ULID,
    organization_id: str = VALID_ORG_ULID,
) -> Parent:
    parent = Parent(
        id=ParentId(parent_id),
        organization_id=OrganizationId(organization_id),
        user_id=UserId("01J8Z3K9G6X8YV5T4N2R7QW3UU"),
        full_name="Fatima Hassan",
        phone=None,
        status=ParentStatus.ACTIVE,
    )
    uow.parents.add(parent)
    return parent


class CommandImmutabilityTests(unittest.TestCase):
    def test_link_command_is_frozen(self) -> None:
        command = LinkParentToStudentCommand(
            student_id=VALID_STUDENT_ULID,
            parent_id=VALID_PARENT_ULID,
            relationship="mother",
            is_primary=True,
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.relationship = "father"  # type: ignore[misc]

    def test_unlink_command_is_frozen(self) -> None:
        command = UnlinkParentFromStudentCommand(
            student_id=VALID_STUDENT_ULID,
            parent_id=VALID_PARENT_ULID,
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.student_id = "other-id"  # type: ignore[misc]

    def test_commands_carry_the_actor_principal(self) -> None:
        actor = make_actor()
        command = LinkParentToStudentCommand(
            student_id=VALID_STUDENT_ULID,
            parent_id=VALID_PARENT_ULID,
            relationship=None,
            is_primary=False,
            actor=actor,
        )
        self.assertIs(command.actor, actor)


class DTOShapeTests(unittest.TestCase):
    def test_student_parent_dto_is_frozen(self) -> None:
        dto = StudentParentDTO(
            student_id=VALID_STUDENT_ULID,
            parent_id=VALID_PARENT_ULID,
            relationship="mother",
            is_primary=True,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            dto.relationship = "father"  # type: ignore[misc]

    def test_parent_for_student_dto_is_frozen(self) -> None:
        dto = ParentForStudentDTO(
            parent_id=VALID_PARENT_ULID,
            full_name="Fatima Hassan",
            phone=None,
            status="active",
            relationship="mother",
            is_primary=True,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            dto.full_name = "Different Name"  # type: ignore[misc]

    def test_student_for_parent_dto_is_frozen(self) -> None:
        dto = StudentForParentDTO(
            student_id=VALID_STUDENT_ULID,
            full_name="Amina Ali",
            status="active",
            relationship="mother",
            is_primary=True,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            dto.full_name = "Different Name"  # type: ignore[misc]


class LinkParentToStudentTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_adds_to_repository_and_commits(self) -> None:
        service, uow = make_service()
        seed_student(uow)
        seed_parent(uow)
        command = LinkParentToStudentCommand(
            student_id=VALID_STUDENT_ULID,
            parent_id=VALID_PARENT_ULID,
            relationship="mother",
            is_primary=True,
            actor=make_actor(),
        )
        dto = await service.link_parent_to_student(command, uow=uow)

        self.assertEqual(dto.student_id, VALID_STUDENT_ULID)
        self.assertEqual(dto.parent_id, VALID_PARENT_ULID)
        self.assertEqual(dto.relationship, "mother")
        self.assertTrue(dto.is_primary)
        self.assertEqual(len(uow.student_parents.by_key), 1)
        self.assertEqual(uow.commit_count, 1)

    async def test_link_records_domain_event(self) -> None:
        service, uow = make_service()
        seed_student(uow)
        seed_parent(uow)
        command = LinkParentToStudentCommand(
            student_id=VALID_STUDENT_ULID,
            parent_id=VALID_PARENT_ULID,
            relationship=None,
            is_primary=False,
            actor=make_actor(),
        )
        await service.link_parent_to_student(command, uow=uow)

        self.assertEqual(len(uow.recorded_events), 1)
        self.assertEqual(uow.recorded_events[0].event_type, "StudentParentLinked")

    async def test_link_with_missing_student_raises_not_found(self) -> None:
        service, uow = make_service()
        seed_parent(uow)
        command = LinkParentToStudentCommand(
            student_id=NON_EXISTENT_STUDENT_ID,
            parent_id=VALID_PARENT_ULID,
            relationship=None,
            is_primary=False,
            actor=make_actor(),
        )
        with self.assertRaises(NotFoundError):
            await service.link_parent_to_student(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)

    async def test_link_with_missing_parent_raises_not_found(self) -> None:
        service, uow = make_service()
        seed_student(uow)
        command = LinkParentToStudentCommand(
            student_id=VALID_STUDENT_ULID,
            parent_id=NON_EXISTENT_PARENT_ID,
            relationship=None,
            is_primary=False,
            actor=make_actor(),
        )
        with self.assertRaises(NotFoundError):
            await service.link_parent_to_student(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)

    async def test_link_duplicate_raises_conflict_error(self) -> None:
        service, uow = make_service()
        seed_student(uow)
        seed_parent(uow)
        command = LinkParentToStudentCommand(
            student_id=VALID_STUDENT_ULID,
            parent_id=VALID_PARENT_ULID,
            relationship=None,
            is_primary=False,
            actor=make_actor(),
        )
        await service.link_parent_to_student(command, uow=uow)
        with self.assertRaises(ConflictError):
            await service.link_parent_to_student(command, uow=uow)
        self.assertEqual(uow.commit_count, 1)  # second attempt never reached commit

    async def test_link_cross_organization_raises_domain_error(self) -> None:
        service, uow = make_service()
        seed_student(uow, organization_id=VALID_ORG_ULID)
        seed_parent(uow, organization_id=OTHER_ORG_ULID)
        command = LinkParentToStudentCommand(
            student_id=VALID_STUDENT_ULID,
            parent_id=VALID_PARENT_ULID,
            relationship=None,
            is_primary=False,
            actor=make_actor(),
        )
        with self.assertRaises(DomainError):
            await service.link_parent_to_student(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)
        self.assertEqual(len(uow.student_parents.by_key), 0)


class UnlinkParentFromStudentTests(unittest.IsolatedAsyncioTestCase):
    async def test_unlink_removes_from_repository_and_commits(self) -> None:
        service, uow = make_service()
        seed_student(uow)
        seed_parent(uow)
        await service.link_parent_to_student(
            LinkParentToStudentCommand(
                student_id=VALID_STUDENT_ULID,
                parent_id=VALID_PARENT_ULID,
                relationship=None,
                is_primary=False,
                actor=make_actor(),
            ),
            uow=uow,
        )
        uow.recorded_events.clear()

        await service.unlink_parent_from_student(
            UnlinkParentFromStudentCommand(
                student_id=VALID_STUDENT_ULID,
                parent_id=VALID_PARENT_ULID,
                actor=make_actor(),
            ),
            uow=uow,
        )

        self.assertEqual(len(uow.student_parents.by_key), 0)
        self.assertEqual(uow.recorded_events[-1].event_type, "StudentParentUnlinked")

    async def test_unlink_missing_link_raises_not_found(self) -> None:
        service, uow = make_service()
        seed_student(uow)
        with self.assertRaises(NotFoundError):
            await service.unlink_parent_from_student(
                UnlinkParentFromStudentCommand(
                    student_id=VALID_STUDENT_ULID,
                    parent_id=NON_EXISTENT_PARENT_ID,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_unlink_missing_student_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.unlink_parent_from_student(
                UnlinkParentFromStudentCommand(
                    student_id=NON_EXISTENT_STUDENT_ID,
                    parent_id=VALID_PARENT_ULID,
                    actor=make_actor(),
                ),
                uow=uow,
            )


class ListParentsForStudentTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_parents_for_student_returns_joined_dtos(self) -> None:
        service, uow = make_service()
        seed_student(uow)
        seed_parent(uow, parent_id=VALID_PARENT_ULID)
        other_parent_id = "01J8Z3K9G6X8YV5T4N2R7QW3PP"
        seed_parent(uow, parent_id=other_parent_id)
        await service.link_parent_to_student(
            LinkParentToStudentCommand(
                student_id=VALID_STUDENT_ULID,
                parent_id=VALID_PARENT_ULID,
                relationship="mother",
                is_primary=True,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.link_parent_to_student(
            LinkParentToStudentCommand(
                student_id=VALID_STUDENT_ULID,
                parent_id=other_parent_id,
                relationship="father",
                is_primary=False,
                actor=make_actor(),
            ),
            uow=uow,
        )

        results = await service.list_parents_for_student(
            ListParentsForStudentQuery(student_id=VALID_STUDENT_ULID), uow=uow
        )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(dto, ParentForStudentDTO) for dto in results))
        self.assertEqual(
            sorted(dto.relationship for dto in results), ["father", "mother"]
        )

    async def test_list_parents_for_student_returns_empty_when_none_linked(
        self,
    ) -> None:
        service, uow = make_service()
        seed_student(uow)
        results = await service.list_parents_for_student(
            ListParentsForStudentQuery(student_id=VALID_STUDENT_ULID), uow=uow
        )
        self.assertEqual(results, [])

    async def test_list_parents_for_missing_student_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.list_parents_for_student(
                ListParentsForStudentQuery(student_id=NON_EXISTENT_STUDENT_ID), uow=uow
            )


class ListStudentsForParentTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_students_for_parent_returns_joined_dtos(self) -> None:
        service, uow = make_service()
        seed_parent(uow)
        other_student_id = "01J8Z3K9G6X8YV5T4N2R7QW3SS"
        seed_student(uow, student_id=VALID_STUDENT_ULID)
        seed_student(uow, student_id=other_student_id)
        await service.link_parent_to_student(
            LinkParentToStudentCommand(
                student_id=VALID_STUDENT_ULID,
                parent_id=VALID_PARENT_ULID,
                relationship="mother",
                is_primary=True,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.link_parent_to_student(
            LinkParentToStudentCommand(
                student_id=other_student_id,
                parent_id=VALID_PARENT_ULID,
                relationship="mother",
                is_primary=False,
                actor=make_actor(),
            ),
            uow=uow,
        )

        results = await service.list_students_for_parent(
            ListStudentsForParentQuery(parent_id=VALID_PARENT_ULID), uow=uow
        )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(dto, StudentForParentDTO) for dto in results))

    async def test_list_students_for_parent_returns_empty_when_none_linked(
        self,
    ) -> None:
        service, uow = make_service()
        seed_parent(uow)
        results = await service.list_students_for_parent(
            ListStudentsForParentQuery(parent_id=VALID_PARENT_ULID), uow=uow
        )
        self.assertEqual(results, [])

    async def test_list_students_for_missing_parent_raises_not_found(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.list_students_for_parent(
                ListStudentsForParentQuery(parent_id=NON_EXISTENT_PARENT_ID), uow=uow
            )


if __name__ == "__main__":
    unittest.main()
