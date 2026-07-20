"""SQLAlchemy repository implementations for `transport_ops` (Backend LLD §7, §8; Database
Design §6.2). Composes `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM ↔ domain conversion goes through `mappers.py` — the repository never
returns an ORM model, only the `Student` aggregate `modules/transport_ops/domain/repositories.py`
declares (§7.1's "aggregate-in/aggregate-out" rule).

**The identity-map problem this file solves** — identical to `iam.infra.repositories`'s and
`organization.infra.repositories`'s own docstrings: because `get()` returns a plain domain
object (not the tracked ORM row), a handler that does
`student = await uow.students.get(id); student.activate(...)` mutates only that detached domain
object — SQLAlchemy's session never sees the change, since it only dirty-tracks its own
`StudentModel` instances. The application layer never re-calls `add()` after such a mutation
(reserved for genuinely new aggregates, `application/services.py`), so this layer bridges the
gap: the repository keeps a `{id: (domain_object, orm_row)}` map of everything it has returned
or added, and `flush_tracked_changes()` re-projects every tracked domain object onto its row via
the mapper immediately before commit — called by `SqlAlchemyTransportOpsUnitOfWork.commit()`,
below.

**`list_all` is not yet tenant-scoped — flagged, not silently shipped as solved.** Phase 10.2's
`StudentRepository.list_all` interface deliberately takes no `organization_id` parameter,
since `.claude/rules/backend.md` #4 says tenant context should be "resolved once at the edge
... and injected into every repository query automatically." That edge resolution
(`core.tenancy.ScopeResolver` producing a `TenantRegionScope` per request) is not bound
anywhere in `core/di/bootstrap.py` yet for *any* module (its own docstring lists
`ScopeResolver` among the ports "bound here once their owning module/infra is implemented in a
later phase") — `iam.infra.repositories.SqlAlchemyUserRepository` notes the identical gap
("[tenant/region scoping] applies once a scoped listing use-case exists, via `list_scoped`"),
but `list_all` here *is* that first scoped-listing use-case, so the gap can no longer be
deferred by simply not implementing the method. Implemented via `list_scoped` (reusing the
existing soft-delete-aware filter mechanics rather than hand-rolling a duplicate query) with an
explicit unrestricted `TenantRegionScope` — functionally identical to no filtering, but written
so that swapping in a real per-request scope is a one-line change once `ScopeResolver` is wired
system-wide, rather than a rewrite. Wiring that resolver is out of this phase's scope (it is a
cross-cutting, all-modules concern, not a Student-specific one) and is not attempted here.

**Phase 10.7 addition: `SqlAlchemyStudentParentRepository`.** Cannot reuse `SqlAlchemyRepository
Base.get_by_id`/its identity-map keying — both assume a single `.id` column, and
`student_parents` has a composite primary key instead (`domain/repositories.py`'s Phase 10.7
docstring). `get`/`list_by_student`/`list_by_parent` therefore issue their own `select()`
statements directly rather than delegating to the base class's `get_by_id`, and the identity
map is keyed by the `(student_id, parent_id)` tuple. `remove()` is new too — `StudentParent`'s
only two lifecycle actions are a real INSERT (`add`) and a real DELETE (`remove`); there is no
in-place field-level UPDATE the way `Student`/`Parent` get via `flush_tracked_changes`, so this
repository defines no such method and `SqlAlchemyTransportOpsUnitOfWork.commit()` below calls
none for it.

**Phase 10.8 addition: `SqlAlchemyDriverRepository`.** Mirrors `SqlAlchemyParentRepository`'s
exact identity-map/`flush_tracked_changes`/`list_all` shape (single-column `.id` PK, same
unrestricted-`TenantRegionScope` caveat, pending the same system-wide `ScopeResolver` binding).

**Phase 11 addition: `SqlAlchemyRouteRepository`.** Mirrors `fleet_device.infra.repositories.
SqlAlchemyDeviceRepository`'s exact shape — `RouteModel.stops` rides the selectin-eager
relationship (`infra/models.py`), so a tracked `Route` re-projection
(`flush_tracked_changes` → `route_to_model`) also syncs the stop rows (add/update/remove, per
`infra/mappers.py`'s Phase 11 addition). `get_by_name` backs the per-tenant name-uniqueness
pre-check, mirroring `SqlAlchemyVehicleRepository.get_by_plate_no`'s identical shape.

**Phase 12 addition: `SqlAlchemyTripRepository`.** Mirrors `SqlAlchemyDriverRepository`'s exact
identity-map/`flush_tracked_changes` shape. `active_trip_for_vehicle`/`list_for_route` issue
their own direct `select()`s (`status = 'in_progress'` / `route_id = ...`, both
`deleted_at IS NULL`), mirroring `SqlAlchemyRouteRepository.get_by_name`'s shape for an
analogous non-`get_by_id` finder.

**Phase 13 addition: `SqlAlchemyStudentAssignmentRepository`.** Mirrors
`SqlAlchemyTripRepository`'s exact identity-map/`flush_tracked_changes` shape.
`active_assignment_for_student` issues its own direct `select()` (`status = 'active'`,
`deleted_at IS NULL`), mirroring `active_trip_for_vehicle`'s identical shape for an analogous
one-active-per-owner finder.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.domain.entities import (
    Driver,
    Parent,
    Route,
    Student,
    StudentAssignment,
    StudentParent,
    Trip,
)
from raad.modules.transport_ops.domain.repositories import (
    DriverRepository,
    ParentRepository,
    RouteRepository,
    StudentAssignmentRepository,
    StudentParentRepository,
    StudentRepository,
    TripRepository,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    ParentId,
    RouteId,
    StudentAssignmentId,
    StudentId,
    TripId,
    UserId,
    VehicleId,
)
from raad.modules.transport_ops.infra.mappers import (
    driver_to_model,
    model_to_driver,
    model_to_parent,
    model_to_route,
    model_to_student,
    model_to_student_assignment,
    model_to_student_parent,
    model_to_trip,
    parent_to_model,
    route_to_model,
    student_assignment_to_model,
    student_parent_to_model,
    student_to_model,
    trip_to_model,
)
from raad.modules.transport_ops.infra.models import (
    DriverModel,
    ParentModel,
    RouteModel,
    StudentAssignmentModel,
    StudentModel,
    StudentParentModel,
    TripModel,
)


class SqlAlchemyStudentRepository(
    SqlAlchemyRepositoryBase[StudentModel], StudentRepository
):
    model = StudentModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Student, StudentModel]] = {}

    async def get(self, student_id: StudentId) -> Student | None:
        row = await self.get_by_id(str(student_id))
        return self._track(row)

    def add(self, student: Student) -> None:
        model = student_to_model(student)
        super().add(model)
        self._tracked[str(student.id)] = (student, model)

    async def list_all(self) -> list[Student]:
        """See module docstring: unrestricted `TenantRegionScope` today, pending a system-wide
        `ScopeResolver` binding — not a Student-specific gap."""
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_student(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for student, model in self._tracked.values():
            student_to_model(student, existing=model)

    def _track(self, row: StudentModel | None) -> Student | None:
        if row is None:
            return None
        student = model_to_student(row)
        self._tracked[row.id] = (student, row)
        return student


class SqlAlchemyParentRepository(
    SqlAlchemyRepositoryBase[ParentModel], ParentRepository
):
    """Mirrors `SqlAlchemyStudentRepository`'s exact identity-map/`flush_tracked_changes`
    shape, including `list_all`'s same unrestricted-`TenantRegionScope` caveat (Phase 10.3's
    module docstring, unchanged this phase — still a system-wide `ScopeResolver` gap, not a
    `Parent`-specific one)."""

    model = ParentModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Parent, ParentModel]] = {}

    async def get(self, parent_id: ParentId) -> Parent | None:
        row = await self.get_by_id(str(parent_id))
        return self._track(row)

    async def get_by_user_id(self, user_id: UserId) -> Parent | None:
        statement = select(ParentModel).where(
            ParentModel.user_id == str(user_id), ParentModel.deleted_at.is_(None)
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, parent: Parent) -> None:
        model = parent_to_model(parent)
        super().add(model)
        self._tracked[str(parent.id)] = (parent, model)

    async def list_all(self) -> list[Parent]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_parent(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for parent, model in self._tracked.values():
            parent_to_model(parent, existing=model)

    def _track(self, row: ParentModel | None) -> Parent | None:
        if row is None:
            return None
        parent = model_to_parent(row)
        self._tracked[row.id] = (parent, row)
        return parent


class SqlAlchemyStudentParentRepository(StudentParentRepository):
    """See module docstring's Phase 10.7 addition for why this does **not** compose
    `SqlAlchemyRepositoryBase[StudentParentModel]` the way `SqlAlchemyStudentRepository`/
    `SqlAlchemyParentRepository` do — the composite-key shape doesn't fit that base class's
    single-`.id` assumptions, so this repository is a small, self-contained implementation
    instead."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tracked: dict[
            tuple[str, str], tuple[StudentParent, StudentParentModel]
        ] = {}

    async def get(
        self, student_id: StudentId, parent_id: ParentId
    ) -> StudentParent | None:
        statement = select(StudentParentModel).where(
            StudentParentModel.student_id == str(student_id),
            StudentParentModel.parent_id == str(parent_id),
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return self._track(row)

    def add(self, link: StudentParent) -> None:
        model = student_parent_to_model(link)
        self._session.add(model)
        self._tracked[(str(link.student_id), str(link.parent_id))] = (link, model)

    async def remove(self, link: StudentParent) -> None:
        key = (str(link.student_id), str(link.parent_id))
        tracked = self._tracked.pop(key, None)
        if tracked is None:
            # The application layer always calls get()/ensure_link_exists() before unlink()
            # (`application/services.py`), which populates `_tracked` - unreachable in
            # practice. Failing loudly here rather than silently no-op-ing, matching this
            # codebase's "fail loudly, don't fake it" posture (core/di/bootstrap.py's own
            # module docstring).
            raise LookupError(
                f"Cannot remove StudentParent({link.student_id}, {link.parent_id}): not "
                "tracked by this repository (call get() first)."
            )
        _, model = tracked
        # `AsyncSession.delete()` is itself a coroutine (unlike `.add()`) - it may need to
        # load relationships/cascade before marking the row for deletion. Found live: a
        # synchronous, un-awaited call here silently no-ops (the coroutine is created but
        # never scheduled), so the row survives commit - caught by
        # `test_transport_ops_student_parent_repository.py`'s round-trip test.
        await self._session.delete(model)

    async def list_by_student(self, student_id: StudentId) -> list[StudentParent]:
        statement = select(StudentParentModel).where(
            StudentParentModel.student_id == str(student_id)
        )
        result = await self._session.execute(statement)
        return [self._track(row) for row in result.scalars().all()]

    async def list_by_parent(self, parent_id: ParentId) -> list[StudentParent]:
        statement = select(StudentParentModel).where(
            StudentParentModel.parent_id == str(parent_id)
        )
        result = await self._session.execute(statement)
        return [self._track(row) for row in result.scalars().all()]

    def _track(self, row: StudentParentModel | None) -> StudentParent | None:
        if row is None:
            return None
        link = model_to_student_parent(row)
        self._tracked[(row.student_id, row.parent_id)] = (link, row)
        return link


class SqlAlchemyDriverRepository(
    SqlAlchemyRepositoryBase[DriverModel], DriverRepository
):
    """Mirrors `SqlAlchemyParentRepository`'s exact identity-map/`flush_tracked_changes` shape,
    including `list_all`'s same unrestricted-`TenantRegionScope` caveat (still a system-wide
    `ScopeResolver` gap, not a `Driver`-specific one)."""

    model = DriverModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Driver, DriverModel]] = {}

    async def get(self, driver_id: DriverId) -> Driver | None:
        row = await self.get_by_id(str(driver_id))
        return self._track(row)

    def add(self, driver: Driver) -> None:
        model = driver_to_model(driver)
        super().add(model)
        self._tracked[str(driver.id)] = (driver, model)

    async def list_all(self) -> list[Driver]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_driver(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for driver, model in self._tracked.values():
            driver_to_model(driver, existing=model)

    def _track(self, row: DriverModel | None) -> Driver | None:
        if row is None:
            return None
        driver = model_to_driver(row)
        self._tracked[row.id] = (driver, row)
        return driver


class SqlAlchemyRouteRepository(SqlAlchemyRepositoryBase[RouteModel], RouteRepository):
    """Mirrors `fleet_device.infra.repositories.SqlAlchemyDeviceRepository`'s exact shape —
    `flush_tracked_changes` re-projects the whole aggregate (stops included) via
    `route_to_model`, the same "Device+Camera" precedent, including `list_all`'s same
    unrestricted-`TenantRegionScope` caveat as every other `list_all` in this module."""

    model = RouteModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Route, RouteModel]] = {}

    async def get(self, route_id: RouteId) -> Route | None:
        row = await self.get_by_id(str(route_id))
        return self._track(row)

    async def get_by_name(self, name: str) -> Route | None:
        statement = select(RouteModel).where(
            RouteModel.name == name, RouteModel.deleted_at.is_(None)
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, route: Route) -> None:
        model = route_to_model(route)
        super().add(model)
        self._tracked[str(route.id)] = (route, model)

    async def list_all(self) -> list[Route]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_route(row) for row in rows]

    def flush_tracked_changes(self) -> None:
        for route, model in self._tracked.values():
            route_to_model(route, existing=model)

    def _track(self, row: RouteModel | None) -> Route | None:
        if row is None:
            return None
        route = model_to_route(row)
        self._tracked[row.id] = (route, row)
        return route


