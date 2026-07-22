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

**Phase 11 addition: `RouteApplicationService`.** A fifth, separate service — `/routes` is its
own resource prefix. `create_route` runs `ensure_route_name_available` before the aggregate
factory (mirroring `VehicleApplicationService.register_vehicle`'s `ensure_plate_no_available`
pre-check exactly). `add_stop_to_route`/`remove_stop_from_route`/`move_stop` all load the whole
`Route` aggregate (its `Stop` children ride along, `domain/repositories.py`'s Phase 11
addendum) and delegate the actual mutation to `Route`'s own methods — this service performs no
child-entity logic itself, matching `DeviceApplicationService.register_camera`'s identical
"load aggregate, call its method, commit" shape.

**Phase 12 addition: `TripApplicationService`.** A sixth, separate service — `/trips` is its
own resource prefix. `schedule_trip` runs `ensure_driver_exists`/`ensure_route_exists` before
the aggregate factory (mirroring `create_route`'s pre-check placement), passing the loaded
`Driver`/`Route`'s own `organization_id` into `Trip.schedule` for its cross-organization check.
`start_trip` and `resume_trip` both run `ensure_vehicle_has_no_active_trip` immediately before
calling the aggregate's own `start`/`resume` method — `resume_trip` needs this guard too, not
just `start_trip`: the DB partial unique index only covers `status='in_progress'`, so while a
trip sits `INTERRUPTED` a *different* trip could legally become the vehicle's active one in the
meantime, and resuming the first would otherwise silently create two in-progress trips for one
vehicle. `interrupt_trip`/`resume_trip` have no approved HTTP route this phase (`api/routers.py`'s
module docstring) but are fully implemented and unit-tested, mirroring
`remove_stop_from_route`/`move_stop`'s identical "use-case exists, no approved endpoint yet"
posture.

**Phase 13 addition: `StudentAssignmentApplicationService`.** A seventh, separate service —
`/student-assignments` is its own resource prefix. `assign_student_to_route` runs
`ensure_student_exists`/`ensure_route_exists` (both reused as-is from Phase 12/10.7 — no new
existence-check function needed for either), then `ensure_pickup_and_dropoff_stops_exist` against
the just-loaded `Route`, then `ensure_student_has_no_active_assignment`, before calling the
aggregate factory — the same ordering discipline (cheap/independent checks before the
I/O-dependent uniqueness guard) `RouteApplicationService.create_route` already establishes.
`remove_student_assignment`/`transfer_student_assignment`/`graduate_student_assignment`/
`disable_student_assignment` all mirror `StudentApplicationService`'s four identically-shaped
status methods exactly — load, call the one matching domain method, commit.
"""

from __future__ import annotations

from raad.core.errors.exceptions import NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import OffsetPage
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    ActivateDriverCommand,
    ActivateParentCommand,
    ActivateRouteCommand,
    ActivateStudentCommand,
    AddStopToRouteCommand,
    AssignStudentToRouteCommand,
    ChangeTripDriverCommand,
    CreateRouteCommand,
    DisableDriverCommand,
    DisableParentCommand,
    DisableRouteCommand,
    DisableStudentAssignmentCommand,
    DisableStudentCommand,
    EndTripCommand,
    EnrollStudentCommand,
    GraduateStudentAssignmentCommand,
    GraduateStudentCommand,
    InterruptTripCommand,
    LinkParentToStudentCommand,
    MoveStopCommand,
    RegisterDriverCommand,
    RegisterParentCommand,
    RemoveStopFromRouteCommand,
    RemoveStudentAssignmentCommand,
    ResumeTripCommand,
    ScheduleTripCommand,
    StartTripCommand,
    TransferStudentAssignmentCommand,
    TransferStudentCommand,
    UnlinkParentFromStudentCommand,
    UpdateDriverCommand,
    UpdateParentCommand,
    UpdateRouteCommand,
    UpdateStudentCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    DriverDTO,
    DriverSummaryDTO,
    GetDriverByIdQuery,
    GetParentByIdQuery,
    GetRouteByIdQuery,
    GetStudentAssignmentByIdQuery,
    GetStudentByIdQuery,
    GetTripByIdQuery,
    ListDriversQuery,
    ListParentsForStudentQuery,
    ListParentsQuery,
    ListRoutesQuery,
    ListStopsForRouteQuery,
    ListStudentAssignmentsQuery,
    ListStudentsForParentQuery,
    ListStudentsQuery,
    ListTripsQuery,
    ParentDTO,
    ParentForStudentDTO,
    ParentSummaryDTO,
    RouteDTO,
    RouteSummaryDTO,
    StopDTO,
    StudentAssignmentDTO,
    StudentAssignmentSummaryDTO,
    StudentDTO,
    StudentForParentDTO,
    StudentParentDTO,
    StudentSummaryDTO,
    TripDTO,
    TripSummaryDTO,
    driver_to_dto,
    driver_to_summary_dto,
    parent_for_student_to_dto,
    parent_to_dto,
    parent_to_summary_dto,
    route_to_dto,
    route_to_summary_dto,
    stop_to_dto,
    student_assignment_to_dto,
    student_assignment_to_summary_dto,
    student_for_parent_to_dto,
    student_parent_to_dto,
    student_to_dto,
    student_to_summary_dto,
    trip_to_dto,
    trip_to_summary_dto,
)
from raad.modules.transport_ops.application.validators import (
    ensure_driver_exists,
    ensure_link_exists,
    ensure_link_not_duplicate,
    ensure_parent_exists,
    ensure_pickup_and_dropoff_stops_exist,
    ensure_route_exists,
    ensure_route_name_available,
    ensure_student_exists,
    ensure_student_has_no_active_assignment,
    ensure_vehicle_has_no_active_trip,
)
from raad.modules.transport_ops.domain.entities import (
    Driver,
    Parent,
    Route,
    Student,
    StudentAssignment,
    StudentParent,
    Trip,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    OrganizationId,
    ParentId,
    PhoneNumber,
    RouteId,
    StopId,
    StudentAssignmentId,
    StudentId,
    TripId,
    TripType,
    UserId,
    VehicleId,
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
    ) -> OffsetPage[StudentSummaryDTO]:
        """Backs `GET /students`'s paginated/filtered/sorted contract (API Contracts §7/§8)."""
        async with uow:
            page = await uow.students.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[student_to_summary_dto(student) for student in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

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

    async def get_parent_by_user_id(
        self, user_id: str, *, uow: TransportOpsUnitOfWork
    ) -> ParentDTO | None:
        """Resolves an authenticated `Principal.user_id` to this module's own `Parent`
        aggregate — added under the Backend Stabilization phase for CR-1 enforcement
        (`interfaces/http/deps.parent_access_guard`), which starts from a JWT principal, not a
        `Parent` id. Returns `None` rather than raising — "this authenticated user has no
        `Parent` profile" is an expected, non-exceptional outcome for non-parent callers."""
        async with uow:
            parent = await uow.parents.get_by_user_id(UserId(user_id))
            return parent_to_dto(parent) if parent is not None else None

    async def list_parents(
        self, query: ListParentsQuery, *, uow: TransportOpsUnitOfWork
    ) -> OffsetPage[ParentSummaryDTO]:
        """Backs `GET /parents`'s paginated/filtered/sorted contract (API Contracts §7/§8)."""
        async with uow:
            page = await uow.parents.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[parent_to_summary_dto(parent) for parent in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

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
    ) -> OffsetPage[DriverSummaryDTO]:
        """Backs `GET /drivers`'s paginated/filtered/sorted contract (API Contracts §7/§8)."""
        async with uow:
            page = await uow.drivers.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[driver_to_summary_dto(driver) for driver in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    @staticmethod
    async def _get_driver_or_raise(
        uow: TransportOpsUnitOfWork, driver_id: str
    ) -> Driver:
        driver = await uow.drivers.get(DriverId(driver_id))
        if driver is None:
            raise NotFoundError(f"Driver {driver_id} not found.")
        return driver


class RouteApplicationService:
    """Route lifecycle + stop-management use-cases: create, update, activate, disable,
    add/remove/move stop, and the `GetRouteByIdQuery`/`ListRoutesQuery`/
    `ListStopsForRouteQuery` read paths."""

    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    async def create_route(
        self, command: CreateRouteCommand, *, uow: TransportOpsUnitOfWork
    ) -> RouteDTO:
        async with uow:
            await ensure_route_name_available(uow, command.name)

            route = Route.create(
                id=RouteId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                name=command.name,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.routes.add(route)
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            return route_to_dto(route)

    async def update_route(
        self, command: UpdateRouteCommand, *, uow: TransportOpsUnitOfWork
    ) -> RouteDTO:
        async with uow:
            route = await self._get_route_or_raise(uow, command.route_id)
            route.update_details(
                name=command.name,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            return route_to_dto(route)

    async def activate_route(
        self, command: ActivateRouteCommand, *, uow: TransportOpsUnitOfWork
    ) -> RouteDTO:
        async with uow:
            route = await self._get_route_or_raise(uow, command.route_id)
            route.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            return route_to_dto(route)

    async def disable_route(
        self, command: DisableRouteCommand, *, uow: TransportOpsUnitOfWork
    ) -> RouteDTO:
        async with uow:
            route = await self._get_route_or_raise(uow, command.route_id)
            route.disable(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            return route_to_dto(route)

    async def add_stop_to_route(
        self, command: AddStopToRouteCommand, *, uow: TransportOpsUnitOfWork
    ) -> StopDTO:
        async with uow:
            route = await self._get_route_or_raise(uow, command.route_id)
            stop = route.add_stop(
                id=StopId(self._id_generator.new_id()),
                name=command.name,
                latitude=command.latitude,
                longitude=command.longitude,
                sequence_no=command.sequence_no,
                geofence_radius_m=command.geofence_radius_m,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            return stop_to_dto(stop)

    async def remove_stop_from_route(
        self, command: RemoveStopFromRouteCommand, *, uow: TransportOpsUnitOfWork
    ) -> RouteDTO:
        """No approved HTTP route yet (`api/routers.py`'s module docstring) — reachable at
        this layer only, mirroring `DeviceApplicationService.register_camera`'s identical
        "use-case exists, no approved endpoint yet" posture."""
        async with uow:
            route = await self._get_route_or_raise(uow, command.route_id)
            route.remove_stop(
                StopId(command.stop_id),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            return route_to_dto(route)

    async def move_stop(
        self, command: MoveStopCommand, *, uow: TransportOpsUnitOfWork
    ) -> RouteDTO:
        """No approved HTTP route yet (`api/routers.py`'s module docstring) — reachable at
        this layer only, same posture as `remove_stop_from_route` above."""
        async with uow:
            route = await self._get_route_or_raise(uow, command.route_id)
            route.move_stop(
                StopId(command.stop_id),
                new_sequence_no=command.new_sequence_no,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(route.pull_domain_events())
            await uow.commit()
            return route_to_dto(route)

    async def get_route_by_id(
        self, query: GetRouteByIdQuery, *, uow: TransportOpsUnitOfWork
    ) -> RouteDTO:
        async with uow:
            route = await self._get_route_or_raise(uow, query.route_id)
            return route_to_dto(route)

    async def list_routes(
        self, query: ListRoutesQuery, *, uow: TransportOpsUnitOfWork
    ) -> OffsetPage[RouteSummaryDTO]:
        """Backs `GET /routes`'s paginated/filtered/sorted contract (API Contracts §7/§8)."""
        async with uow:
            page = await uow.routes.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[route_to_summary_dto(route) for route in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    async def list_stops_for_route(
        self, query: ListStopsForRouteQuery, *, uow: TransportOpsUnitOfWork
    ) -> list[StopDTO]:
        async with uow:
            route = await self._get_route_or_raise(uow, query.route_id)
            return [stop_to_dto(stop) for stop in route.stops]

    @staticmethod
    async def _get_route_or_raise(uow: TransportOpsUnitOfWork, route_id: str) -> Route:
        route = await uow.routes.get(RouteId(route_id))
        if route is None:
            raise NotFoundError(f"Route {route_id} not found.")
        return route


class TripApplicationService:
    """Trip lifecycle use-cases: schedule, start, end, interrupt, resume, change driver, and the
    `GetTripByIdQuery`/`ListTripsQuery` read paths. See module docstring for the
    `ensure_vehicle_has_no_active_trip` guard's placement on both `start_trip` and
    `resume_trip`."""

    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    async def schedule_trip(
        self, command: ScheduleTripCommand, *, uow: TransportOpsUnitOfWork
    ) -> TripDTO:
        async with uow:
            driver = await ensure_driver_exists(uow, DriverId(command.driver_id))
            route = await ensure_route_exists(uow, RouteId(command.route_id))

            trip = Trip.schedule(
                id=TripId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                vehicle_id=VehicleId(command.vehicle_id),
                driver_id=driver.id,
                driver_organization_id=driver.organization_id,
                route_id=route.id,
                route_organization_id=route.organization_id,
                trip_type=TripType(command.trip_type),
                scheduled_date=command.scheduled_date,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.trips.add(trip)
            uow.record_events(trip.pull_domain_events())
            await uow.commit()
            return trip_to_dto(trip)

    async def start_trip(
        self, command: StartTripCommand, *, uow: TransportOpsUnitOfWork
    ) -> TripDTO:
        async with uow:
            trip = await self._get_trip_or_raise(uow, command.trip_id)
            await ensure_vehicle_has_no_active_trip(uow, trip.vehicle_id)
            trip.start(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(trip.pull_domain_events())
            await uow.commit()
            return trip_to_dto(trip)

    async def end_trip(
        self, command: EndTripCommand, *, uow: TransportOpsUnitOfWork
    ) -> TripDTO:
        async with uow:
            trip = await self._get_trip_or_raise(uow, command.trip_id)
            trip.end(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(trip.pull_domain_events())
            await uow.commit()
            return trip_to_dto(trip)

    async def interrupt_trip(
        self, command: InterruptTripCommand, *, uow: TransportOpsUnitOfWork
    ) -> TripDTO:
        """No approved HTTP route yet (`api/routers.py`'s module docstring) — reachable at
        this layer only, mirroring `RouteApplicationService.remove_stop_from_route`'s identical
        "use-case exists, no approved endpoint yet" posture."""
        async with uow:
            trip = await self._get_trip_or_raise(uow, command.trip_id)
            trip.interrupt(
                command.reason, clock=self._clock, actor_id=command.actor.user_id
            )
            uow.record_events(trip.pull_domain_events())
            await uow.commit()
            return trip_to_dto(trip)

    async def resume_trip(
        self, command: ResumeTripCommand, *, uow: TransportOpsUnitOfWork
    ) -> TripDTO:
        """No approved HTTP route yet — same posture as `interrupt_trip` above. Also re-runs
        `ensure_vehicle_has_no_active_trip` — see module docstring for why resuming needs the
        same guard `start_trip` has."""
        async with uow:
            trip = await self._get_trip_or_raise(uow, command.trip_id)
            await ensure_vehicle_has_no_active_trip(uow, trip.vehicle_id)
            trip.resume(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(trip.pull_domain_events())
            await uow.commit()
            return trip_to_dto(trip)

    async def change_trip_driver(
        self, command: ChangeTripDriverCommand, *, uow: TransportOpsUnitOfWork
    ) -> TripDTO:
        async with uow:
            trip = await self._get_trip_or_raise(uow, command.trip_id)
            new_driver = await ensure_driver_exists(uow, DriverId(command.driver_id))
            trip.change_driver(
                new_driver.id,
                new_driver_organization_id=new_driver.organization_id,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(trip.pull_domain_events())
            await uow.commit()
            return trip_to_dto(trip)

    async def get_trip_by_id(
        self, query: GetTripByIdQuery, *, uow: TransportOpsUnitOfWork
    ) -> TripDTO:
        async with uow:
            trip = await self._get_trip_or_raise(uow, query.trip_id)
            return trip_to_dto(trip)

    async def list_trips(
        self, query: ListTripsQuery, *, uow: TransportOpsUnitOfWork
    ) -> OffsetPage[TripSummaryDTO]:
        """Backs `GET /trips`'s paginated/filtered/sorted contract (API Contracts §7/§8)."""
        async with uow:
            page = await uow.trips.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[trip_to_summary_dto(trip) for trip in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    @staticmethod
    async def _get_trip_or_raise(uow: TransportOpsUnitOfWork, trip_id: str) -> Trip:
        trip = await uow.trips.get(TripId(trip_id))
        if trip is None:
            raise NotFoundError(f"Trip {trip_id} not found.")
        return trip


class StudentAssignmentApplicationService:
    """Student-assignment lifecycle use-cases: assign, remove, transfer, graduate, disable, and
    the `GetStudentAssignmentByIdQuery`/`ListStudentAssignmentsQuery` read paths. See module
    docstring for the pre-check ordering `assign_student_to_route` follows."""

    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    async def assign_student_to_route(
        self, command: AssignStudentToRouteCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentAssignmentDTO:
        async with uow:
            student = await ensure_student_exists(uow, StudentId(command.student_id))
            route = await ensure_route_exists(uow, RouteId(command.route_id))
            ensure_pickup_and_dropoff_stops_exist(
                route,
                StopId(command.pickup_stop_id),
                StopId(command.dropoff_stop_id),
            )
            await ensure_student_has_no_active_assignment(uow, student.id)

            assignment = StudentAssignment.assign(
                id=StudentAssignmentId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                student_id=student.id,
                student_organization_id=student.organization_id,
                route_id=route.id,
                route_organization_id=route.organization_id,
                pickup_stop_id=StopId(command.pickup_stop_id),
                dropoff_stop_id=StopId(command.dropoff_stop_id),
                vehicle_id=(
                    VehicleId(command.vehicle_id)
                    if command.vehicle_id is not None
                    else None
                ),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.student_assignments.add(assignment)
            uow.record_events(assignment.pull_domain_events())
            await uow.commit()
            return student_assignment_to_dto(assignment)

    async def remove_student_assignment(
        self, command: RemoveStudentAssignmentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentAssignmentDTO:
        async with uow:
            assignment = await self._get_assignment_or_raise(
                uow, command.student_assignment_id
            )
            assignment.remove(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(assignment.pull_domain_events())
            await uow.commit()
            return student_assignment_to_dto(assignment)

    async def transfer_student_assignment(
        self, command: TransferStudentAssignmentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentAssignmentDTO:
        async with uow:
            assignment = await self._get_assignment_or_raise(
                uow, command.student_assignment_id
            )
            assignment.transfer(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(assignment.pull_domain_events())
            await uow.commit()
            return student_assignment_to_dto(assignment)

    async def graduate_student_assignment(
        self, command: GraduateStudentAssignmentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentAssignmentDTO:
        async with uow:
            assignment = await self._get_assignment_or_raise(
                uow, command.student_assignment_id
            )
            assignment.graduate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(assignment.pull_domain_events())
            await uow.commit()
            return student_assignment_to_dto(assignment)

    async def disable_student_assignment(
        self, command: DisableStudentAssignmentCommand, *, uow: TransportOpsUnitOfWork
    ) -> StudentAssignmentDTO:
        async with uow:
            assignment = await self._get_assignment_or_raise(
                uow, command.student_assignment_id
            )
            assignment.disable(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(assignment.pull_domain_events())
            await uow.commit()
            return student_assignment_to_dto(assignment)

    async def get_student_assignment_by_id(
        self, query: GetStudentAssignmentByIdQuery, *, uow: TransportOpsUnitOfWork
    ) -> StudentAssignmentDTO:
        async with uow:
            assignment = await self._get_assignment_or_raise(
                uow, query.student_assignment_id
            )
            return student_assignment_to_dto(assignment)

    async def list_student_assignments(
        self, query: ListStudentAssignmentsQuery, *, uow: TransportOpsUnitOfWork
    ) -> OffsetPage[StudentAssignmentSummaryDTO]:
        """Backs `GET /student-assignments`'s paginated/filtered/sorted contract (API
        Contracts §7/§8)."""
        async with uow:
            page = await uow.student_assignments.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[
                    student_assignment_to_summary_dto(assignment)
                    for assignment in page.data
                ],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    async def get_active_assignment_for_student(
        self, student_id: str, *, uow: TransportOpsUnitOfWork
    ) -> StudentAssignmentDTO | None:
        """Application-layer read path over `StudentAssignmentRepository.
        active_assignment_for_student` — previously reachable only as a domain-layer/repository
        method, not a standalone query. Added under the Backend Stabilization phase to back
        CR-1 enforcement (`interfaces/http/deps.parent_access_guard`), which needs a specific
        student's current `assignment_state` without loading by assignment id."""
        async with uow:
            assignment = await uow.student_assignments.active_assignment_for_student(
                StudentId(student_id)
            )
            return (
                student_assignment_to_dto(assignment) if assignment is not None else None
            )

    @staticmethod
    async def _get_assignment_or_raise(
        uow: TransportOpsUnitOfWork, student_assignment_id: str
    ) -> StudentAssignment:
        assignment = await uow.student_assignments.get(
            StudentAssignmentId(student_assignment_id)
        )
        if assignment is None:
            raise NotFoundError(
                f"StudentAssignment {student_assignment_id} not found."
            )
        return assignment
