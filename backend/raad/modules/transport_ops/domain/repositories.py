"""Repository interfaces for the `transport_ops` module (Backend LLD §5.1/§7.1/§7.2).
Framework-free — no SQLAlchemy/FastAPI/Pydantic.

Deliberately **not** extending `core.db.repository`'s `Repository`/`TenantScopedRepository`,
for the same reason `organization.domain.repositories` doesn't: that module co-locates a
SQLAlchemy-dependent concrete class in the same file, so importing anything from it would force
this domain layer's import graph to require SQLAlchemy (forbidden by LLD §5.3 / `.claude/rules/
backend.md` #2). The concrete `infra/repositories.py` implementation (a later phase) is free to
also satisfy `core.db.repository`'s interfaces if useful — an infra-layer decision.

Phase 10.1 scope: `StudentRepository` only, matching `entities.py`'s `Student`-only scope.

**Phase 10.2 addition: `list_all`.** The application layer's `ListStudentsQuery` needs a
collection read this interface didn't previously expose — added here as an interface-only
method (no infra implementation this phase), per that phase's own explicit instruction
("Repositories remain interfaces only"). No `organization_id` parameter: tenant scoping is
injected once at the repository/infra layer automatically (`.claude/rules/backend.md` #4), the
same "never pass `organization_id` explicitly" convention `get`/`add` above already follow.

**Phase 10.7 addition: `StudentParentRepository`.** Deliberately **not** shaped like
`StudentRepository`/`ParentRepository` above — `StudentParent` has no single-column id
(composite-keyed by `student_id`+`parent_id`, `entities.py`'s Phase 10.7 addendum), so `get`
takes both ids, and a `remove` method is added (absent from the other two interfaces) since
unlinking is a real deletion, not a status transition — there is nothing to "add back" the way
`Student`/`Parent` are always re-fetched-and-mutated in place.

**Phase 10.8 addition: `DriverRepository`.** Mirrors `ParentRepository`'s exact shape —
`drivers` has no module-owned uniqueness constraint beyond its primary key either (Database
Design §6.1 lists no `UX` on `user_id`/`license_no`), so no `get_by_*` uniqueness-backing lookup
is needed, including `list_all` (matching `StudentRepository`/`ParentRepository`'s identical
precedent).

**Phase 11 addition: `RouteRepository`.** No separate `StopRepository` — `Stop` is a child
entity owned by `Route` (`entities.py`'s Phase 11 addition), the identical shape
`fleet_device.domain.repositories` already establishes (no `CameraRepository` alongside
`DeviceRepository`). `get_by_name` backs the per-tenant name uniqueness pre-check (Database
Design §6.5: `Unique (organization_id, name)`), mirroring `fleet_device.domain.repositories.
VehicleRepository.get_by_plate_no`'s identical shape for an analogous per-tenant unique column.

**Phase 12 addition: `TripRepository`.** `active_trip_for_vehicle`/`for_route` (implemented
here as `list_for_route`) are Backend LLD §7.2's own `TripRepository` contract skeleton,
verbatim. `active_trip_for_vehicle` backs the one-active-trip-per-vehicle guard
(`application/validators.py`'s `ensure_vehicle_has_no_active_trip`), mirroring
`fleet_device.domain.repositories.DeviceAssignmentRepository.active_for_vehicle`'s identical
role for its own one-active-device-per-vehicle invariant. `list_for_route` carries no
pagination of its own — it is a small, bounded per-route collection, not a general listing
surface, the same reasoning `StudentParentRepository.list_by_student`/`list_by_parent` (below)
apply to their own scoped collections; `ListTripsQuery`'s own top-level listing *is* now
paginated (Tier 2 pagination phase — see `list_page` below).

**Phase 13 addition: `StudentAssignmentRepository`.** No LLD-given contract skeleton exists for
this repository (unlike `TripRepository`/`DeviceAssignmentRepository`, which LLD §7.2 gives
verbatim) — built by structural analogy to `TripRepository`'s shape, the closest documented
precedent: both aggregates have a single-column surrogate id and a documented "one active X per
Y" invariant. `active_assignment_for_student` backs the one-active-assignment-per-student guard
(`application/validators.py`'s `ensure_student_has_no_active_assignment`), the identical role
`active_trip_for_vehicle` plays for `Trip`.

**Tier 2 pagination phase addition: `list_page` on `StudentRepository`/`ParentRepository`/
`DriverRepository`/`RouteRepository`/`TripRepository`/`StudentAssignmentRepository`.** Backs
`GET /students`/`/parents`/`/drivers`/`/routes`/`/trips`/`/student-assignments`'s paginated/
filterable/sortable contract (API Contracts §7/§8), applying the same `core.pagination`
(`OffsetPage`/`OffsetPageRequest`/`SortSpec`/`FilterCondition`) shape `iam.domain.repositories.
UserRepository.list_page`/`organization.domain.repositories.OrganizationRepository.list_page`
already establish — `core/pagination` is no longer the empty module earlier phases of this file
described; that gap is now closed. `list_all` remains alongside `list_page` on every one of
these six repositories (unlike `iam`/`organization`, which only ever had `list_page` layered on
top of an already-existing `list_all`, this module's own six `list_all` methods keep serving
their existing non-paginated callers unchanged — no caller of `list_all` was migrated to
`list_page` this phase). `StudentParentRepository` carries neither `list_page` nor a
`ListStudentParentsQuery` — its two "list X for Y" methods (`list_by_student`/`list_by_parent`)
are relationship-scoped-to-one-parent, small, out of this phase's scope (see the six routes this
phase actually touches, `api/routers.py`'s module docstring).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
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
    ParentId,
    RouteId,
    StudentAssignmentId,
    StudentId,
    TripId,
    UserId,
    VehicleId,
)


class StudentRepository(ABC):
    """`students` has no module-owned uniqueness constraint beyond its primary key (Database
    Design §6.2 lists no `UX` on `external_ref` or any other column) — so unlike `iam.
    UserRepository`, no `get_by_*` uniqueness-backing lookup is needed yet."""

    @abstractmethod
    async def get(self, student_id: StudentId) -> Student | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, student: Student) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Student]:
        """Backs `ListStudentsQuery` (Phase 10.2). Already implicitly scoped to the caller's
        tenant — see module docstring."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Student]:
        """Backs `GET /students`'s paginated/filtered/sorted contract (API Contracts §7/§8) —
        Tier 2 pagination phase addition, see module docstring."""
        raise NotImplementedError


