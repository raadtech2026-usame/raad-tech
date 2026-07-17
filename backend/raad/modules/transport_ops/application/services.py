"""Transport Operations application services (Backend LLD §4.1/§4.3). Thin, orchestration-only
handlers — business rules stay inside the `Student` aggregate (`modules/transport_ops/domain`);
this service only: loads the aggregate via the repository bound to `TransportOpsUnitOfWork`,
invokes domain behavior, records the resulting `DomainEvent`s, commits, and returns a DTO — the
exact skeleton the LLD's §4.3 "transaction & event ordering" steps describe, identical to
`organization.application.services`.

**Documentation conflict resolved before implementing (Phase 10.2):** the task's own
instructions asked for `UpdateStudentCommand` while also saying "reuse only the completed
Student Domain" — Phase 10.1's `Student` had no field-update method. Confirmed with the user:
added one small, additive `Student.update_details` domain method (`domain/entities.py`'s Phase
10.2 addendum) rather than mutating `full_name`/`external_ref` directly from here, which would
either bypass or duplicate that class's own validation.

**No approved document names any Student use-case or application-service method** (Backend LLD
§5.2 has no `Student` skeleton; re-confirmed this phase). Method names below mirror `Student`'s
own domain method names 1:1, the same relationship `OrganizationApplicationService` has to
`Organization`.

**Phase 10.6 addition: `ParentApplicationService`.** Split from `StudentApplicationService` by
aggregate, not folded into one service — matching `fleet_device`'s
`VehicleApplicationService`/`DeviceApplicationService` split (by natural API grouping,
`.claude/rules/api.md` #2: `/students` and `/parents` both route to this module but are
distinct resource prefixes) rather than `organization`'s split-by-API-grouping-within-one-file
convention, since `Student`/`Parent` are two unrelated aggregates with no shared use-case, the
same reasoning that keeps `VehicleApplicationService` and `DeviceApplicationService` separate
classes.
"""

from __future__ import annotations

from raad.core.errors.exceptions import NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    ActivateParentCommand,
    ActivateStudentCommand,
    DisableParentCommand,
    DisableStudentCommand,
    EnrollStudentCommand,
    GraduateStudentCommand,
    RegisterParentCommand,
    TransferStudentCommand,
    UpdateParentCommand,
    UpdateStudentCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    GetParentByIdQuery,
    GetStudentByIdQuery,
    ListParentsQuery,
    ListStudentsQuery,
    ParentDTO,
    ParentSummaryDTO,
    StudentDTO,
    StudentSummaryDTO,
    parent_to_dto,
    parent_to_summary_dto,
    student_to_dto,
    student_to_summary_dto,
)
from raad.modules.transport_ops.domain.entities import Parent, Student
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    ParentId,
    PhoneNumber,
    StudentId,
    UserId,
)


