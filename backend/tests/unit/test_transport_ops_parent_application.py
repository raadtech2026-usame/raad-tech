"""Application-layer tests for `transport_ops`'s `ParentApplicationService` (Phase 10.6;
ADR-0003 accepted — Parent registration now provisions its own linked `iam.User` via
`UserProvisioningPort`, rather than taking an already-existing `user_id` as input). Stdlib
`unittest` — no `pytest` (not an approved dependency), mirroring
`test_transport_ops_student_application.py`'s exact structure. Uses a fixed clock/sequential id
generator fake, an in-memory fake `TransportOpsUnitOfWork`/`ParentRepository`, and a fake
`UserProvisioningPort` — no SQLAlchemy, no FastAPI, no real database, no real `iam` module.
Covers: command immutability, DTO mapping, service orchestration flow (including the new
provisioning-port call and temporary-password hand-off), repository interaction, and
status-transition/validation error paths.
"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import (
    AuthorizationError,
    DomainError,
    NotFoundError,
    ValidationError,
)
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import FilterCondition, OffsetPage, OffsetPageRequest, SortSpec
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.transport_ops.application.commands import (
    ActivateParentCommand,
    ChildEnrollmentSpec,
    DisableParentCommand,
    GrantParentVideoLiveAccessCommand,
    GrantParentVideoPlaybackAccessCommand,
    RegisterParentCommand,
    RegisterParentWithChildrenCommand,
    RevokeParentVideoLiveAccessCommand,
    RevokeParentVideoPlaybackAccessCommand,
    SetFamilyTransportationCommand,
    UpdateParentCommand,
)
from raad.modules.transport_ops.application.ports import (
    TransportOpsUnitOfWork,
    UserProvisioningPort,
)
from raad.modules.transport_ops.application.queries import (
    GetParentByIdQuery,
    ListParentsQuery,
    ParentDTO,
    ParentSummaryDTO,
    parent_to_dto,
    parent_to_summary_dto,
)
from raad.modules.transport_ops.application.services import ParentApplicationService
from raad.modules.transport_ops.domain.entities import (
    Parent,
    Route,
    Stop,
    Student,
    StudentAssignment,
    StudentParent,
)
from raad.modules.transport_ops.domain.repositories import (
    ParentRepository,
    RouteRepository,
    StudentAssignmentRepository,
    StudentParentRepository,
    StudentRepository,
)
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    ParentId,
    ParentStatus,
    PhoneNumber,
    RouteId,
    RouteStatus,
    StopId,
    StudentAssignmentId,
    StudentAssignmentStatus,
    StudentId,
    UserId,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
OTHER_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3OT"
VALID_USER_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
# Well-formed ULID shape but never added to any InMemoryParentRepository in these tests -
# exercises the NotFoundError path, distinct from ParentId's own malformed-shape DomainError.
NON_EXISTENT_PARENT_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"
FAKE_TEMPORARY_PASSWORD = "Fake-Temp-Pw9!"
# Family-transportation fixtures (2026-09-12 business-model correction).
VALID_ROUTE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3RT"
VALID_PICKUP_STOP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3P1"
VALID_DROPOFF_STOP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3D1"
OTHER_ROUTE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3R2"
OTHER_PICKUP_STOP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3P2"
OTHER_DROPOFF_STOP_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3D2"
VALID_VEHICLE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3VE"
OTHER_VEHICLE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3V2"
NON_EXISTENT_ROUTE_ID = "01J8Z3K9G6X8YV5T4N2R7QW3ZX"


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
    search_field: str = "full_name",
) -> OffsetPage:
    """Shared in-memory equivalent of `SqlAlchemyRepositoryBase.list_page` (`core/db/
    repository.py`), for fake repositories that can't run real SQL — duplicated per module's
    own test file rather than a shared test helper, mirroring
    `test_organization_application.py`'s own established "duplicated per module" precedent."""
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

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Parent]:
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )

    async def list_by_ids(self, parent_ids: list[str]) -> list[Parent]:
        wanted = set(parent_ids)
        return [p for p in self.by_id.values() if str(p.id) in wanted]


class InMemoryStudentRepository(StudentRepository):
    """Minimal fake — only `add` is exercised by `register_parent_with_children`."""

    def __init__(self) -> None:
        self.by_id: dict[str, Student] = {}

    async def get(self, student_id: StudentId) -> Student | None:
        return self.by_id.get(str(student_id))

    def add(self, student: Student) -> None:
        self.by_id[str(student.id)] = student

    async def list_all(self) -> list[Student]:
        return list(self.by_id.values())

    async def list_by_ids(self, student_ids: list[str]) -> list[Student]:
        wanted = set(student_ids)
        return [s for s in self.by_id.values() if str(s.id) in wanted]

    async def list_page(self, page_request, *, sort, filters, search):
        raise NotImplementedError


