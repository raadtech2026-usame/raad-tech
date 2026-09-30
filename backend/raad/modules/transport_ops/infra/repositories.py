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

**Tenant-scoping (ADR-0021).** The gap this section used to describe (`list_all`/`list_page`
constructed with an explicit unrestricted `TenantRegionScope`, pending a system-wide
`ScopeResolver` binding) is now closed: every repository below — `students`, `parents`,
`drivers`, `routes`, `trips`, `student_assignments` — is constructed with the caller's resolved
`TenantRegionScope` (`SqlAlchemyTransportOpsUnitOfWork.__aenter__`, set from `api/deps.
get_transport_ops_uow`'s `Depends(get_scope)`); `get_by_id`/`list_page`/`list_all` all apply it
automatically via the base class, mirroring `fleet_device`/`organization`'s identical fix.
`SqlAlchemyStudentParentRepository` (Phase 10.7, below) is the one exception — it takes no
`scope` parameter at all, deliberately: every one of its call sites (`link_parent_to_student`/
`unlink_parent_from_student`/`list_parents_for_student`/`list_students_for_parent`,
`application/services.py`) already loads the parent `Student`/`Parent` through its own
now-scoped repository first, so an out-of-scope `student_id`/`parent_id` raises `NotFoundError`
before this repository is ever reached — verified by reading every call site, not assumed.
`Trip.schedule`/`StudentAssignment.assign`'s own cross-organization domain checks
(`domain/entities.py`) transitively benefit the same way once `drivers`/`routes`/`students` are
scoped: a tenant-scoped caller can no longer load another org's `Driver`/`Route`/`Student` to
build a request with it. `services.py`'s own `_enforce_own_organization` adds the matching
authorization-layer check for every command's own client-supplied `organization_id` field
(defense-in-depth per `.claude/rules/security.md` #2 — never rely on one layer alone).

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
ADR-0021 tenant-scoped posture — see the module docstring's own "Tenant-scoping" note).

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

**Tier 2 pagination phase addition: `list_page` on all six repositories above** (`students`/
`parents`/`drivers`/`routes`/`trips`/`student_assignments`), backing `GET /students`/`/parents`/
`/drivers`/`/routes`/`/trips`/`/student-assignments`'s paginated/filtered/sorted contract (API
Contracts §7/§8). Each composes the shared `SqlAlchemyRepositoryBase.list_page` (`core/db/
repository.py`) the identical way `organization.infra.repositories.
SqlAlchemyOrganizationRepository.list_page`/`iam.infra.repositories.SqlAlchemyUserRepository.
list_page` already do: the caller's own resolved `TenantRegionScope` (ADR-0021, see this
module docstring's own "Tenant-scoping" note above) — followed by re-tracking every returned
row through the repository's own `_track`
helper (so a paginated result participates in the identity-map/`flush_tracked_changes` bridge
exactly like `get()`'s result does). Each repository's `filterable_fields`/`sortable_fields`/
`searchable_fields` whitelist is limited to columns already exposed on that aggregate's
*summary* DTO/response (`application/queries.py`'s `StudentSummaryDTO`/etc.) — the same
"whitelist limited to what's already on the response" precedent `organization`'s own
whitelists establish, never a wider column set than the list endpoint's own response shape.
`core/pagination` is no longer the empty module earlier phases of this file described.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import FilterField, SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.transport_ops.application.ports import TransportOpsUnitOfWork
from raad.modules.transport_ops.domain.entities import (
    Driver,
    Parent,
    Route,
    StaffDocument,
    StaffDocumentType,
    Student,
    StudentAssignment,
    StudentParent,
    TransportStaff,
    TransportStaffRole,
    Trip,
    VehicleStaffAssignment,
)
from raad.modules.transport_ops.domain.repositories import (
    DriverRepository,
    ParentRepository,
    RouteRepository,
    StaffDocumentRepository,
    StaffDocumentTypeRepository,
    StudentAssignmentRepository,
    StudentParentRepository,
    StudentRepository,
    TransportStaffRepository,
    TransportStaffRoleRepository,
    TripRepository,
    VehicleStaffAssignmentRepository,
)
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    ParentId,
    RouteId,
    StaffDocumentId,
    StaffDocumentTypeId,
    StudentAssignmentId,
    StudentId,
    TransportStaffId,
    TransportStaffRoleId,
    TripId,
    UserId,
    VehicleId,
    VehicleStaffAssignmentId,
)
from raad.modules.transport_ops.infra.mappers import (
    driver_to_model,
    model_to_driver,
    model_to_staff_document,
    model_to_staff_document_type,
    model_to_transport_staff,
    model_to_transport_staff_role,
    model_to_vehicle_staff_assignment,
    staff_document_to_model,
    staff_document_type_to_model,
    transport_staff_role_to_model,
    transport_staff_to_model,
    vehicle_staff_assignment_to_model,
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
    StaffDocumentModel,
    StaffDocumentTypeModel,
    StudentParentModel,
    TransportStaffModel,
    TransportStaffRoleModel,
    TripModel,
    VehicleStaffAssignmentModel,
)


class SqlAlchemyStudentRepository(
    SqlAlchemyRepositoryBase[StudentModel], StudentRepository
):
    model = StudentModel

    #: Whitelist for `GET /students` (§8) — limited to columns already on `StudentSummaryResponse`.
    filterable_fields = {
        # ADR-0021 keeps this honest: `_apply_scope` still narrows every query to the
        # caller's own scope, so this filter can only narrow *within* what the caller may
        # already see. It exists so a Founder can focus one organization.
        "organization_id": FilterField(column="organization_id"),
        "status": FilterField(column="status"),
    }
    sortable_fields = {
        "full_name": "full_name",
        "status": "status",
    }
    searchable_fields = ("full_name",)

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[Student, StudentModel]] = {}

    async def get(self, student_id: StudentId) -> Student | None:
        row = await self.get_by_id(str(student_id))
        return self._track(row)

    def add(self, student: Student) -> None:
        model = student_to_model(student)
        super().add(model)
        self._tracked[str(student.id)] = (student, model)

    async def list_all(self) -> list[Student]:
        """Tenant-scoped via `list_scoped`'s own `_apply_scope` call (ADR-0021) — see the
        module docstring's "Tenant-scoping" note."""
        rows = await self.list_scoped()
        return [model_to_student(row) for row in rows]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Student]:
        """Tenant-scoped exactly like `list_all` above (ADR-0021, `_apply_scope`) — not the
        unrestricted posture this docstring described before that fix landed."""
        raw_page = await super().list_page(
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

    async def list_by_ids(self, student_ids: list[str]) -> list[Student]:
        """Report Center re-design — mirrors `SqlAlchemyParentRepository.list_by_ids` exactly,
        including its identical tenant-scoping posture (an id outside the caller's own scope is
        silently absent, never surfaced)."""
        if not student_ids:
            return []
        statement = self._apply_scope(
            select(StudentModel).where(
                StudentModel.id.in_(student_ids), StudentModel.deleted_at.is_(None)
            )
        )
        result = await self._session.execute(statement)
        return [self._track(row) for row in result.scalars().all()]  # type: ignore[misc]

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
    shape, including `list_all`'s ADR-0021 tenant-scoped posture (see the module docstring's
    own "Tenant-scoping" note)."""

    model = ParentModel

    #: Whitelist for `GET /parents` (§8) — limited to columns already on `ParentSummaryResponse`,
    #: plus `phone` (2026-09-10, Parent & Student Domain Restructure): duplicate-parent
    #: protection and "search parent by name or phone" both need an exact/partial phone match,
    #: and `_apply_scope` (ADR-0021) still narrows every query to the caller's own tenant first,
    #: so this never becomes a cross-organization phone lookup.
    filterable_fields = {
        # ADR-0021 keeps this honest: `_apply_scope` still narrows every query to the
        # caller's own scope, so this filter can only narrow *within* what the caller may
        # already see. It exists so a Founder can focus one organization.
        "organization_id": FilterField(column="organization_id"),
        "status": FilterField(column="status"),
        "phone": FilterField(column="phone"),
    }
    sortable_fields = {
        "full_name": "full_name",
        "status": "status",
    }
    searchable_fields = ("full_name", "phone")

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
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
        rows = await self.list_scoped()
        return [model_to_parent(row) for row in rows]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Parent]:
        """Tenant-scoped exactly like `list_all` above (ADR-0021, `_apply_scope`) — not the
        unrestricted posture this docstring described before that fix landed."""
        raw_page = await super().list_page(
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

    async def list_by_ids(self, parent_ids: list[str]) -> list[Parent]:
        """ADR-0041 §1. Tenant-scoped via `_apply_scope`, same as every other read here — an id
        outside the caller's own scope is silently absent, never surfaced."""
        if not parent_ids:
            return []
        statement = self._apply_scope(
            select(ParentModel).where(
                ParentModel.id.in_(parent_ids), ParentModel.deleted_at.is_(None)
            )
        )
        result = await self._session.execute(statement)
        return [self._track(row) for row in result.scalars().all()]  # type: ignore[misc]

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

    async def list_by_students(self, student_ids: list[StudentId]) -> list[StudentParent]:
        """ADR-0041 §1. `student_id IN (...)` short-circuits to an empty list for an empty
        input — SQLAlchemy renders `IN ()` as a query that never matches, which works but is
        wasted round trip for a caller that already knows there is nothing to ask about."""
        if not student_ids:
            return []
        statement = select(StudentParentModel).where(
            StudentParentModel.student_id.in_([str(sid) for sid in student_ids])
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
    including `list_all`'s ADR-0021 tenant-scoped posture (see the module docstring's own
    "Tenant-scoping" note)."""

    model = DriverModel

    #: Whitelist for `GET /drivers` (§8) — limited to columns already on `DriverSummaryResponse`
    #: (`Driver` has no `full_name` of its own — `license_no` stands in as the readable
    #: identifying field, mirroring `application/queries.py`'s `DriverSummaryDTO` docstring).
    filterable_fields = {
        # ADR-0021 keeps this honest: `_apply_scope` still narrows every query to the
        # caller's own scope, so this filter can only narrow *within* what the caller may
        # already see. It exists so a Founder can focus one organization.
        "organization_id": FilterField(column="organization_id"),
        "status": FilterField(column="status"),
    }
    sortable_fields = {
        "license_no": "license_no",
        "status": "status",
    }
    searchable_fields = ("license_no",)

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[Driver, DriverModel]] = {}

    async def get(self, driver_id: DriverId) -> Driver | None:
        row = await self.get_by_id(str(driver_id))
        return self._track(row)

    async def get_by_staff_id(self, staff_id: TransportStaffId) -> Driver | None:
        statement = self._apply_scope(
            select(DriverModel).where(
                DriverModel.staff_id == str(staff_id), DriverModel.deleted_at.is_(None)
            )
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    async def list_by_staff_ids(self, staff_ids: list[str]) -> list[Driver]:
        if not staff_ids:
            return []
        statement = self._apply_scope(
            select(DriverModel).where(
                DriverModel.staff_id.in_(sorted(set(staff_ids))),
                DriverModel.deleted_at.is_(None),
            )
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._track(row) for row in rows]  # type: ignore[misc]

    async def get_by_user_id(self, user_id: UserId) -> Driver | None:
        statement = select(DriverModel).where(
            DriverModel.user_id == str(user_id), DriverModel.deleted_at.is_(None)
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, driver: Driver) -> None:
        model = driver_to_model(driver)
        super().add(model)
        self._tracked[str(driver.id)] = (driver, model)

    async def list_all(self) -> list[Driver]:
        rows = await self.list_scoped()
        return [model_to_driver(row) for row in rows]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Driver]:
        """Tenant-scoped exactly like `list_all` above (ADR-0021, `_apply_scope`) — not the
        unrestricted posture this docstring described before that fix landed."""
        raw_page = await super().list_page(
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

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
    ADR-0021 tenant-scoped posture as every other `list_all` in this module."""

    model = RouteModel

    #: Whitelist for `GET /routes` (§8) — limited to columns already on `RouteSummaryResponse`.
    filterable_fields = {
        # ADR-0021 keeps this honest: `_apply_scope` still narrows every query to the
        # caller's own scope, so this filter can only narrow *within* what the caller may
        # already see. It exists so a Founder can focus one organization.
        "organization_id": FilterField(column="organization_id"),
        "status": FilterField(column="status"),
    }
    sortable_fields = {
        "name": "name",
        "status": "status",
    }
    searchable_fields = ("name",)

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
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
        rows = await self.list_scoped()
        return [model_to_route(row) for row in rows]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Route]:
        """Tenant-scoped exactly like `list_all` above (ADR-0021, `_apply_scope`) — not the
        unrestricted posture this docstring described before that fix landed."""
        raw_page = await super().list_page(
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

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
    including `list_all`'s same ADR-0021 tenant-scoped posture as every other `list_all` in
    this module."""

    model = TripModel

    #: Whitelist for `GET /trips` (§8) — limited to columns already on `TripSummaryResponse`.
    #: `Trip` is API Contracts §8's own filtering example resource (`filter[trip_type][in]=...`,
    #: `filter[scheduled_date][gte]=...`), so both are whitelisted here verbatim.
    filterable_fields = {
        "status": FilterField(column="status"),
        "trip_type": FilterField(column="trip_type"),
        "vehicle_id": FilterField(column="vehicle_id"),
        "driver_id": FilterField(column="driver_id"),
        "route_id": FilterField(column="route_id"),
        "scheduled_date": FilterField(column="scheduled_date", value_type=date),
    }
    sortable_fields = {
        "scheduled_date": "scheduled_date",
        "status": "status",
        "trip_type": "trip_type",
    }
    #: No free-text field exists on `TripSummaryResponse` — search is deliberately empty here,
    #: matching `core.db.repository.SqlAlchemyRepositoryBase._apply_search`'s "no-op when
    #: `searchable_fields` is empty" behavior.
    searchable_fields: tuple[str, ...] = ()

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[Trip, TripModel]] = {}

    async def get(self, trip_id: TripId) -> Trip | None:
        row = await self.get_by_id(str(trip_id))
        return self._track(row)

    def add(self, trip: Trip) -> None:
        model = trip_to_model(trip)
        super().add(model)
        self._tracked[str(trip.id)] = (trip, model)

    async def list_all(self) -> list[Trip]:
        rows = await self.list_scoped()
        return [model_to_trip(row) for row in rows]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Trip]:
        """Tenant-scoped exactly like `list_all` above (ADR-0021, `_apply_scope`) — not the
        unrestricted posture this docstring described before that fix landed."""
        raw_page = await super().list_page(
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

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
    including `list_all`'s same ADR-0021 tenant-scoped posture as every other `list_all` in
    this module."""

    model = StudentAssignmentModel

    #: Whitelist for `GET /student-assignments` (§8) — limited to columns already on
    #: `StudentAssignmentSummaryResponse`.
    filterable_fields = {
        "status": FilterField(column="status"),
        "route_id": FilterField(column="route_id"),
        "student_id": FilterField(column="student_id"),
    }
    sortable_fields = {
        "status": "status",
    }
    searchable_fields: tuple[str, ...] = ()

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
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
        rows = await self.list_scoped()
        return [model_to_student_assignment(row) for row in rows]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[StudentAssignment]:
        """Tenant-scoped exactly like `list_all` above (ADR-0021, `_apply_scope`) — not the
        unrestricted posture this docstring described before that fix landed."""
        raw_page = await super().list_page(
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

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


# ---- ADR-0049/0050/0051: transport staff, bus crew, staff documents ----------------------------


class _TrackingRepository:
    """The identity-map shape every repository in this module repeats: track each aggregate
    with its row so `flush_tracked_changes` can re-project in-place mutations before commit."""

    _to_model = None
    _from_model = None

    def _init_tracking(self) -> None:
        self._tracked: dict[str, tuple[object, object]] = {}

    def _track_row(self, row):
        if row is None:
            return None
        key = row.id
        if key in self._tracked:
            return self._tracked[key][0]
        aggregate = type(self)._from_model(row)
        self._tracked[key] = (aggregate, row)
        return aggregate

    def _track_new(self, aggregate) -> object:
        model = type(self)._to_model(aggregate)
        self._tracked[str(aggregate.id)] = (aggregate, model)
        return model

    def flush_tracked_changes(self) -> None:
        for aggregate, model in self._tracked.values():
            type(self)._to_model(aggregate, existing=model)


class SqlAlchemyTransportStaffRoleRepository(
    _TrackingRepository,
    SqlAlchemyRepositoryBase[TransportStaffRoleModel],
    TransportStaffRoleRepository,
):
    model = TransportStaffRoleModel
    _to_model = staticmethod(transport_staff_role_to_model)
    _from_model = staticmethod(model_to_transport_staff_role)

    def __init__(self, session: AsyncSession, *, scope: TenantRegionScope | None = None) -> None:
        super().__init__(session, scope=scope)
        self._init_tracking()

    async def get(self, role_id: TransportStaffRoleId) -> TransportStaffRole | None:
        return self._track_row(await self.get_by_id(str(role_id)))

    def add(self, role: TransportStaffRole) -> None:
        super().add(self._track_new(role))

    async def list_for_organization(self, organization_id: str) -> list[TransportStaffRole]:
        statement = self._apply_scope(
            select(self.model)
            .where(
                self.model.organization_id == organization_id,
                self.model.deleted_at.is_(None),
            )
            .order_by(self.model.sort_order, self.model.name)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._track_row(row) for row in rows]


class SqlAlchemyTransportStaffRepository(
    _TrackingRepository,
    SqlAlchemyRepositoryBase[TransportStaffModel],
    TransportStaffRepository,
):
    model = TransportStaffModel
    _to_model = staticmethod(transport_staff_to_model)
    _from_model = staticmethod(model_to_transport_staff)

    #: Filtering stays inside the caller's scope (ADR-0021); `organization_id` only narrows it.
    filterable_fields = {
        "organization_id": FilterField(column="organization_id"),
        "status": FilterField(column="status"),
        "role_id": FilterField(column="role_id"),
    }
    sortable_fields = {
        "full_name": "full_name",
        "status": "status",
        "start_date": "start_date",
        "created_at": "created_at",
    }
    searchable_fields = ("full_name", "employee_ref", "phone")

    def __init__(self, session: AsyncSession, *, scope: TenantRegionScope | None = None) -> None:
        super().__init__(session, scope=scope)
        self._init_tracking()

    async def get(self, staff_id: TransportStaffId) -> TransportStaff | None:
        return self._track_row(await self.get_by_id(str(staff_id)))

    def add(self, staff: TransportStaff) -> None:
        super().add(self._track_new(staff))

    async def get_by_employee_ref(
        self, *, organization_id: str, employee_ref: str
    ) -> TransportStaff | None:
        statement = self._apply_scope(
            select(self.model).where(
                self.model.organization_id == organization_id,
                self.model.employee_ref == employee_ref,
                self.model.deleted_at.is_(None),
            )
        )
        return self._track_row((await self._session.execute(statement)).scalar_one_or_none())

    async def list_by_ids(self, staff_ids: list[str]) -> list[TransportStaff]:
        if not staff_ids:
            return []
        statement = self._apply_scope(
            select(self.model).where(
                self.model.id.in_(sorted(set(staff_ids))), self.model.deleted_at.is_(None)
            )
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._track_row(row) for row in rows]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[TransportStaff]:
        raw = await super().list_page(page_request, sort=sort, filters=filters, search=search)
        return OffsetPage(
            data=[self._track_row(row) for row in raw.data],
            total=raw.total,
            page=raw.page,
            page_size=raw.page_size,
        )


class SqlAlchemyVehicleStaffAssignmentRepository(
    _TrackingRepository,
    SqlAlchemyRepositoryBase[VehicleStaffAssignmentModel],
    VehicleStaffAssignmentRepository,
):
    model = VehicleStaffAssignmentModel
    _to_model = staticmethod(vehicle_staff_assignment_to_model)
    _from_model = staticmethod(model_to_vehicle_staff_assignment)

    def __init__(self, session: AsyncSession, *, scope: TenantRegionScope | None = None) -> None:
        super().__init__(session, scope=scope)
        self._init_tracking()

    async def get(self, assignment_id: VehicleStaffAssignmentId) -> VehicleStaffAssignment | None:
        return self._track_row(await self.get_by_id(str(assignment_id)))

    def add(self, assignment: VehicleStaffAssignment) -> None:
        super().add(self._track_new(assignment))

    async def list_for(
        self,
        *,
        staff_id: TransportStaffId | None = None,
        vehicle_id: VehicleId | None = None,
    ) -> list[VehicleStaffAssignment]:
        statement = select(self.model).where(self.model.deleted_at.is_(None))
        if staff_id is not None:
            statement = statement.where(self.model.staff_id == str(staff_id))
        if vehicle_id is not None:
            statement = statement.where(self.model.vehicle_id == str(vehicle_id))
        statement = self._apply_scope(
            statement.order_by(self.model.starts_on.desc(), self.model.created_at.desc())
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._track_row(row) for row in rows]


class SqlAlchemyStaffDocumentTypeRepository(
    _TrackingRepository,
    SqlAlchemyRepositoryBase[StaffDocumentTypeModel],
    StaffDocumentTypeRepository,
):
    model = StaffDocumentTypeModel
    _to_model = staticmethod(staff_document_type_to_model)
    _from_model = staticmethod(model_to_staff_document_type)

    def __init__(self, session: AsyncSession, *, scope: TenantRegionScope | None = None) -> None:
        super().__init__(session, scope=scope)
        self._init_tracking()

    async def get(self, type_id: StaffDocumentTypeId) -> StaffDocumentType | None:
        return self._track_row(await self.get_by_id(str(type_id)))

    def add(self, doc_type: StaffDocumentType) -> None:
        super().add(self._track_new(doc_type))

    async def list_for_organization(self, organization_id: str) -> list[StaffDocumentType]:
        statement = self._apply_scope(
            select(self.model)
            .where(
                self.model.organization_id == organization_id,
                self.model.deleted_at.is_(None),
            )
            .order_by(self.model.name)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._track_row(row) for row in rows]

    async def list_by_ids(self, type_ids: list[str]) -> list[StaffDocumentType]:
        if not type_ids:
            return []
        statement = self._apply_scope(
            select(self.model).where(self.model.id.in_(sorted(set(type_ids))))
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._track_row(row) for row in rows]


class SqlAlchemyStaffDocumentRepository(
    _TrackingRepository,
    SqlAlchemyRepositoryBase[StaffDocumentModel],
    StaffDocumentRepository,
):
    model = StaffDocumentModel
    _to_model = staticmethod(staff_document_to_model)
    _from_model = staticmethod(model_to_staff_document)

    def __init__(self, session: AsyncSession, *, scope: TenantRegionScope | None = None) -> None:
        super().__init__(session, scope=scope)
        self._init_tracking()

    async def get(self, document_id: StaffDocumentId) -> StaffDocument | None:
        return self._track_row(await self.get_by_id(str(document_id)))

    def add(self, document: StaffDocument) -> None:
        super().add(self._track_new(document))

    async def list_for_staff(self, staff_id: TransportStaffId) -> list[StaffDocument]:
        statement = self._apply_scope(
            select(self.model)
            .where(self.model.staff_id == str(staff_id), self.model.deleted_at.is_(None))
            .order_by(self.model.created_at.desc())
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._track_row(row) for row in rows]

    async def list_current_with_expiry(self) -> list[StaffDocument]:
        statement = self._apply_scope(
            select(self.model)
            .where(
                self.model.replaced_by_id.is_(None),
                self.model.expires_on.is_not(None),
                self.model.deleted_at.is_(None),
            )
            .order_by(self.model.expires_on)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [self._track_row(row) for row in rows]


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
    staff_roles: SqlAlchemyTransportStaffRoleRepository
    staff: SqlAlchemyTransportStaffRepository
    staff_assignments: SqlAlchemyVehicleStaffAssignmentRepository
    staff_document_types: SqlAlchemyStaffDocumentTypeRepository
    staff_documents: SqlAlchemyStaffDocumentRepository

    async def __aenter__(self) -> "SqlAlchemyTransportOpsUnitOfWork":
        await super().__aenter__()
        self.students = SqlAlchemyStudentRepository(self.session, scope=self.scope)
        self.parents = SqlAlchemyParentRepository(self.session, scope=self.scope)
        self.student_parents = SqlAlchemyStudentParentRepository(self.session)
        self.drivers = SqlAlchemyDriverRepository(self.session, scope=self.scope)
        self.routes = SqlAlchemyRouteRepository(self.session, scope=self.scope)
        self.trips = SqlAlchemyTripRepository(self.session, scope=self.scope)
        self.student_assignments = SqlAlchemyStudentAssignmentRepository(
            self.session, scope=self.scope
        )
        self.staff_roles = SqlAlchemyTransportStaffRoleRepository(self.session, scope=self.scope)
        self.staff = SqlAlchemyTransportStaffRepository(self.session, scope=self.scope)
        self.staff_assignments = SqlAlchemyVehicleStaffAssignmentRepository(
            self.session, scope=self.scope
        )
        self.staff_document_types = SqlAlchemyStaffDocumentTypeRepository(
            self.session, scope=self.scope
        )
        self.staff_documents = SqlAlchemyStaffDocumentRepository(self.session, scope=self.scope)
        return self

    async def commit(self) -> None:
        self.students.flush_tracked_changes()
        self.parents.flush_tracked_changes()
        self.drivers.flush_tracked_changes()
        self.routes.flush_tracked_changes()
        self.trips.flush_tracked_changes()
        self.student_assignments.flush_tracked_changes()
        self.staff_roles.flush_tracked_changes()
        self.staff.flush_tracked_changes()
        self.staff_assignments.flush_tracked_changes()
        self.staff_document_types.flush_tracked_changes()
        self.staff_documents.flush_tracked_changes()
        await super().commit()