class StudentApplicationService:
    """Student lifecycle use-cases: enroll, update, transfer, graduate, activate, disable, and
    the `GetStudentByIdQuery`/`ListStudentsQuery` read paths."""

    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    async def enroll_student(
        self, command: EnrollStudentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentDTO:
        async with uow:
            student = Student.enroll(
                id=StudentId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                full_name=command.full_name,
                external_ref=command.external_ref,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.students.add(student)
            uow.record_events(student.pull_domain_events())
            await uow.commit()
            return student_to_dto(student)

    async def update_student(
        self, command: UpdateStudentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentDTO:
        async with uow:
            student = await self._get_student_or_raise(uow, command.student_id)
            student.update_details(
                full_name=command.full_name,
                external_ref=command.external_ref,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(student.pull_domain_events())
            await uow.commit()
            return student_to_dto(student)

    async def transfer_student(
        self, command: TransferStudentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentDTO:
        async with uow:
            student = await self._get_student_or_raise(uow, command.student_id)
            student.transfer(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(student.pull_domain_events())
            await uow.commit()
            return student_to_dto(student)

    async def graduate_student(
        self, command: GraduateStudentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentDTO:
        async with uow:
            student = await self._get_student_or_raise(uow, command.student_id)
            student.graduate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(student.pull_domain_events())
            await uow.commit()
            return student_to_dto(student)

    async def activate_student(
        self, command: ActivateStudentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentDTO:
        async with uow:
            student = await self._get_student_or_raise(uow, command.student_id)
            student.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(student.pull_domain_events())
            await uow.commit()
            return student_to_dto(student)

    async def disable_student(
        self, command: DisableStudentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentDTO:
        async with uow:
            student = await self._get_student_or_raise(uow, command.student_id)
            student.disable(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(student.pull_domain_events())
            await uow.commit()
            return student_to_dto(student)

    async def get_student_by_id(
        self, query: GetStudentByIdQuery, *, uow: TransportOpsUnitOfWork
    ) -> StudentDTO:
        async with uow:
            student = await self._get_student_or_raise(uow, query.student_id)
            return student_to_dto(student)

    async def list_students(
        self, query: ListStudentsQuery, *, uow: TransportOpsUnitOfWork
    ) -> list[StudentSummaryDTO]:
        async with uow:
            students = await uow.students.list_all()
            return [student_to_summary_dto(student) for student in students]

    @staticmethod
    async def _get_student_or_raise(
        uow: TransportOpsUnitOfWork, student_id: str
    ) -> Student:
        student = await uow.students.get(StudentId(student_id))
        if student is None:
            raise NotFoundError(f"Student {student_id} not found.")
        return student


class ParentApplicationService:
    """Parent lifecycle use-cases: register, update, activate, disable, and the
    `GetParentByIdQuery`/`ListParentsQuery` read paths."""

    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    async def register_parent(
        self, command: RegisterParentCommand, *, uow: TransportOpsUnitOfWork
    ) -> ParentDTO:
        async with uow:
            parent = Parent.register(
                id=ParentId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                user_id=UserId(command.user_id),
                full_name=command.full_name,
                phone=PhoneNumber(command.phone) if command.phone else None,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.parents.add(parent)
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            return parent_to_dto(parent)

    async def update_parent(
        self, command: UpdateParentCommand, *, uow: TransportOpsUnitOfWork
    ) -> ParentDTO:
        async with uow:
            parent = await self._get_parent_or_raise(uow, command.parent_id)
            parent.update_details(
                full_name=command.full_name,
                phone=PhoneNumber(command.phone) if command.phone else None,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            return parent_to_dto(parent)

    async def activate_parent(
        self, command: ActivateParentCommand, *, uow: TransportOpsUnitOfWork
    ) -> ParentDTO:
        async with uow:
            parent = await self._get_parent_or_raise(uow, command.parent_id)
            parent.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            return parent_to_dto(parent)

    async def disable_parent(
        self, command: DisableParentCommand, *, uow: TransportOpsUnitOfWork
    ) -> ParentDTO:
        async with uow:
            parent = await self._get_parent_or_raise(uow, command.parent_id)
            parent.disable(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(parent.pull_domain_events())
            await uow.commit()
            return parent_to_dto(parent)

    async def get_parent_by_id(
        self, query: GetParentByIdQuery, *, uow: TransportOpsUnitOfWork
    ) -> ParentDTO:
        async with uow:
            parent = await self._get_parent_or_raise(uow, query.parent_id)
            return parent_to_dto(parent)

    async def list_parents(
        self, query: ListParentsQuery, *, uow: TransportOpsUnitOfWork
    ) -> list[ParentSummaryDTO]:
        async with uow:
            parents = await uow.parents.list_all()
            return [parent_to_summary_dto(parent) for parent in parents]

    @staticmethod
    async def _get_parent_or_raise(
        uow: TransportOpsUnitOfWork, parent_id: str
    ) -> Parent:
        parent = await uow.parents.get(ParentId(parent_id))
        if parent is None:
            raise NotFoundError(f"Parent {parent_id} not found.")
        return parent