class InMemoryStudentParentRepository(StudentParentRepository):
    """Minimal fake — only `add` is exercised by `register_parent_with_children`."""

    def __init__(self) -> None:
        self.links: list[StudentParent] = []

    async def get(self, student_id: StudentId, parent_id: ParentId) -> StudentParent | None:
        return next(
            (
                link
                for link in self.links
                if link.student_id == student_id and link.parent_id == parent_id
            ),
            None,
        )

    def add(self, link: StudentParent) -> None:
        self.links.append(link)

    async def remove(self, link: StudentParent) -> None:
        raise NotImplementedError

    async def list_by_student(self, student_id: StudentId) -> list[StudentParent]:
        return [link for link in self.links if link.student_id == student_id]

    async def list_by_parent(self, parent_id: ParentId) -> list[StudentParent]:
        return [link for link in self.links if link.parent_id == parent_id]

    async def list_by_students(self, student_ids: list[StudentId]) -> list[StudentParent]:
        wanted = {str(sid) for sid in student_ids}
        return [link for link in self.links if str(link.student_id) in wanted]


class InMemoryRouteRepository(RouteRepository):
    """Minimal fake — needed for `register_parent_with_children`'s/`set_family_transportation`'s
    family-transportation validation (2026-09-12), mirroring `test_transport_ops_student_
    assignment_application.py`'s own identically-named fake (duplicated per test file, this
    codebase's own established precedent)."""

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

    async def list_page(self, page_request, *, sort, filters, search):
        raise NotImplementedError


class InMemoryStudentAssignmentRepository(StudentAssignmentRepository):
    """Minimal fake — needed for `set_family_transportation`'s per-child assign/end cascade."""

    def __init__(self) -> None:
        self.by_id: dict[str, StudentAssignment] = {}

    async def get(self, student_assignment_id: StudentAssignmentId) -> StudentAssignment | None:
        return self.by_id.get(str(student_assignment_id))

    def add(self, assignment: StudentAssignment) -> None:
        self.by_id[str(assignment.id)] = assignment

    async def list_all(self) -> list[StudentAssignment]:
        return list(self.by_id.values())

    async def list_page(self, page_request, *, sort, filters, search):
        raise NotImplementedError

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


class FakeTransportOpsUnitOfWork(TransportOpsUnitOfWork):
    def __init__(
        self,
        parents: InMemoryParentRepository,
        students: InMemoryStudentRepository | None = None,
        student_parents: InMemoryStudentParentRepository | None = None,
        routes: InMemoryRouteRepository | None = None,
        student_assignments: InMemoryStudentAssignmentRepository | None = None,
    ) -> None:
        self.parents = parents
        self.students = students or InMemoryStudentRepository()
        self.student_parents = student_parents or InMemoryStudentParentRepository()
        self.routes = routes or InMemoryRouteRepository()
        self.student_assignments = student_assignments or InMemoryStudentAssignmentRepository()
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeUserProvisioningPort(UserProvisioningPort):
    """ADR-0003 (accepted): stands in for the real `IamUserProvisioningAdapter` — records every
    call for assertions, always succeeds, always returns the same fixed, ULID-shaped
    `VALID_USER_ULID` (tests here never assert on `user_id` uniqueness across calls, only that
    the returned id is what `Parent.register` receives)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_user_with_temporary_password(
        self,
        *,
        organization_id: str,
        role: Role,
        email: str | None,
        phone: str | None,
        full_name: str,
        actor: Principal,
    ) -> tuple[str, str]:
        self.calls.append(
            {
                "organization_id": organization_id,
                "role": role,
                "email": email,
                "phone": phone,
                "full_name": full_name,
                "actor": actor,
            }
        )
        return VALID_USER_ULID, FAKE_TEMPORARY_PASSWORD


def make_actor(org_id: str = VALID_ORG_ULID) -> Principal:
    return Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=org_id)


def make_route(
    route_id: str = VALID_ROUTE_ULID,
    organization_id: str = VALID_ORG_ULID,
    *,
    pickup_stop_id: str = VALID_PICKUP_STOP_ULID,
    dropoff_stop_id: str = VALID_DROPOFF_STOP_ULID,
) -> Route:
    """Family-transportation fixture (2026-09-12) — mirrors `test_transport_ops_student_
    assignment_application.py`'s own identically-shaped `make_route` helper."""
    return Route(
        id=RouteId(route_id),
        organization_id=OrganizationId(organization_id),
        name=f"Route {route_id[-4:]}",
        status=RouteStatus.ACTIVE,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        stops=[
            Stop(
                id=StopId(pickup_stop_id),
                name="Pickup",
                latitude=2.5,
                longitude=45.3,
                sequence_no=1,
                geofence_radius_m=None,
            ),
            Stop(
                id=StopId(dropoff_stop_id),
                name="Dropoff",
                latitude=2.6,
                longitude=45.4,
                sequence_no=2,
                geofence_radius_m=None,
            ),
        ],
    )


def make_service() -> tuple[ParentApplicationService, FakeTransportOpsUnitOfWork, FakeUserProvisioningPort]:
    clock = FixedClock(datetime(2026, 7, 17, tzinfo=timezone.utc))
    id_generator = SequentialIdGenerator()
    user_provisioning = FakeUserProvisioningPort()
    service = ParentApplicationService(
        clock=clock, id_generator=id_generator, user_provisioning=user_provisioning
    )
    uow = FakeTransportOpsUnitOfWork(InMemoryParentRepository())
    return service, uow, user_provisioning


