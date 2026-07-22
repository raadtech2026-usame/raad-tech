"""Transport Operations application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite
read-models). DTOs are plain dataclasses — the boundary between the domain's aggregates and any
future API/infra layer, so neither ever depends on the other's internal shape. Mirrors
`organization.application.queries`'s shape exactly: id fields become `str(vo)`, enum/status
fields become `.value`, timestamps (none on `Student` — see `domain/entities.py`) would stay
native `datetime`, never `.isoformat()`-stringified at this layer.

**`ListStudentsQuery` established a new pattern in this codebase when first written (Phase
10.2) — flagged then, not silently copied.** At the time, no `List*Query` existed in any of
`iam`/`organization`/`fleet_device`/`tracking`'s application layers (their only "many" reads
were relationship-scoped, e.g. `GetVehiclePositionHistoryQuery(trip_id)`, never an unscoped
"list everything in my tenant"), and `core/pagination` was an empty module — no limit/offset/
cursor convention existed yet to reuse. `ListStudentsQuery` therefore carried no fields at all;
pagination was deferred to whichever later phase actually needed it.

**That later phase is this one (Tier 2 pagination phase).** `core/pagination` is no longer
empty — `iam.application.queries.ListUsersQuery`/`organization.application.queries.
ListOrganizationsQuery`/`ListRegionsQuery` already established the concrete shape
(`page_request: OffsetPageRequest`, `sort: list[SortSpec]`, `filters: list[FilterCondition]`,
`search: str | None`), and `ListStudentsQuery`/`ListParentsQuery`/`ListDriversQuery`/
`ListRoutesQuery`/`ListTripsQuery`/`ListStudentAssignmentsQuery` (below) now all carry that
identical shape rather than the old empty-`pass` body the paragraph above used to describe.
`ListParentsForStudentQuery`/`ListStudentsForParentQuery`/`ListStopsForRouteQuery` (this
module's three relationship-/child-scoped-to-one-parent reads) are deliberately **not**
paginated this phase — out of scope, per the task's own explicit boundary (small,
scoped-to-one-parent collections, not top-level resource lists).

**`StudentSummaryDTO` also establishes a new pattern — flagged.** No module in this codebase has
a "summary" vs. "full" DTO distinction; every aggregate has exactly one DTO shape. Built here
only because the task explicitly requests it: a lighter projection for `list_students` (omitting
`organization_id`/`external_ref`, which a listing view doesn't need) alongside the full
`StudentDTO` for `get_student_by_id`.

**Phase 10.8 addition: `Driver` queries/DTOs.** `GetDriverByIdQuery`/`ListDriversQuery`/
`DriverDTO`/`DriverSummaryDTO`, mirroring `Parent`'s equivalents exactly (by-then an established
pattern, not a new one) — see `DriverSummaryDTO`'s own docstring for the one shape difference
(`license_no` instead of `full_name`, since `Driver` has none of its own).

**Phase 11 addition: `Route`/`Stop` queries/DTOs.** `RouteDTO` embeds
`stops: tuple[StopDTO, ...]`, mirroring `fleet_device.application.queries.DeviceDTO`'s identical
`cameras: tuple[CameraDTO, ...]` shape for an intra-aggregate child collection.
`RouteSummaryDTO` (the `ListRoutesQuery` read shape) omits `stops` — a listing view doesn't
need the full nested collection, the same reasoning `StudentSummaryDTO`/`ParentSummaryDTO`
already establish for their own omitted fields. `list_stops_for_route` reuses `Route.stops`'s
own always-sorted-by-`sequence_no` ordering (`domain/entities.py`) rather than re-sorting here —
a second, possibly-diverging sort implementation would be a needless duplicate of the one
already-correct source.

**Phase 12 addition: `Trip` queries/DTOs.** `TripDTO`/`TripSummaryDTO` mirror `DriverDTO`/
`DriverSummaryDTO`'s exact shape. `started_at`/`ended_at` stay native `datetime | None`
(`scheduled_date` stays native `date`) — this file's own documented convention ("timestamps...
stay native `datetime`, never `.isoformat()`-stringified at this layer"); the API layer's
Pydantic schemas (`api/schemas.py`) handle JSON serialization, not this one.

**Phase 13 addition: `StudentAssignment` queries/DTOs.** `StudentAssignmentDTO`/
`StudentAssignmentSummaryDTO` mirror `TripDTO`/`TripSummaryDTO`'s exact shape. **Not** included:
`created_at`/`updated_at` — API Contracts §6's documented example resource for this aggregate
shows them, but no DTO in this module has ever carried ORM-only audit columns (they are not
domain-aggregate fields anywhere in this file); flagged as a pre-existing, module-wide
documentation-vs-implementation gap in `domain/entities.py`'s module docstring, not fixed
one-off here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.modules.transport_ops.domain.entities import (
    Driver,
    Parent,
    Route,
    Stop,
    Student,
    StudentAssignment,
    StudentParent,
    Trip,
)


@dataclass(frozen=True)
class GetStudentByIdQuery:
    student_id: str


@dataclass(frozen=True)
class ListStudentsQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class StudentDTO:
    id: str
    organization_id: str
    full_name: str
    external_ref: str | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StudentSummaryDTO:
    id: str
    full_name: str
    status: str


def student_to_dto(student: Student) -> StudentDTO:
    """Shared mapper — the only place a `Student` aggregate is projected into its full DTO."""
    return StudentDTO(
        id=str(student.id),
        organization_id=str(student.organization_id),
        full_name=student.full_name,
        external_ref=student.external_ref,
        status=student.status.value,
        created_at=student.created_at,
        updated_at=student.updated_at,
    )


def student_to_summary_dto(student: Student) -> StudentSummaryDTO:
    """Shared mapper — the only place a `Student` aggregate is projected into its summary DTO
    (`ListStudentsQuery`'s read shape)."""
    return StudentSummaryDTO(
        id=str(student.id),
        full_name=student.full_name,
        status=student.status.value,
    )


@dataclass(frozen=True)
class GetParentByIdQuery:
    parent_id: str


@dataclass(frozen=True)
class ListParentsQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class ParentDTO:
    id: str
    organization_id: str
    user_id: str
    full_name: str
    phone: str | None
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ParentSummaryDTO:
    id: str
    full_name: str
    status: str


def parent_to_dto(parent: Parent) -> ParentDTO:
    """Shared mapper — the only place a `Parent` aggregate is projected into its full DTO,
    mirroring `student_to_dto`'s exact shape."""
    return ParentDTO(
        id=str(parent.id),
        organization_id=str(parent.organization_id),
        user_id=str(parent.user_id),
        full_name=parent.full_name,
        phone=str(parent.phone) if parent.phone is not None else None,
        status=parent.status.value,
        created_at=parent.created_at,
        updated_at=parent.updated_at,
    )


def parent_to_summary_dto(parent: Parent) -> ParentSummaryDTO:
    """Shared mapper — the only place a `Parent` aggregate is projected into its summary DTO
    (`ListParentsQuery`'s read shape), mirroring `student_to_summary_dto`'s exact shape.
    """
    return ParentSummaryDTO(
        id=str(parent.id), full_name=parent.full_name, status=parent.status.value
    )


@dataclass(frozen=True)
class ListParentsForStudentQuery:
    student_id: str


@dataclass(frozen=True)
class ListStudentsForParentQuery:
    parent_id: str


@dataclass(frozen=True)
class StudentParentDTO:
    """The raw link record — returned by `link_parent_to_student` (Phase 10.7). The two "list X
    for Y" read paths return the richer `ParentForStudentDTO`/`StudentForParentDTO` below
    instead (joining in the referenced aggregate's own fields), since a bare link record with
    only ids is of little use to an API caller asking "which parents does this student have" —
    flagged as a deliberate shape choice, not a silently invented one."""

    student_id: str
    parent_id: str
    relationship: str | None
    is_primary: bool


@dataclass(frozen=True)
class ParentForStudentDTO:
    """`Parent`'s own fields plus this link's `relationship`/`is_primary` — the read shape for
    `ListParentsForStudentQuery` (Phase 10.7)."""

    parent_id: str
    full_name: str
    phone: str | None
    status: str
    relationship: str | None
    is_primary: bool


@dataclass(frozen=True)
class StudentForParentDTO:
    """`Student`'s own fields plus this link's `relationship`/`is_primary` — the read shape for
    `ListStudentsForParentQuery` (Phase 10.7)."""

    student_id: str
    full_name: str
    status: str
    relationship: str | None
    is_primary: bool


def student_parent_to_dto(link: StudentParent) -> StudentParentDTO:
    """Shared mapper — the only place a `StudentParent` aggregate is projected into its raw
    link DTO."""
    return StudentParentDTO(
        student_id=str(link.student_id),
        parent_id=str(link.parent_id),
        relationship=link.relationship,
        is_primary=link.is_primary,
    )


def parent_for_student_to_dto(
    parent: Parent, link: StudentParent
) -> ParentForStudentDTO:
    return ParentForStudentDTO(
        parent_id=str(parent.id),
        full_name=parent.full_name,
        phone=str(parent.phone) if parent.phone is not None else None,
        status=parent.status.value,
        relationship=link.relationship,
        is_primary=link.is_primary,
    )


def student_for_parent_to_dto(
    student: Student, link: StudentParent
) -> StudentForParentDTO:
    return StudentForParentDTO(
        student_id=str(student.id),
        full_name=student.full_name,
        status=student.status.value,
        relationship=link.relationship,
        is_primary=link.is_primary,
    )


@dataclass(frozen=True)
class GetDriverByIdQuery:
    driver_id: str


@dataclass(frozen=True)
class ListDriversQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class DriverDTO:
    id: str
    organization_id: str
    user_id: str
    license_no: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DriverSummaryDTO:
    """Lighter listing projection, mirroring `StudentSummaryDTO`/`ParentSummaryDTO`'s shape —
    `license_no` stands in for those DTOs' `full_name` as `Driver`'s own readable identifying
    field (`Driver` has no `full_name` of its own; that lives on the linked `iam.User`,
    `domain/entities.py`)."""

    id: str
    license_no: str
    status: str


def driver_to_dto(driver: Driver) -> DriverDTO:
    """Shared mapper — the only place a `Driver` aggregate is projected into its full DTO,
    mirroring `parent_to_dto`'s exact shape."""
    return DriverDTO(
        id=str(driver.id),
        organization_id=str(driver.organization_id),
        user_id=str(driver.user_id),
        license_no=driver.license_no,
        status=driver.status.value,
        created_at=driver.created_at,
        updated_at=driver.updated_at,
    )


def driver_to_summary_dto(driver: Driver) -> DriverSummaryDTO:
    """Shared mapper — the only place a `Driver` aggregate is projected into its summary DTO
    (`ListDriversQuery`'s read shape), mirroring `parent_to_summary_dto`'s exact shape.
    """
    return DriverSummaryDTO(
        id=str(driver.id), license_no=driver.license_no, status=driver.status.value
    )


@dataclass(frozen=True)
class GetRouteByIdQuery:
    route_id: str


@dataclass(frozen=True)
class ListRoutesQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class ListStopsForRouteQuery:
    route_id: str


@dataclass(frozen=True)
class StopDTO:
    id: str
    name: str
    latitude: float
    longitude: float
    sequence_no: int
    geofence_radius_m: int | None


@dataclass(frozen=True)
class RouteDTO:
    id: str
    organization_id: str
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    stops: tuple[StopDTO, ...]


@dataclass(frozen=True)
class RouteSummaryDTO:
    id: str
    name: str
    status: str


def stop_to_dto(stop: Stop) -> StopDTO:
    """Shared mapper — the only place a `Stop` child entity is projected into its DTO,
    mirroring `fleet_device.application.queries.camera_to_dto`'s identical shape."""
    return StopDTO(
        id=str(stop.id),
        name=stop.name,
        latitude=stop.latitude,
        longitude=stop.longitude,
        sequence_no=stop.sequence_no,
        geofence_radius_m=stop.geofence_radius_m,
    )


def route_to_dto(route: Route) -> RouteDTO:
    """Shared mapper — the only place a `Route` aggregate is projected into its full DTO,
    mirroring `fleet_device.application.queries.device_to_dto`'s identical shape (embedding
    the child-entity collection)."""
    return RouteDTO(
        id=str(route.id),
        organization_id=str(route.organization_id),
        name=route.name,
        status=route.status.value,
        created_at=route.created_at,
        updated_at=route.updated_at,
        stops=tuple(stop_to_dto(stop) for stop in route.stops),
    )


def route_to_summary_dto(route: Route) -> RouteSummaryDTO:
    """Shared mapper — the only place a `Route` aggregate is projected into its summary DTO
    (`ListRoutesQuery`'s read shape), mirroring `parent_to_summary_dto`'s exact shape.
    """
    return RouteSummaryDTO(id=str(route.id), name=route.name, status=route.status.value)


@dataclass(frozen=True)
class GetTripByIdQuery:
    trip_id: str


@dataclass(frozen=True)
class ListTripsQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class TripDTO:
    id: str
    organization_id: str
    vehicle_id: str
    driver_id: str
    route_id: str
    trip_type: str
    status: str
    scheduled_date: date
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class TripSummaryDTO:
    """Lighter listing projection, mirroring `DriverSummaryDTO`/`RouteSummaryDTO`'s shape."""

    id: str
    vehicle_id: str
    driver_id: str
    route_id: str
    trip_type: str
    status: str
    scheduled_date: date


def trip_to_dto(trip: Trip) -> TripDTO:
    """Shared mapper — the only place a `Trip` aggregate is projected into its full DTO,
    mirroring `route_to_dto`'s exact shape."""
    return TripDTO(
        id=str(trip.id),
        organization_id=str(trip.organization_id),
        vehicle_id=str(trip.vehicle_id),
        driver_id=str(trip.driver_id),
        route_id=str(trip.route_id),
        trip_type=trip.trip_type.value,
        status=trip.status.value,
        scheduled_date=trip.scheduled_date,
        started_at=trip.started_at,
        ended_at=trip.ended_at,
        created_at=trip.created_at,
        updated_at=trip.updated_at,
    )


def trip_to_summary_dto(trip: Trip) -> TripSummaryDTO:
    """Shared mapper — the only place a `Trip` aggregate is projected into its summary DTO
    (`ListTripsQuery`'s read shape), mirroring `route_to_summary_dto`'s exact shape.
    """
    return TripSummaryDTO(
        id=str(trip.id),
        vehicle_id=str(trip.vehicle_id),
        driver_id=str(trip.driver_id),
        route_id=str(trip.route_id),
        trip_type=trip.trip_type.value,
        status=trip.status.value,
        scheduled_date=trip.scheduled_date,
    )


@dataclass(frozen=True)
class GetStudentAssignmentByIdQuery:
    student_assignment_id: str


@dataclass(frozen=True)
class ListStudentAssignmentsQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class StudentAssignmentDTO:
    id: str
    organization_id: str
    student_id: str
    route_id: str
    pickup_stop_id: str
    dropoff_stop_id: str
    vehicle_id: str | None
    status: str
    assigned_at: datetime
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StudentAssignmentSummaryDTO:
    """Lighter listing projection, mirroring `TripSummaryDTO`'s shape."""

    id: str
    student_id: str
    route_id: str
    status: str


def student_assignment_to_dto(assignment: StudentAssignment) -> StudentAssignmentDTO:
    """Shared mapper — the only place a `StudentAssignment` aggregate is projected into its
    full DTO, mirroring `trip_to_dto`'s exact shape."""
    return StudentAssignmentDTO(
        id=str(assignment.id),
        organization_id=str(assignment.organization_id),
        student_id=str(assignment.student_id),
        route_id=str(assignment.route_id),
        pickup_stop_id=str(assignment.pickup_stop_id),
        dropoff_stop_id=str(assignment.dropoff_stop_id),
        vehicle_id=(
            str(assignment.vehicle_id) if assignment.vehicle_id is not None else None
        ),
        status=assignment.status.value,
        assigned_at=assignment.assigned_at,
        ended_at=assignment.ended_at,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def student_assignment_to_summary_dto(
    assignment: StudentAssignment,
) -> StudentAssignmentSummaryDTO:
    """Shared mapper — the only place a `StudentAssignment` aggregate is projected into its
    summary DTO (`ListStudentAssignmentsQuery`'s read shape), mirroring `trip_to_summary_dto`'s
    exact shape."""
    return StudentAssignmentSummaryDTO(
        id=str(assignment.id),
        student_id=str(assignment.student_id),
        route_id=str(assignment.route_id),
        status=assignment.status.value,
    )