class SqlAlchemyTripRepository(SqlAlchemyRepositoryBase[TripModel], TripRepository):
    """Mirrors `SqlAlchemyDriverRepository`'s exact identity-map/`flush_tracked_changes` shape,
    including `list_all`'s same unrestricted-`TenantRegionScope` caveat as every other
    `list_all` in this module."""

    model = TripModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Trip, TripModel]] = {}

    async def get(self, trip_id: TripId) -> Trip | None:
        row = await self.get_by_id(str(trip_id))
        return self._track(row)

    def add(self, trip: Trip) -> None:
        model = trip_to_model(trip)
        super().add(model)
        self._tracked[str(trip.id)] = (trip, model)

    async def list_all(self) -> list[Trip]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_trip(row) for row in rows]

    async def active_trip_for_vehicle(self, vehicle_id: VehicleId) -> Trip | None:
        statement = select(TripModel).where(
            TripModel.vehicle_id == str(vehicle_id),
            TripModel.status == "in_progress",
            TripModel.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    async def list_for_route(self, route_id: RouteId) -> list[Trip]:
        statement = select(TripModel).where(
            TripModel.route_id == str(route_id), TripModel.deleted_at.is_(None)
        )
        result = await self._session.execute(statement)
        return [self._track(row) for row in result.scalars().all()]

    def flush_tracked_changes(self) -> None:
        for trip, model in self._tracked.values():
            trip_to_model(trip, existing=model)

    def _track(self, row: TripModel | None) -> Trip | None:
        if row is None:
            return None
        trip = model_to_trip(row)
        self._tracked[row.id] = (trip, row)
        return trip


class SqlAlchemyStudentAssignmentRepository(
    SqlAlchemyRepositoryBase[StudentAssignmentModel], StudentAssignmentRepository
):
    """Mirrors `SqlAlchemyTripRepository`'s exact identity-map/`flush_tracked_changes` shape,
    including `list_all`'s same unrestricted-`TenantRegionScope` caveat as every other
    `list_all` in this module."""

    model = StudentAssignmentModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[StudentAssignment, StudentAssignmentModel]] = {}

    async def get(
        self, student_assignment_id: StudentAssignmentId
    ) -> StudentAssignment | None:
        row = await self.get_by_id(str(student_assignment_id))
        return self._track(row)

    def add(self, assignment: StudentAssignment) -> None:
        model = student_assignment_to_model(assignment)
        super().add(model)
        self._tracked[str(assignment.id)] = (assignment, model)

    async def list_all(self) -> list[StudentAssignment]:
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [model_to_student_assignment(row) for row in rows]

    async def active_assignment_for_student(
        self, student_id: StudentId
    ) -> StudentAssignment | None:
        statement = select(StudentAssignmentModel).where(
            StudentAssignmentModel.student_id == str(student_id),
            StudentAssignmentModel.status == "active",
            StudentAssignmentModel.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def flush_tracked_changes(self) -> None:
        for assignment, model in self._tracked.values():
            student_assignment_to_model(assignment, existing=model)

    def _track(
        self, row: StudentAssignmentModel | None
    ) -> StudentAssignment | None:
        if row is None:
            return None
        assignment = model_to_student_assignment(row)
        self._tracked[row.id] = (assignment, row)
        return assignment


class SqlAlchemyTransportOpsUnitOfWork(SqlAlchemyUnitOfWork, TransportOpsUnitOfWork):
    """Concrete `TransportOpsUnitOfWork` (Backend LLD §8.2/§6.2). Constructs `transport_ops`'s
    repositories once the session is open, and re-syncs every tracked aggregate's in-place
    mutations onto its ORM row (`flush_tracked_changes`, above) immediately before delegating
    to `SqlAlchemyUnitOfWork.commit()` — which still owns the actual outbox-write +
    session-commit behavior, preserved exactly (§8.3), via `super().commit()`. Identical shape
    to `organization.infra.repositories.SqlAlchemyOrganizationUnitOfWork`, which already
    bundles two repositories (`organizations`/`regions`) the same way `students`/`parents` do
    here as of Phase 10.6; `student_parents` (Phase 10.7) joins the same way again — but needs
    no `flush_tracked_changes()` call of its own, per `SqlAlchemyStudentParentRepository`'s own
    docstring; `drivers` (Phase 10.8) joins the same way again, and *does* need its own
    `flush_tracked_changes()` call, mirroring `students`/`parents`; `routes` (Phase 11) joins
    the same way again, a fifth; `trips` (Phase 12) joins the same way again, a sixth;
    `student_assignments` (Phase 13) joins the same way again, a seventh.
    """

    students: SqlAlchemyStudentRepository
    parents: SqlAlchemyParentRepository
    student_parents: SqlAlchemyStudentParentRepository
    drivers: SqlAlchemyDriverRepository
    routes: SqlAlchemyRouteRepository
    trips: SqlAlchemyTripRepository
    student_assignments: SqlAlchemyStudentAssignmentRepository

    async def __aenter__(self) -> "SqlAlchemyTransportOpsUnitOfWork":
        await super().__aenter__()
        self.students = SqlAlchemyStudentRepository(self.session)
        self.parents = SqlAlchemyParentRepository(self.session)
        self.student_parents = SqlAlchemyStudentParentRepository(self.session)
        self.drivers = SqlAlchemyDriverRepository(self.session)
        self.routes = SqlAlchemyRouteRepository(self.session)
        self.trips = SqlAlchemyTripRepository(self.session)
        self.student_assignments = SqlAlchemyStudentAssignmentRepository(self.session)
        return self

    async def commit(self) -> None:
        self.students.flush_tracked_changes()
        self.parents.flush_tracked_changes()
        self.drivers.flush_tracked_changes()
        self.routes.flush_tracked_changes()
        self.trips.flush_tracked_changes()
        self.student_assignments.flush_tracked_changes()
        await super().commit()