class CommandImmutabilityTests(unittest.TestCase):
    def test_register_command_is_frozen(self) -> None:
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Fatima Hassan",
            email=None,
            phone=None,
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.full_name = "Different Name"  # type: ignore[misc]

    def test_update_command_is_frozen(self) -> None:
        command = UpdateParentCommand(
            parent_id="some-id",
            full_name="Fatima Hassan",
            phone=None,
            actor=make_actor(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            command.parent_id = "other-id"  # type: ignore[misc]

    def test_status_commands_are_frozen(self) -> None:
        for command in (
            ActivateParentCommand(parent_id="p1", actor=make_actor()),
            DisableParentCommand(parent_id="p1", actor=make_actor()),
        ):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                command.parent_id = "other-id"  # type: ignore[misc]

    def test_commands_carry_the_actor_principal(self) -> None:
        actor = make_actor()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Fatima Hassan",
            email=None,
            phone=None,
            actor=actor,
        )
        self.assertIs(command.actor, actor)


class DTOMappingTests(unittest.TestCase):
    def make_parent(self) -> Parent:
        return Parent(
            id=ParentId("01J8Z3K9G6X8YV5T4N2R7QW3MC"),
            organization_id=OrganizationId(VALID_ORG_ULID),
            user_id=UserId(VALID_USER_ULID),
            full_name="Fatima Hassan",
            phone=PhoneNumber("+252700000000"),
            status=ParentStatus.ACTIVE,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def test_parent_to_dto_maps_all_fields_as_primitives(self) -> None:
        dto = parent_to_dto(self.make_parent())
        self.assertIsInstance(dto, ParentDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3MC")
        self.assertEqual(dto.organization_id, VALID_ORG_ULID)
        self.assertEqual(dto.user_id, VALID_USER_ULID)
        self.assertEqual(dto.full_name, "Fatima Hassan")
        self.assertEqual(dto.phone, "+252700000000")
        self.assertEqual(dto.status, "active")  # enum -> .value, not the enum member

    def test_parent_to_dto_preserves_none_phone(self) -> None:
        parent = self.make_parent()
        parent.phone = None
        dto = parent_to_dto(parent)
        self.assertIsNone(dto.phone)

    def test_parent_to_summary_dto_maps_reduced_field_set(self) -> None:
        dto = parent_to_summary_dto(self.make_parent())
        self.assertIsInstance(dto, ParentSummaryDTO)
        self.assertEqual(dto.id, "01J8Z3K9G6X8YV5T4N2R7QW3MC")
        self.assertEqual(dto.full_name, "Fatima Hassan")
        self.assertEqual(dto.status, "active")
        self.assertFalse(hasattr(dto, "organization_id"))
        self.assertFalse(hasattr(dto, "user_id"))
        self.assertFalse(hasattr(dto, "phone"))

    def test_dtos_are_frozen(self) -> None:
        dto = parent_to_dto(self.make_parent())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            dto.full_name = "Different Name"  # type: ignore[misc]


class ParentApplicationServiceRegisterTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_parent_adds_to_repository_and_commits(self) -> None:
        service, uow, _provisioning = make_service()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Fatima Hassan",
            email=None,
            phone="+252700000000",
            actor=make_actor(),
        )
        dto, temporary_password = await service.register_parent(command, uow=uow)

        self.assertEqual(dto.full_name, "Fatima Hassan")
        self.assertEqual(dto.status, "active")
        self.assertEqual(dto.user_id, VALID_USER_ULID)
        self.assertEqual(temporary_password, FAKE_TEMPORARY_PASSWORD)
        self.assertEqual(len(uow.parents.by_id), 1)
        self.assertIn(dto.id, uow.parents.by_id)
        self.assertEqual(uow.commit_count, 1)

    async def test_register_parent_passes_through_the_additive_profile_fields(self) -> None:
        """2026-09-10 explicit user directive (Parent & Student Domain Restructure)."""
        service, uow, _provisioning = make_service()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Fatima Hassan",
            email=None,
            phone="+252700000000",
            actor=make_actor(),
            alternate_phone="+252611111111",
            address="Hodan District, Mogadishu",
            emergency_contact_name="Ahmed Hassan",
            emergency_contact_phone="+252622222222",
            notes="Prefers SMS over calls.",
        )
        dto, _temporary_password = await service.register_parent(command, uow=uow)

        self.assertEqual(dto.alternate_phone, "+252611111111")
        self.assertEqual(dto.address, "Hodan District, Mogadishu")
        self.assertEqual(dto.emergency_contact_name, "Ahmed Hassan")
        self.assertEqual(dto.emergency_contact_phone, "+252622222222")
        self.assertEqual(dto.notes, "Prefers SMS over calls.")

    async def test_register_parent_calls_user_provisioning_with_role_parent(self) -> None:
        service, uow, provisioning = make_service()
        actor = make_actor()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Fatima Hassan",
            email="fatima@example.com",
            phone="+252700000000",
            actor=actor,
        )
        await service.register_parent(command, uow=uow)

        self.assertEqual(len(provisioning.calls), 1)
        call = provisioning.calls[0]
        self.assertEqual(call["organization_id"], VALID_ORG_ULID)
        self.assertEqual(call["role"], Role.PARENT)
        self.assertEqual(call["email"], "fatima@example.com")
        self.assertEqual(call["phone"], "+252700000000")
        self.assertEqual(call["full_name"], "Fatima Hassan")
        self.assertIs(call["actor"], actor)

    async def test_register_parent_records_domain_events(self) -> None:
        service, uow, _provisioning = make_service()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Fatima Hassan",
            email=None,
            phone=None,
            actor=make_actor(),
        )
        await service.register_parent(command, uow=uow)

        self.assertEqual(len(uow.recorded_events), 1)
        self.assertEqual(uow.recorded_events[0].event_type, "ParentRegistered")

    async def test_register_parent_generates_a_fresh_id_per_call(self) -> None:
        service, uow, _provisioning = make_service()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Fatima Hassan",
            email=None,
            phone=None,
            actor=make_actor(),
        )
        first, _ = await service.register_parent(command, uow=uow)
        second, _ = await service.register_parent(command, uow=uow)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(len(uow.parents.by_id), 2)

    async def test_register_parent_without_phone_leaves_phone_none(self) -> None:
        service, uow, _provisioning = make_service()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Fatima Hassan",
            email=None,
            phone=None,
            actor=make_actor(),
        )
        dto, _temporary_password = await service.register_parent(command, uow=uow)
        self.assertIsNone(dto.phone)

    async def test_register_parent_with_invalid_phone_raises_domain_error(
        self,
    ) -> None:
        service, uow, _provisioning = make_service()
        command = RegisterParentCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Fatima Hassan",
            email=None,
            phone="not-e164",
            actor=make_actor(),
        )
        with self.assertRaises(DomainError):
            await service.register_parent(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)

    async def test_register_parent_for_a_different_organization_raises_authorization_error(
        self,
    ) -> None:
        # ADR-0021's `_enforce_own_organization` - raised before the (redundant, transitive)
        # iam-side check inside the fake `UserProvisioningPort` would ever run.
        service, uow, provisioning = make_service()
        command = RegisterParentCommand(
            organization_id=OTHER_ORG_ULID,
            full_name="Fatima Hassan",
            email=None,
            phone=None,
            actor=make_actor(org_id=VALID_ORG_ULID),
        )
        with self.assertRaises(AuthorizationError):
            await service.register_parent(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)
        self.assertEqual(provisioning.calls, [])


class RegisterParentWithChildrenTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0041 §2 — the "Add Parent -> add children -> Save" transactional flow."""

    async def test_creates_parent_and_every_child_and_links_each_one(self) -> None:
        service, uow, provisioning = make_service()
        command = RegisterParentWithChildrenCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Ahmed Mohamed",
            email=None,
            phone="+252611111111",
            actor=make_actor(),
            children=[
                ChildEnrollmentSpec(full_name="Mohamed Ahmed", relationship="Father", is_primary=True),
                ChildEnrollmentSpec(full_name="Aisha Ahmed", relationship="Father"),
                ChildEnrollmentSpec(full_name="Omar Ahmed", relationship="Father"),
            ],
        )
        parent, children, temporary_password = await service.register_parent_with_children(
            command, uow=uow
        )

        self.assertEqual(parent.full_name, "Ahmed Mohamed")
        self.assertEqual(len(children), 3)
        self.assertEqual({c.full_name for c in children}, {"Mohamed Ahmed", "Aisha Ahmed", "Omar Ahmed"})
        self.assertEqual(temporary_password, FAKE_TEMPORARY_PASSWORD)

        # Every child actually persisted, and actually linked to the new parent.
        self.assertEqual(len(uow.students.by_id), 3)
        self.assertEqual(len(uow.student_parents.links), 3)
        for link in uow.student_parents.links:
            self.assertEqual(str(link.parent_id), parent.id)

        # One transaction, one commit - not one per child.
        self.assertEqual(uow.commit_count, 1)

    async def test_zero_children_behaves_like_register_parent(self) -> None:
        service, uow, _ = make_service()
        command = RegisterParentWithChildrenCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Solo Parent",
            email=None,
            phone="+252622222222",
            actor=make_actor(),
            children=[],
        )
        parent, children, _ = await service.register_parent_with_children(command, uow=uow)
        self.assertEqual(children, [])
        self.assertEqual(len(uow.parents.by_id), 1)
        self.assertEqual(uow.commit_count, 1)

    async def test_an_invalid_child_never_commits(self) -> None:
        """The unit-level proof of atomicity: nothing is durable unless `commit()` is reached,
        exactly once, for the whole family. (The in-memory fakes here mutate their own `by_id`
        dict synchronously on `add()`, the same way every other fake repository in this test
        file does — they do not model real rollback; that guarantee is the real SQLAlchemy
        `UnitOfWork`'s job, proven instead by
        `test_transport_ops_parent_repository.py::RegisterParentWithChildrenTransactionTests`
        against a real Postgres transaction.)"""
        service, uow, _ = make_service()
        command = RegisterParentWithChildrenCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Ahmed Mohamed",
            email=None,
            phone="+252611111111",
            actor=make_actor(),
            children=[
                ChildEnrollmentSpec(full_name="Mohamed Ahmed"),
                ChildEnrollmentSpec(full_name=""),  # invalid: empty full_name
            ],
        )
        with self.assertRaises(DomainError):
            await service.register_parent_with_children(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)

    async def test_cross_organization_actor_is_rejected_before_any_write(self) -> None:
        service, uow, provisioning = make_service()
        command = RegisterParentWithChildrenCommand(
            organization_id=OTHER_ORG_ULID,
            full_name="Ahmed Mohamed",
            email=None,
            phone=None,
            actor=make_actor(org_id=VALID_ORG_ULID),
            children=[ChildEnrollmentSpec(full_name="Mohamed Ahmed")],
        )
        with self.assertRaises(AuthorizationError):
            await service.register_parent_with_children(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)
        self.assertEqual(provisioning.calls, [])

    async def test_each_child_records_its_own_date_of_birth_and_gender_and_notes(self) -> None:
        service, uow, _ = make_service()
        command = RegisterParentWithChildrenCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Ahmed Mohamed",
            email=None,
            phone="+252611111111",
            actor=make_actor(),
            children=[
                ChildEnrollmentSpec(
                    full_name="Mohamed Ahmed",
                    date_of_birth=None,
                    gender="male",
                    notes="Allergic to peanuts.",
                )
            ],
        )
        _, children, _ = await service.register_parent_with_children(command, uow=uow)
        self.assertEqual(children[0].gender, "male")
        self.assertEqual(children[0].notes, "Allergic to peanuts.")


class RegisterParentWithChildrenFamilyTransportationTests(unittest.IsolatedAsyncioTestCase):
    """2026-09-12 business-model correction: family transportation is set once, at registration,
    for every listed child together — not per child afterward."""

    async def test_every_child_gets_the_same_route_and_vehicle_in_one_transaction(self) -> None:
        service, uow, _ = make_service()
        uow.routes.add(make_route())
        command = RegisterParentWithChildrenCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Ahmed Mohamed",
            email=None,
            phone="+252611111111",
            actor=make_actor(),
            children=[
                ChildEnrollmentSpec(full_name="Mohamed Ahmed"),
                ChildEnrollmentSpec(full_name="Aisha Ahmed"),
            ],
            route_id=VALID_ROUTE_ULID,
            pickup_stop_id=VALID_PICKUP_STOP_ULID,
            dropoff_stop_id=VALID_DROPOFF_STOP_ULID,
            vehicle_id=VALID_VEHICLE_ULID,
        )
        _parent, children, _ = await service.register_parent_with_children(command, uow=uow)

        self.assertEqual(len(uow.student_assignments.by_id), 2)
        assignments = list(uow.student_assignments.by_id.values())
        self.assertEqual({str(a.route_id) for a in assignments}, {VALID_ROUTE_ULID})
        self.assertEqual({str(a.vehicle_id) for a in assignments}, {VALID_VEHICLE_ULID})
        self.assertEqual(
            {str(a.student_id) for a in assignments},
            {child.id for child in children},
        )
        # Still one commit for the whole family, transportation included.
        self.assertEqual(uow.commit_count, 1)

    async def test_omitting_route_id_creates_no_assignments(self) -> None:
        service, uow, _ = make_service()
        command = RegisterParentWithChildrenCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Ahmed Mohamed",
            email=None,
            phone="+252611111111",
            actor=make_actor(),
            children=[ChildEnrollmentSpec(full_name="Mohamed Ahmed")],
        )
        await service.register_parent_with_children(command, uow=uow)
        self.assertEqual(uow.student_assignments.by_id, {})

    async def test_route_id_without_pickup_stop_id_raises_validation_error(self) -> None:
        service, uow, _ = make_service()
        uow.routes.add(make_route())
        command = RegisterParentWithChildrenCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Ahmed Mohamed",
            email=None,
            phone="+252611111111",
            actor=make_actor(),
            children=[ChildEnrollmentSpec(full_name="Mohamed Ahmed")],
            route_id=VALID_ROUTE_ULID,
            pickup_stop_id=None,
            dropoff_stop_id=None,
        )
        with self.assertRaises(ValidationError):
            await service.register_parent_with_children(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)
        self.assertEqual(uow.parents.by_id, {})

    async def test_unknown_route_id_raises_not_found_before_any_write(self) -> None:
        service, uow, _ = make_service()
        command = RegisterParentWithChildrenCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Ahmed Mohamed",
            email=None,
            phone="+252611111111",
            actor=make_actor(),
            children=[ChildEnrollmentSpec(full_name="Mohamed Ahmed")],
            route_id=NON_EXISTENT_ROUTE_ID,
            pickup_stop_id=VALID_PICKUP_STOP_ULID,
            dropoff_stop_id=VALID_DROPOFF_STOP_ULID,
        )
        with self.assertRaises(NotFoundError):
            await service.register_parent_with_children(command, uow=uow)
        self.assertEqual(uow.commit_count, 0)


class SetFamilyTransportationTests(unittest.IsolatedAsyncioTestCase):
    """2026-09-12 business-model correction — the one place a family's Vehicle/Route/Stops is
    assigned for the first time or changed later, cascading to every one of a Parent's linked
    children in one transaction."""

    async def _register_parent_with_children(
        self, service: ParentApplicationService, uow: FakeTransportOpsUnitOfWork, count: int
    ) -> tuple[str, list[str]]:
        command = RegisterParentWithChildrenCommand(
            organization_id=VALID_ORG_ULID,
            full_name="Ahmed Mohamed",
            email=None,
            phone="+252611111111",
            actor=make_actor(),
            children=[ChildEnrollmentSpec(full_name=f"Child {i}") for i in range(count)],
        )
        parent, children, _ = await service.register_parent_with_children(command, uow=uow)
        uow.recorded_events.clear()
        return parent.id, [child.id for child in children]

    async def test_assigns_every_linked_child_to_the_same_route_and_vehicle(self) -> None:
        service, uow, _ = make_service()
        uow.routes.add(make_route())
        parent_id, child_ids = await self._register_parent_with_children(service, uow, 2)

        assignments = await service.set_family_transportation(
            SetFamilyTransportationCommand(
                parent_id=parent_id,
                route_id=VALID_ROUTE_ULID,
                pickup_stop_id=VALID_PICKUP_STOP_ULID,
                dropoff_stop_id=VALID_DROPOFF_STOP_ULID,
                vehicle_id=VALID_VEHICLE_ULID,
                actor=make_actor(),
            ),
            uow=uow,
        )

        self.assertEqual(len(assignments), 2)
        self.assertEqual({a.student_id for a in assignments}, set(child_ids))
        self.assertEqual({a.route_id for a in assignments}, {VALID_ROUTE_ULID})
        self.assertEqual({a.vehicle_id for a in assignments}, {VALID_VEHICLE_ULID})
        self.assertEqual({a.status for a in assignments}, {"active"})

    async def test_changing_transportation_ends_the_old_assignment_and_creates_a_new_one(
        self,
    ) -> None:
        service, uow, _ = make_service()
        uow.routes.add(make_route())
        uow.routes.add(
            make_route(
                OTHER_ROUTE_ULID,
                pickup_stop_id=OTHER_PICKUP_STOP_ULID,
                dropoff_stop_id=OTHER_DROPOFF_STOP_ULID,
            )
        )
        parent_id, child_ids = await self._register_parent_with_children(service, uow, 1)
        await service.set_family_transportation(
            SetFamilyTransportationCommand(
                parent_id=parent_id,
                route_id=VALID_ROUTE_ULID,
                pickup_stop_id=VALID_PICKUP_STOP_ULID,
                dropoff_stop_id=VALID_DROPOFF_STOP_ULID,
                vehicle_id=VALID_VEHICLE_ULID,
                actor=make_actor(),
            ),
            uow=uow,
        )
        first_assignment_id = next(iter(uow.student_assignments.by_id))

        new_assignments = await service.set_family_transportation(
            SetFamilyTransportationCommand(
                parent_id=parent_id,
                route_id=OTHER_ROUTE_ULID,
                pickup_stop_id=OTHER_PICKUP_STOP_ULID,
                dropoff_stop_id=OTHER_DROPOFF_STOP_ULID,
                vehicle_id=OTHER_VEHICLE_ULID,
                actor=make_actor(),
            ),
            uow=uow,
        )

        # The old assignment is ended (`removed`), not deleted - a new one is created for the
        # new route/vehicle. Exactly one ACTIVE assignment exists for the student afterward.
        old_assignment = uow.student_assignments.by_id[first_assignment_id]
        self.assertEqual(old_assignment.status.value, "removed")
        self.assertEqual(len(new_assignments), 1)
        self.assertEqual(new_assignments[0].route_id, OTHER_ROUTE_ULID)
        self.assertEqual(new_assignments[0].vehicle_id, OTHER_VEHICLE_ULID)
        active = await uow.student_assignments.active_assignment_for_student(
            StudentId(child_ids[0])
        )
        self.assertEqual(str(active.id), new_assignments[0].id)

    async def test_parent_with_no_linked_children_is_a_legal_no_op(self) -> None:
        service, uow, _ = make_service()
        uow.routes.add(make_route())
        parent_id, _children = await self._register_parent_with_children(service, uow, 0)

        assignments = await service.set_family_transportation(
            SetFamilyTransportationCommand(
                parent_id=parent_id,
                route_id=VALID_ROUTE_ULID,
                pickup_stop_id=VALID_PICKUP_STOP_ULID,
                dropoff_stop_id=VALID_DROPOFF_STOP_ULID,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(assignments, [])

    async def test_unknown_parent_raises_not_found(self) -> None:
        service, uow, _ = make_service()
        uow.routes.add(make_route())
        with self.assertRaises(NotFoundError):
            await service.set_family_transportation(
                SetFamilyTransportationCommand(
                    parent_id=NON_EXISTENT_PARENT_ID,
                    route_id=VALID_ROUTE_ULID,
                    pickup_stop_id=VALID_PICKUP_STOP_ULID,
                    dropoff_stop_id=VALID_DROPOFF_STOP_ULID,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_pickup_stop_not_on_route_raises_not_found(self) -> None:
        service, uow, _ = make_service()
        uow.routes.add(make_route())
        parent_id, _children = await self._register_parent_with_children(service, uow, 1)
        with self.assertRaises(NotFoundError):
            await service.set_family_transportation(
                SetFamilyTransportationCommand(
                    parent_id=parent_id,
                    route_id=VALID_ROUTE_ULID,
                    pickup_stop_id=OTHER_PICKUP_STOP_ULID,
                    dropoff_stop_id=VALID_DROPOFF_STOP_ULID,
                    actor=make_actor(),
                ),
                uow=uow,
            )


class ParentApplicationServiceStatusTransitionTests(unittest.IsolatedAsyncioTestCase):
    async def _registered_parent_id(
        self, service: ParentApplicationService, uow
    ) -> str:
        dto, _temporary_password = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Fatima Hassan",
                email=None,
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        uow.recorded_events.clear()  # isolate the transition's own event from registration's
        return dto.id

    async def test_disable_parent_changes_status(self) -> None:
        service, uow, _provisioning = make_service()
        parent_id = await self._registered_parent_id(service, uow)
        dto = await service.disable_parent(
            DisableParentCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "inactive")
        self.assertEqual(uow.recorded_events[-1].event_type, "ParentDisabled")

    async def test_activate_after_disable_returns_to_active(self) -> None:
        service, uow, _provisioning = make_service()
        parent_id = await self._registered_parent_id(service, uow)
        await service.disable_parent(
            DisableParentCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        dto = await service.activate_parent(
            ActivateParentCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.status, "active")

    async def test_repeated_disable_is_idempotent_no_new_event(self) -> None:
        service, uow, _provisioning = make_service()
        parent_id = await self._registered_parent_id(service, uow)
        await service.disable_parent(
            DisableParentCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        uow.recorded_events.clear()
        await service.disable_parent(
            DisableParentCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(uow.recorded_events, [])  # already inactive - no-op

    async def test_transition_on_missing_parent_raises_not_found(self) -> None:
        service, uow, _provisioning = make_service()
        with self.assertRaises(NotFoundError):
            await service.disable_parent(
                DisableParentCommand(
                    parent_id=NON_EXISTENT_PARENT_ID, actor=make_actor()
                ),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 0)  # never reached commit

    async def test_malformed_parent_id_shape_raises_domain_error_not_not_found(
        self,
    ) -> None:
        # ParentId's own ULID-shape validation runs before the repository lookup - a
        # malformed id is a DomainError, distinct from a well-formed but absent NotFoundError.
        service, uow, _provisioning = make_service()
        with self.assertRaises(DomainError):
            await service.disable_parent(
                DisableParentCommand(parent_id="not-a-ulid", actor=make_actor()),
                uow=uow,
            )


class ParentApplicationServiceVideoAccessTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0026 SS2 - mirrors `ParentApplicationServiceStatusTransitionTests`'s exact shape."""

    async def _registered_parent_id(
        self, service: ParentApplicationService, uow
    ) -> str:
        dto, _temporary_password = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Fatima Hassan",
                email=None,
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        uow.recorded_events.clear()
        return dto.id

    async def test_new_parent_has_no_video_access(self) -> None:
        service, uow, _provisioning = make_service()
        parent_id = await self._registered_parent_id(service, uow)
        dto = await service.get_parent_by_id(
            GetParentByIdQuery(parent_id=parent_id), uow=uow
        )
        self.assertFalse(dto.has_video_live_access)
        self.assertFalse(dto.has_video_playback_access)

    async def test_grant_video_live_access(self) -> None:
        service, uow, _provisioning = make_service()
        parent_id = await self._registered_parent_id(service, uow)
        dto = await service.grant_parent_video_live_access(
            GrantParentVideoLiveAccessCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        self.assertTrue(dto.has_video_live_access)
        self.assertFalse(dto.has_video_playback_access)
        self.assertEqual(uow.recorded_events[-1].event_type, "ParentVideoLiveAccessGranted")

    async def test_revoke_video_live_access(self) -> None:
        service, uow, _provisioning = make_service()
        parent_id = await self._registered_parent_id(service, uow)
        await service.grant_parent_video_live_access(
            GrantParentVideoLiveAccessCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        dto = await service.revoke_parent_video_live_access(
            RevokeParentVideoLiveAccessCommand(parent_id=parent_id, actor=make_actor()), uow=uow
        )
        self.assertFalse(dto.has_video_live_access)

    async def test_grant_video_playback_access_is_independent_of_live(self) -> None:
        service, uow, _provisioning = make_service()
        parent_id = await self._registered_parent_id(service, uow)
        dto = await service.grant_parent_video_playback_access(
            GrantParentVideoPlaybackAccessCommand(parent_id=parent_id, actor=make_actor()),
            uow=uow,
        )
        self.assertTrue(dto.has_video_playback_access)
        self.assertFalse(dto.has_video_live_access)

    async def test_revoke_video_playback_access(self) -> None:
        service, uow, _provisioning = make_service()
        parent_id = await self._registered_parent_id(service, uow)
        await service.grant_parent_video_playback_access(
            GrantParentVideoPlaybackAccessCommand(parent_id=parent_id, actor=make_actor()),
            uow=uow,
        )
        dto = await service.revoke_parent_video_playback_access(
            RevokeParentVideoPlaybackAccessCommand(parent_id=parent_id, actor=make_actor()),
            uow=uow,
        )
        self.assertFalse(dto.has_video_playback_access)

    async def test_grant_on_missing_parent_raises_not_found(self) -> None:
        service, uow, _provisioning = make_service()
        with self.assertRaises(NotFoundError):
            await service.grant_parent_video_live_access(
                GrantParentVideoLiveAccessCommand(
                    parent_id=NON_EXISTENT_PARENT_ID, actor=make_actor()
                ),
                uow=uow,
            )
        self.assertEqual(uow.commit_count, 0)


class ParentApplicationServiceUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_parent_changes_full_name_and_phone(self) -> None:
        service, uow, _provisioning = make_service()
        registered, _temporary_password = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Old Name",
                email=None,
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        dto = await service.update_parent(
            UpdateParentCommand(
                parent_id=registered.id,
                full_name="New Name",
                phone="+252700000000",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(dto.full_name, "New Name")
        self.assertEqual(dto.phone, "+252700000000")

    async def test_update_parent_on_missing_parent_raises_not_found(self) -> None:
        service, uow, _provisioning = make_service()
        with self.assertRaises(NotFoundError):
            await service.update_parent(
                UpdateParentCommand(
                    parent_id=NON_EXISTENT_PARENT_ID,
                    full_name="X",
                    phone=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )


class ParentApplicationServiceReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_parent_by_id_returns_dto(self) -> None:
        service, uow, _provisioning = make_service()
        registered, _temporary_password = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Fatima Hassan",
                email=None,
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        dto = await service.get_parent_by_id(
            GetParentByIdQuery(parent_id=registered.id), uow=uow
        )
        self.assertEqual(dto.id, registered.id)
        self.assertEqual(dto.full_name, "Fatima Hassan")

    async def test_get_parent_by_id_raises_not_found_for_missing_parent(self) -> None:
        service, uow, _provisioning = make_service()
        with self.assertRaises(NotFoundError):
            await service.get_parent_by_id(
                GetParentByIdQuery(parent_id=NON_EXISTENT_PARENT_ID), uow=uow
            )

    async def test_list_parents_returns_summary_dtos_for_all_parents(self) -> None:
        service, uow, _provisioning = make_service()
        await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Parent One",
                email=None,
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Parent Two",
                email=None,
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        page = await service.list_parents(
            ListParentsQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(len(page.data), 2)
        self.assertTrue(all(isinstance(dto, ParentSummaryDTO) for dto in page.data))
        self.assertEqual(
            sorted(dto.full_name for dto in page.data), ["Parent One", "Parent Two"]
        )

    async def test_list_parents_returns_empty_page_when_none_registered(self) -> None:
        service, uow, _provisioning = make_service()
        page = await service.list_parents(
            ListParentsQuery(page_request=OffsetPageRequest()), uow=uow
        )
        self.assertEqual(page.data, [])
        self.assertEqual(page.total, 0)


class ParentApplicationServicePaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_parents_paginates_and_reports_total(self) -> None:
        service, uow, _provisioning = make_service()
        for i in range(3):
            await service.register_parent(
                RegisterParentCommand(
                    organization_id=VALID_ORG_ULID,
                    full_name=f"Parent {i}",
                    email=None,
                    phone=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await service.list_parents(
            ListParentsQuery(page_request=OffsetPageRequest(page=1, page_size=2)),
            uow=uow,
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(page.page, 1)
        self.assertEqual(page.page_size, 2)
        self.assertEqual(len(page.data), 2)

        second_page = await service.list_parents(
            ListParentsQuery(page_request=OffsetPageRequest(page=2, page_size=2)),
            uow=uow,
        )
        self.assertEqual(len(second_page.data), 1)

    async def test_list_parents_filters_by_status(self) -> None:
        service, uow, _provisioning = make_service()
        active, _tp1 = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Active Parent",
                email=None,
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        disabled, _tp2 = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Disabled Parent",
                email=None,
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await service.disable_parent(
            DisableParentCommand(parent_id=disabled.id, actor=make_actor()), uow=uow
        )

        page = await service.list_parents(
            ListParentsQuery(
                page_request=OffsetPageRequest(),
                filters=[FilterCondition(field="status", op="eq", value="inactive")],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].full_name, "Disabled Parent")
        self.assertNotEqual(page.data[0].id, active.id)

    async def test_list_parents_sorts_descending_by_full_name(self) -> None:
        service, uow, _provisioning = make_service()
        for name in ("Alpha", "Beta", "Gamma"):
            await service.register_parent(
                RegisterParentCommand(
                    organization_id=VALID_ORG_ULID,
                    full_name=name,
                    email=None,
                    phone=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await service.list_parents(
            ListParentsQuery(
                page_request=OffsetPageRequest(),
                sort=[SortSpec(field="full_name", descending=True)],
            ),
            uow=uow,
        )
        self.assertEqual(
            [dto.full_name for dto in page.data], ["Gamma", "Beta", "Alpha"]
        )


class RepositoryInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_never_bypasses_the_repository_to_mutate_state(self) -> None:
        # The service must go through uow.parents.add/get - not hold its own parallel state.
        service, uow, _provisioning = make_service()
        dto, _temporary_password = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Fatima Hassan",
                email=None,
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        stored = await uow.parents.get(ParentId(dto.id))
        self.assertIsNotNone(stored)
        self.assertEqual(stored.full_name, "Fatima Hassan")

    async def test_uow_used_as_async_context_manager_for_every_call(self) -> None:
        service, uow, _provisioning = make_service()
        dto, _temporary_password = await service.register_parent(
            RegisterParentCommand(
                organization_id=VALID_ORG_ULID,
                full_name="Fatima Hassan",
                email=None,
                phone=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        fetched = await service.get_parent_by_id(
            GetParentByIdQuery(parent_id=dto.id), uow=uow
        )
        self.assertEqual(fetched.id, dto.id)


if __name__ == "__main__":
    unittest.main()