class ParentRepository(ABC):
    """`parents` has no module-owned *uniqueness* constraint beyond its primary key (Database
    Design §6.3 lists no `UX` on `user_id` or any other column, matching `StudentRepository`'s
    identical reading of §6.2). Mirrors `StudentRepository`'s exact shape, including `list_all`
    (Phase 10.6, matching Phase 10.2's precedent)."""

    @abstractmethod
    async def get(self, parent_id: ParentId) -> Parent | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_user_id(self, user_id: UserId) -> Parent | None:
        """Resolves the authenticated `Principal.user_id` (an `iam.User`) to this module's own
        `Parent` aggregate id — needed by any parent-facing self-service feature, not just CR-1
        (`interfaces/http/deps.parent_access_guard`, Backend Stabilization phase). Not a
        uniqueness-backing lookup (no `UX` on `user_id`) — a plain finder, mirroring
        `SqlAlchemyDriverRepository`'s identical non-unique `user_id` filter shape."""
        raise NotImplementedError

    @abstractmethod
    def add(self, parent: Parent) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Parent]:
        """Backs `ListParentsQuery` (Phase 10.6). Already implicitly scoped to the caller's
        tenant — see module docstring."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Parent]:
        """Backs `GET /parents`'s paginated/filtered/sorted contract (API Contracts §7/§8) —
        Tier 2 pagination phase addition, see module docstring."""
        raise NotImplementedError


class StudentParentRepository(ABC):
    """`student_parents` has its own primary key shape (`PK (student_id, parent_id)`, Database
    Design §6.4) — no `get_by_*` uniqueness-backing lookup beyond that composite key itself is
    needed (duplicate-link prevention is `get(student_id, parent_id) is not None`, `application/
    validators.py`)."""

    @abstractmethod
    async def get(
        self, student_id: StudentId, parent_id: ParentId
    ) -> StudentParent | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, link: StudentParent) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def remove(self, link: StudentParent) -> None:
        """Unlinking is a real deletion (Database Design §6.4 has no status/`deleted_at`
        column on this table — confirmed with the user), not a status transition, unlike every
        `Student`/`Parent` behavior method. **Async**, unlike `add()` — the concrete
        SQLAlchemy implementation's `AsyncSession.delete()` is itself a coroutine (it may need
        to load relationships/cascade), unlike `Session.add()`'s synchronous equivalent.
        """
        raise NotImplementedError

    @abstractmethod
    async def list_by_student(self, student_id: StudentId) -> list[StudentParent]:
        """Backs `ListParentsForStudentQuery`."""
        raise NotImplementedError

    @abstractmethod
    async def list_by_parent(self, parent_id: ParentId) -> list[StudentParent]:
        """Backs `ListStudentsForParentQuery`."""
        raise NotImplementedError


class DriverRepository(ABC):
    """`drivers` has no module-owned uniqueness constraint beyond its primary key (Database
    Design §6.1 lists no `UX` on `user_id`/`license_no`) — mirrors `ParentRepository`'s exact
    shape, including `list_all` (matching Phase 10.2/10.6's precedent)."""

    @abstractmethod
    async def get(self, driver_id: DriverId) -> Driver | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, driver: Driver) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Driver]:
        """Backs `ListDriversQuery` (Phase 10.8). Already implicitly scoped to the caller's
        tenant — see module docstring."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Driver]:
        """Backs `GET /drivers`'s paginated/filtered/sorted contract (API Contracts §7/§8) —
        Tier 2 pagination phase addition, see module docstring."""
        raise NotImplementedError


class RouteRepository(ABC):
    """`Route` owns its `Stop` children (`entities.py`'s Phase 11 addition) — `get`/`add`
    always operate on the whole aggregate, stops included, mirroring
    `fleet_device.domain.repositories.DeviceRepository`'s identical shape for its own
    `Camera` children."""

    @abstractmethod
    async def get(self, route_id: RouteId) -> Route | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_name(self, name: str) -> Route | None:
        """Backs the per-tenant route-name uniqueness pre-check (Database Design §6.5:
        `Unique (organization_id, name)`)."""
        raise NotImplementedError

    @abstractmethod
    def add(self, route: Route) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Route]:
        """Backs `ListRoutesQuery` (Phase 11). Already implicitly scoped to the caller's
        tenant — see module docstring."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Route]:
        """Backs `GET /routes`'s paginated/filtered/sorted contract (API Contracts §7/§8) —
        Tier 2 pagination phase addition, see module docstring."""
        raise NotImplementedError


class TripRepository(ABC):
    """Backend LLD §7.2's `TripRepository` contract skeleton, verbatim (see module docstring's
    Phase 12 addition)."""

    @abstractmethod
    async def get(self, trip_id: TripId) -> Trip | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, trip: Trip) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Trip]:
        """Backs `ListTripsQuery` (Phase 12). Already implicitly scoped to the caller's
        tenant — see module docstring."""
        raise NotImplementedError

    @abstractmethod
    async def active_trip_for_vehicle(self, vehicle_id: VehicleId) -> Trip | None:
        """LLD §7.2 verbatim — the currently `IN_PROGRESS` trip for a vehicle, or None. Backs
        the one-active-trip-per-vehicle guard (safety-critical invariant,
        `.claude/rules/testing.md` #3)."""
        raise NotImplementedError

    @abstractmethod
    async def list_for_route(self, route_id: RouteId) -> list[Trip]:
        """LLD §7.2's `for_route`, without pagination — see module docstring's Phase 12
        addition for why."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Trip]:
        """Backs `GET /trips`'s paginated/filtered/sorted contract (API Contracts §7/§8) —
        Tier 2 pagination phase addition, see module docstring. Distinct from `list_for_route`
        above, which stays unpaginated (a small, bounded per-route collection, not this
        top-level listing surface)."""
        raise NotImplementedError


class StudentAssignmentRepository(ABC):
    """No LLD-given contract skeleton — see module docstring's Phase 13 addition."""

    @abstractmethod
    async def get(
        self, student_assignment_id: StudentAssignmentId
    ) -> StudentAssignment | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, assignment: StudentAssignment) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[StudentAssignment]:
        """Backs `ListStudentAssignmentsQuery` (Phase 13). Already implicitly scoped to the
        caller's tenant — see module docstring."""
        raise NotImplementedError

    @abstractmethod
    async def active_assignment_for_student(
        self, student_id: StudentId
    ) -> StudentAssignment | None:
        """The currently `ACTIVE` assignment for a student, or None. Backs the
        one-active-assignment-per-student guard (safety-critical/CR-1-relevant invariant,
        `.claude/rules/testing.md` #3)."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[StudentAssignment]:
        """Backs `GET /student-assignments`'s paginated/filtered/sorted contract (API
        Contracts §7/§8) — Tier 2 pagination phase addition, see module docstring."""
        raise NotImplementedError
