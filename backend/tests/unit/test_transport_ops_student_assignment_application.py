"""Application-layer tests for `transport_ops`'s `StudentAssignmentApplicationService` (Phase
13). Stdlib `unittest` — no `pytest` (not an approved dependency), mirroring
`test_transport_ops_trip_application.py`'s exact structure. Uses in-memory fakes for
`StudentAssignmentRepository`/`StudentRepository`/`RouteRepository`, bundled onto one fake
`TransportOpsUnitOfWork` — no SQLAlchemy, no FastAPI, no real database. Covers: command
immutability, DTO mapping, assign/remove/transfer/graduate/disable orchestration,
`ensure_student_exists`/`ensure_route_exists`/`ensure_pickup_and_dropoff_stops_exist` not-found
paths, `ensure_student_has_no_active_assignment`'s `ConflictError`, and the read paths.
"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import ConflictError, DomainError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import FilterCondition, OffsetPage, OffsetPageRequest, SortSpec
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    AssignStudentToRouteCommand,
    DisableStudentAssignmentCommand,
    GraduateStudentAssignmentCommand,
    RemoveStudentAssignmentCommand,
    TransferStudentAssignmentCommand,
)
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.application.queries import (
    GetStudentAssignmentByIdQuery,
    ListStudentAssignmentsQuery,
    StudentAssignmentDTO,
    StudentAssignmentSummaryDTO,
)
from raad.modules.transport_ops.application.services import (
    StudentAssignmentApplicationService,
)
from raad.modules.transport_ops.domain.entities import (
    Route,
    Stop,
    Student,
    StudentAssignment,
)
from raad.modules.transport_ops.domain.repositories import (
    RouteRepository,
    StudentAssignmentRepository,
    StudentRepository,
)
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    RouteId,
    RouteStatus,
    StopId,
    StudentAssignmentId,
    StudentAssignmentStatus,
    StudentId,
    StudentStatus,
    VehicleId,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ZY"
VALID_STUDENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ST"
VALID_ROUTE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3RT"
VALID_PICKUP_STOP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3P1"
VALID_DROPOFF_STOP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3D1"
OTHER_STOP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3P9"
VALID_VEHICLE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3VE"
NON_EXISTENT_STUDENT_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"
NON_EXISTENT_ROUTE_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZX"
NON_EXISTENT_ASSIGNMENT_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZW"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class SequentialIdGenerator(IdGenerator):
    """26-char, valid-Crockford-Base32 ULID-shaped ids, unique per call - mirrors
    `test_transport_ops_trip_application.py`'s identical helper exactly."""

    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"  # 20 chars

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


def _field_text(item: object, field_name: str) -> str:
    value = getattr(item, field_name)
    value = getattr(value, "value", value)
    return "" if value is None else str(value)


def _matches_filter(item: object, condition: FilterCondition) -> bool:
    text = _field_text(item, condition.field)
    if condition.op == "eq":
        return text == condition.value
    if condition.op == "in":
        return text in {part.strip() for part in condition.value.split(",")}
    if condition.op == "gte":
        return text >= condition.value
    if condition.op == "lte":
        return text <= condition.value
    if condition.op == "gt":
        return text > condition.value
    if condition.op == "lt":
        return text < condition.value
    return True


