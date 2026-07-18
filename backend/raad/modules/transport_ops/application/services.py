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

**Phase 10.7 addition: `StudentParentApplicationService`.** A third, separate service — not
folded into `StudentApplicationService` or `ParentApplicationService` — for the same by-natural-
API-grouping reason as above (`/students/{id}/parents` and `/parents/{id}/students` are their
own nested-resource surface, `api/routers.py`'s Phase 10.7 addendum). No `id_generator`
dependency, unlike the other two services: `StudentParent` has no surrogate id to mint
(composite-keyed by `student_id`+`parent_id`, both already supplied by the caller,
`domain/entities.py`).

**Phase 10.8 addition: `DriverApplicationService`.** A fourth, separate service, split out for
the same by-natural-API-grouping reason as `ParentApplicationService` — `/drivers` is its own
resource prefix (`api/routers.py`'s Phase 10.8 addendum), a distinct aggregate with no shared
use-case with `Student`/`Parent`/`StudentParent`. Mirrors `ParentApplicationService`'s exact
shape (register/update/activate/disable + get/list), including the `id_generator` dependency
(`Driver` has a surrogate `id`, unlike `StudentParent`).
"""

from __future__ import annotations

from raad.core.errors.exceptions import NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    ActivateDriverCommand,
    ActivateParentCommand,
    ActivateStudentCommand,
    DisableDriverCommand,
    DisableParentCommand,
    DisableStudentCommand,
    EnrollStudentCommand,
    GraduateStudentCommand,
    LinkParentToStudentCommand,
    RegisterDriverCommand,
    RegisterParentCommand,
    TransferStudentCommand,
    UnlinkParentFromStudentCommand,
    UpdateDriverCommand,
    UpdateParentCommand,
    UpdateStudentCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    DriverDTO,
    DriverSummaryDTO,
    GetDriverByIdQuery,
    GetParentByIdQuery,
    GetStudentByIdQuery,
    ListDriversQuery,
    ListParentsForStudentQuery,
    ListParentsQuery,
    ListStudentsForParentQuery,
    ListStudentsQuery,
    ParentDTO,
    ParentForStudentDTO,
    ParentSummaryDTO,
    StudentDTO,
    StudentForParentDTO,
    StudentParentDTO,
    StudentSummaryDTO,
    driver_to_dto,
    driver_to_summary_dto,
    parent_for_student_to_dto,
    parent_to_dto,
    parent_to_summary_dto,
    student_for_parent_to_dto,
    student_parent_to_dto,
    student_to_dto,
    student_to_summary_dto,
)
from raad.modules.transport_ops.application.validators import (
    ensure_link_exists,
    ensure_link_not_duplicate,
    ensure_parent_exists,
    ensure_student_exists,
)
from raad.modules.transport_ops.domain.entities import (
    Driver,
    Parent,
    Student,
    StudentParent,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
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


class StudentParentApplicationService:
    """Parent<->Student relationship (link) use-cases (Phase 10.7): link, unlink, and the two
    "list X for Y" read paths. See module docstring for why this is its own service rather than
    folded into `StudentApplicationService`/`ParentApplicationService`."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    async def link_parent_to_student(
        self, command: LinkParentToStudentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentParentDTO:
        async with uow:
            student = await ensure_student_exists(uow, StudentId(command.student_id))
            parent = await ensure_parent_exists(uow, ParentId(command.parent_id))
            await ensure_link_not_duplicate(uow, student.id, parent.id)
            link = StudentParent.link(
                student_id=student.id,
                student_organization_id=student.organization_id,
                parent_id=parent.id,
                parent_organization_id=parent.organization_id,
                relationship=command.relationship,
                is_primary=command.is_primary,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.student_parents.add(link)
            uow.record_events(link.pull_domain_events())
            await uow.commit()
            return student_parent_to_dto(link)

    async def unlink_parent_from_student(
        self, command: UnlinkParentFromStudentCommand, *, uow: TransportOpsUnitOfWork
    ) -> None:
        async with uow:
            student = await ensure_student_exists(uow, StudentId(command.student_id))
            link = await ensure_link_exists(
                uow, student.id, ParentId(command.parent_id)
            )
            link.unlink(
                organization_id=student.organization_id,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            await uow.student_parents.remove(link)
            uow.record_events(link.pull_domain_events())
            await uow.commit()

    async def list_parents_for_student(
        self, query: ListParentsForStudentQuery, *, uow: TransportOpsUnitOfWork
    ) -> list[ParentForStudentDTO]:
        async with uow:
            student = await ensure_student_exists(uow, StudentId(query.student_id))
            links = await uow.student_parents.list_by_student(student.id)
            result: list[ParentForStudentDTO] = []
            for link in links:
                parent = await uow.parents.get(link.parent_id)
                if parent is None:
                    # In-context FK guarantees the row exists, but a soft-deleted Parent
                    # (`deleted_at` set) is filtered out by `get()`'s default read - skip it
                    # rather than surfacing a confusing partial DTO for a deleted parent.
                    continue
                result.append(parent_for_student_to_dto(parent, link))
            return result

    async def list_students_for_parent(
        self, query: ListStudentsForParentQuery, *, uow: TransportOpsUnitOfWork
    ) -> list[StudentForParentDTO]:
        async with uow:
            parent = await ensure_parent_exists(uow, ParentId(query.parent_id))
            links = await uow.student_parents.list_by_parent(parent.id)
            result: list[StudentForParentDTO] = []
            for link in links:
                student = await uow.students.get(link.student_id)
                if student is None:
                    # Same soft-delete caveat as list_parents_for_student above.
                    continue
                result.append(student_for_parent_to_dto(student, link))
            return result


class DriverApplicationService:
    """Driver lifecycle use-cases: register, update, activate, disable, and the
    `GetDriverByIdQuery`/`ListDriversQuery` read paths. Mirrors `ParentApplicationService`'s
    exact shape — both aggregates share the identical "profile linked to an `iam.User` login,
    flat active/inactive status" structure (Database Design §6.1/§6.3)."""

    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    async def register_driver(
        self, command: RegisterDriverCommand, *, uow: TransportOpsUnitOfWork
    ) -> DriverDTO:
        async with uow:
            driver = Driver.register(
                id=DriverId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                user_id=UserId(command.user_id),
                license_no=command.license_no,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.drivers.add(driver)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            return driver_to_dto(driver)

    async def update_driver(
        self, command: UpdateDriverCommand, *, uow: TransportOpsUnitOfWork
    ) -> DriverDTO:
        async with uow:
            driver = await self._get_driver_or_raise(uow, command.driver_id)
            driver.update_details(
                license_no=command.license_no,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            return driver_to_dto(driver)

    async def activate_driver(
        self, command: ActivateDriverCommand, *, uow: TransportOpsUnitOfWork
    ) -> DriverDTO:
        async with uow:
            driver = await self._get_driver_or_raise(uow, command.driver_id)
            driver.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            return driver_to_dto(driver)

    async def disable_driver(
        self, command: DisableDriverCommand, *, uow: TransportOpsUnitOfWork
    ) -> DriverDTO:
        async with uow:
            driver = await self._get_driver_or_raise(uow, command.driver_id)
            driver.disable(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(driver.pull_domain_events())
            await uow.commit()
            return driver_to_dto(driver)

    async def get_driver_by_id(
        self, query: GetDriverByIdQuery, *, uow: TransportOpsUnitOfWork
    ) -> DriverDTO:
        async with uow:
            driver = await self._get_driver_or_raise(uow, query.driver_id)
            return driver_to_dto(driver)

    async def list_drivers(
        self, query: ListDriversQuery, *, uow: TransportOpsUnitOfWork
    ) -> list[DriverSummaryDTO]:
        async with uow:
            drivers = await uow.drivers.list_all()
            return [driver_to_summary_dto(driver) for driver in drivers]

    @staticmethod
    async def _get_driver_or_raise(
        uow: TransportOpsUnitOfWork, driver_id: str
    ) -> Driver:
        driver = await uow.drivers.get(DriverId(driver_id))
        if driver is None:
            raise NotFoundError(f"Driver {driver_id} not found.")
        return driver