def _paginate_in_memory(
    items: list,
    page_request: OffsetPageRequest,
    *,
    sort: list[SortSpec],
    filters: list[FilterCondition],
    search: str | None,
    search_field: str = "status",
) -> OffsetPage:
    """Shared in-memory equivalent of `SqlAlchemyRepositoryBase.list_page` (`core/db/
    repository.py`), for fake repositories that can't run real SQL — duplicated per module's
    own test file rather than a shared test helper, mirroring
    `test_organization_application.py`'s own established "duplicated per module" precedent.
    `StudentAssignment` has no `searchable_fields` whitelist (`infra/repositories.py`'s Tier 2
    pagination phase addition) — `search_field`/`search` are accepted for shape-parity with
    every other module's identical helper but are never exercised by this file's own tests."""
    for condition in filters:
        items = [item for item in items if _matches_filter(item, condition)]
    if search:
        items = [
            item
            for item in items
            if search.lower() in _field_text(item, search_field).lower()
        ]
    for spec in reversed(sort):
        items = sorted(
            items, key=lambda item: _field_text(item, spec.field), reverse=spec.descending
        )
    if not sort:
        items = sorted(items, key=lambda item: str(item.id))
    total = len(items)
    start = page_request.offset
    end = start + page_request.page_size
    return OffsetPage(
        data=items[start:end], total=total, page=page_request.page, page_size=page_request.page_size
    )


class InMemoryStudentAssignmentRepository(StudentAssignmentRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, StudentAssignment] = {}

    async def get(
        self, student_assignment_id: StudentAssignmentId
    ) -> StudentAssignment | None:
        return self.by_id.get(str(student_assignment_id))

    def add(self, assignment: StudentAssignment) -> None:
        self.by_id[str(assignment.id)] = assignment

    async def list_all(self) -> list[StudentAssignment]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[StudentAssignment]:
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )

    async def active_assignment_for_student(
        self, student_id: StudentId
    ) -> StudentAssignment | None:
        return next(
            (
                assignment
                for assignment in self.by_id.values()
                if str(assignment.student_id) == str(student_id)
                and assignment.status == StudentAssignmentStatus.ACTIVE
            ),
            None,
        )


class InMemoryStudentRepository(StudentRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Student] = {}

    async def get(self, student_id: StudentId) -> Student | None:
        return self.by_id.get(str(student_id))

    def add(self, student: Student) -> None:
        self.by_id[str(student.id)] = student

    async def list_all(self) -> list[Student]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Student]:
        # Not this file's own listing focus (see `test_transport_ops_student_application.py`
        # for `Student`'s dedicated pagination tests) - only implemented here because
        # `StudentRepository` is an ABC `StudentAssignmentApplicationService`'s tests must
        # still construct.
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
            search_field="full_name",
        )


class InMemoryRouteRepository(RouteRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Route] = {}

    async def get(self, route_id: RouteId) -> Route | None:
        return self.by_id.get(str(route_id))

    async def get_by_name(self, name: str) -> Route | None:
        return next((r for r in self.by_id.values() if r.name == name), None)

    def add(self, route: Route) -> None:
        self.by_id[str(route.id)] = route

    async def list_all(self) -> list[Route]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Route]:
        # Not this file's own listing focus (see `test_transport_ops_route_application.py`
        # for `Route`'s dedicated pagination tests) - only implemented here because
        # `RouteRepository` is an ABC `StudentAssignmentApplicationService`'s tests must still
        # construct.
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
            search_field="name",
        )


class FakeTransportOpsUnitOfWork(TransportOpsUnitOfWork):
    def __init__(
        self,
        student_assignments: InMemoryStudentAssignmentRepository,
        students: InMemoryStudentRepository,
        routes: InMemoryRouteRepository,
    ) -> None:
        self.student_assignments = student_assignments
        self.students = students
        self.routes = routes
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


def make_student(
    student_id: str = VALID_STUDENT_ULID, organization_id: str = VALID_ORG_ULID
) -> Student:
    return Student(
        id=StudentId(student_id),
        organization_id=OrganizationId(organization_id),
        full_name="Test Student",
        external_ref=None,
        status=StudentStatus.ACTIVE,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def make_route(
    route_id: str = VALID_ROUTE_ULID, organization_id: str = VALID_ORG_ULID
) -> Route:
    return Route(
        id=RouteId(route_id),
        organization_id=OrganizationId(organization_id),
        name="Morning Route A",
        status=RouteStatus.ACTIVE,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        stops=[
            Stop(
                id=StopId(VALID_PICKUP_STOP_ULID),
                name="Pickup",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                geofence_radius_m=None,
            ),
            Stop(
                id=StopId(VALID_DROPOFF_STOP_ULID),
                name="Dropoff",
                latitude=2.6,
                longitude=45.4,
                sequence_no=2,
                geofence_radius_m=None,
            ),
        ],
    )


def make_service() -> tuple[
    StudentAssignmentApplicationService, FakeTransportOpsUnitOfWork
]:
    clock = FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc))
    id_generator = SequentialIdGenerator()
    service = StudentAssignmentApplicationService(
        clock=clock, id_generator=id_generator
    )
    uow = FakeTransportOpsUnitOfWork(
        InMemoryStudentAssignmentRepository(),
        InMemoryStudentRepository(),
        InMemoryRouteRepository(),
    )
    return service, uow


def seed_student_and_route(uow: FakeTransportOpsUnitOfWork) -> None:
    uow.students.add(make_student())
    uow.routes.add(make_route())


def make_assign_command(**overrides) -> AssignStudentToRouteCommand:
    defaults = dict(
        organization_id=VALID_ORG_ULID,
        student_id=VALID_STUDENT_ULID,
        route_id=VALID_ROUTE_ULID,
        pickup_stop_id=VALID_PICKUP_STOP_ULID,
        dropoff_stop_id=VALID_DROPOFF_STOP_ULID,
        vehicle_id=VALID_VEHICLE_ULID,
        actor=make_actor(),
    )
    defaults.update(overrides)
    return AssignStudentToRouteCommand(**defaults)


class CommandImmutabilityTests(unittest.TestCase):
    def test_assign_command_is_frozen(self) -> None:
        command = make_assign_command()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.student_id = "other-student"  # type: ignore[misc]

    def test_status_commands_are_frozen(self) -> None:
        for command in (
            RemoveStudentAssignmentCommand(
                student_assignment_id="a1", actor=make_actor()
            ),
            TransferStudentAssignmentCommand(
                student_assignment_id="a1", actor=make_actor()
            ),
            GraduateStudentAssignmentCommand(
                student_assignment_id="a1", actor=make_actor()
            ),
            DisableStudentAssignmentCommand(
                student_assignment_id="a1", actor=make_actor()
            ),
        ):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                command.student_assignment_id = "other-id"  # type: ignore[misc]

    def test_commands_carry_the_actor_principal(self) -> None:
        actor = make_actor()
        command = make_assign_command(actor=actor)
        self.assertIs(command.actor, actor)


class AssignStudentToRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_assign_adds_to_repository_and_commits(self) -> None:
        service, uow = make_service()
        seed_student_and_route(uow)
        dto = await service.assign_student_to_route(make_assign_command(), uow=uow)

        self.assertEqual(dto.status, "active")
        self.assertEqual(len(uow.student_assignments.by_id), 1)
        self.assertEqual(uow.commit_count, 1)

    async def test_assign_records_domain_events(self) -> None:
        service, uow = make_service()
        seed_student_and_route(uow)
        await service.assign_student_to_route(make_assign_command(), uow=uow)
        self.assertEqual(len(uow.recorded_events), 1)
        self.assertEqual(uow.recorded_events[0].event_type, "StudentAssignmentCreated")

    async def test_assign_with_nonexistent_student_raises_not_found_error(
        self,
    ) -> None:
        service, uow = make_service()
        uow.routes.add(make_route())
        with self.assertRaises(NotFoundError):
            await service.assign_student_to_route(
                make_assign_command(student_id=NON_EXISTENT_STUDENT_ID), uow=uow
            )

    async def test_assign_with_nonexistent_route_raises_not_found_error(self) -> None:
        service, uow = make_service()
        uow.students.add(make_student())
        with self.assertRaises(NotFoundError):
            await service.assign_student_to_route(
                make_assign_command(route_id=NON_EXISTENT_ROUTE_ID), uow=uow
            )

    async def test_assign_with_pickup_stop_not_on_route_raises_not_found_error(
        self,
    ) -> None:
        service, uow = make_service()
        seed_student_and_route(uow)
        with self.assertRaises(NotFoundError):
            await service.assign_student_to_route(
                make_assign_command(pickup_stop_id=OTHER_STOP_ULID), uow=uow
            )

    async def test_assign_with_dropoff_stop_not_on_route_raises_not_found_error(
        self,
    ) -> None:
        service, uow = make_service()
        seed_student_and_route(uow)
        with self.assertRaises(NotFoundError):
            await service.assign_student_to_route(
                make_assign_command(dropoff_stop_id=OTHER_STOP_ULID), uow=uow
            )

    async def test_assign_with_cross_organization_student_raises_domain_error(
        self,
    ) -> None:
        service, uow = make_service()
        uow.students.add(make_student(organization_id=OTHER_ORG_ULID))
        uow.routes.add(make_route())
        with self.assertRaises(DomainError):
            await service.assign_student_to_route(make_assign_command(), uow=uow)

    async def test_assign_with_no_vehicle_succeeds(self) -> None:
        service, uow = make_service()
        seed_student_and_route(uow)
        dto = await service.assign_student_to_route(
            make_assign_command(vehicle_id=None), uow=uow
        )
        self.assertIsNone(dto.vehicle_id)

    async def test_assign_rejects_when_student_already_has_active_assignment(
        self,
    ) -> None:
        service, uow = make_service()
        seed_student_and_route(uow)
        await service.assign_student_to_route(make_assign_command(), uow=uow)

        with self.assertRaises(ConflictError):
            await service.assign_student_to_route(make_assign_command(), uow=uow)


class StudentAssignmentStatusOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def _active_assignment_dto(
        self,
        service: StudentAssignmentApplicationService,
        uow: FakeTransportOpsUnitOfWork,
    ) -> StudentAssignmentDTO:
        seed_student_and_route(uow)
        return await service.assign_student_to_route(make_assign_command(), uow=uow)

    async def test_remove_transitions_status(self) -> None:
        service, uow = make_service()
        assignment = await self._active_assignment_dto(service, uow)
        dto = await service.remove_student_assignment(
            RemoveStudentAssignmentCommand(
                student_assignment_id=assignment.id, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(dto.status, "removed")
        self.assertIsNotNone(dto.ended_at)

    async def test_transfer_transitions_status(self) -> None:
        service, uow = make_service()
        assignment = await self._active_assignment_dto(service, uow)
        dto = await service.transfer_student_assignment(
            TransferStudentAssignmentCommand(
                student_assignment_id=assignment.id, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(dto.status, "transferred")

    async def test_graduate_transitions_status(self) -> None:
        service, uow = make_service()
        assignment = await self._active_assignment_dto(service, uow)
        dto = await service.graduate_student_assignment(
            GraduateStudentAssignmentCommand(
                student_assignment_id=assignment.id, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(dto.status, "graduated")

    async def test_disable_transitions_status(self) -> None:
        service, uow = make_service()
        assignment = await self._active_assignment_dto(service, uow)
        dto = await service.disable_student_assignment(
            DisableStudentAssignmentCommand(
                student_assignment_id=assignment.id, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(dto.status, "disabled")

    async def test_remove_with_nonexistent_id_raises_not_found_error(self) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.remove_student_assignment(
                RemoveStudentAssignmentCommand(
                    student_assignment_id=NON_EXISTENT_ASSIGNMENT_ID,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_reassigning_after_removal_succeeds(self) -> None:
        """Removing frees the one-active-assignment-per-student slot for a new assignment."""
        service, uow = make_service()
        assignment = await self._active_assignment_dto(service, uow)
        await service.remove_student_assignment(
            RemoveStudentAssignmentCommand(
                student_assignment_id=assignment.id, actor=make_actor()
            ),
            uow=uow,
        )
        second = await service.assign_student_to_route(make_assign_command(), uow=uow)
        self.assertEqual(second.status, "active")
        self.assertNotEqual(second.id, assignment.id)

    async def test_get_student_assignment_by_id_returns_dto(self) -> None:
        service, uow = make_service()
        assignment = await self._active_assignment_dto(service, uow)
        dto = await service.get_student_assignment_by_id(
            GetStudentAssignmentByIdQuery(student_assignment_id=assignment.id),
            uow=uow,
        )
        self.assertEqual(dto.id, assignment.id)

    async def test_get_student_assignment_by_id_with_nonexistent_id_raises_not_found(
        self,
    ) -> None:
        service, uow = make_service()
        with self.assertRaises(NotFoundError):
            await service.get_student_assignment_by_id(
                GetStudentAssignmentByIdQuery(
                    student_assignment_id=NON_EXISTENT_ASSIGNMENT_ID
                ),
                uow=uow,
            )

    async def test_list_student_assignments_returns_summary_dtos(self) -> None:
        service, uow = make_service()
        await self._active_assignment_dto(service, uow)
        page = await service.list_student_assignments(
            ListStudentAssignmentsQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(len(page.data), 1)
        self.assertIsInstance(page.data[0], StudentAssignmentSummaryDTO)


class StudentAssignmentApplicationServicePaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_student_assignments_paginates_and_reports_total(self) -> None:
        service, uow = make_service()
        seed_student_and_route(uow)
        await service.assign_student_to_route(make_assign_command(), uow=uow)
        await service.remove_student_assignment(
            RemoveStudentAssignmentCommand(
                student_assignment_id=(
                    await service.list_student_assignments(
                        ListStudentAssignmentsQuery(page_request=OffsetPageRequest()),
                        uow=uow,
                    )
                ).data[0].id,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.assign_student_to_route(make_assign_command(), uow=uow)

        page = await service.list_student_assignments(
            ListStudentAssignmentsQuery(page_request=OffsetPageRequest(page=1, page_size=1)),
            uow=uow,
        )
        self.assertEqual(page.total, 2)
        self.assertEqual(page.page, 1)
        self.assertEqual(page.page_size, 1)
        self.assertEqual(len(page.data), 1)

        second_page = await service.list_student_assignments(
            ListStudentAssignmentsQuery(page_request=OffsetPageRequest(page=2, page_size=1)),
            uow=uow,
        )
        self.assertEqual(len(second_page.data), 1)

    async def test_list_student_assignments_filters_by_status(self) -> None:
        service, uow = make_service()
        seed_student_and_route(uow)
        active = await service.assign_student_to_route(make_assign_command(), uow=uow)
        await service.remove_student_assignment(
            RemoveStudentAssignmentCommand(
                student_assignment_id=active.id, actor=make_actor()
            ),
            uow=uow,
        )

        page = await service.list_student_assignments(
            ListStudentAssignmentsQuery(
                page_request=OffsetPageRequest(),
                filters=[FilterCondition(field="status", op="eq", value="removed")],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].id, active.id)
        self.assertEqual(page.data[0].status, "removed")

    async def test_list_student_assignments_sorts_by_status(self) -> None:
        service, uow = make_service()
        seed_student_and_route(uow)
        first = await service.assign_student_to_route(make_assign_command(), uow=uow)
        await service.remove_student_assignment(
            RemoveStudentAssignmentCommand(
                student_assignment_id=first.id, actor=make_actor()
            ),
            uow=uow,
        )
        second = await service.assign_student_to_route(make_assign_command(), uow=uow)

        page = await service.list_student_assignments(
            ListStudentAssignmentsQuery(
                page_request=OffsetPageRequest(),
                sort=[SortSpec(field="status", descending=False)],
            ),
            uow=uow,
        )
        # "active" < "removed" alphabetically - ascending sort puts the active one first.
        self.assertEqual([dto.status for dto in page.data], ["active", "removed"])
        self.assertEqual(page.data[0].id, second.id)


if __name__ == "__main__":
    unittest.main()
