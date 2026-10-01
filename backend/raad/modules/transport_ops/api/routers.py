"""HTTP surface of the `transport_ops` module (C4) — Phase 10.4. `students_router` mounts at
`/api/v1/students` (`interfaces/http/api_v1.py`); `parents_router`/`routes_router`/
`trips_router` remain empty — Phase 10.1-10.3 built only the `Student` aggregate, and this
phase's own scope is the Student API only.

Thin controllers only (Backend LLD §16.2): parse the request DTO, call exactly one
`StudentApplicationService` method, return the response DTO. No business logic, no repository/
SQLAlchemy access, no aggregate manipulation — every error raised by the application/domain
layers already maps to the standard `ErrorEnvelope` via the global exception handlers
(`core/errors/handlers.py`, registered once in `main.py`); routers never build an error
response themselves. Mirrors `organization`/`fleet_device`/`tracking.api.routers`'s shape
exactly: every route below is authorization-gated via `require_permission`
(`interfaces/http/deps.py`), resolving against the real seeded RBAC permission matrix
(ADR-0004), per API Contracts §4.3's role column ("Org Admin") and §3.1's authorization
layering.

**Five routes, matching API Contracts §4.3's `/students` rows exactly** (lines 122-123):
- `POST /students` — enroll (the doc's uniform "`GET/POST /students`" create half)
- `GET /students` — list (the doc's uniform "`GET/POST /students`" list half) — the **first
  list endpoint in this codebase**: `iam`/`organization`/`fleet_device`/`tracking` all
  deliberately deferred their own `GET /x` (list) routes because no listing use-case existed
  in their Application layers yet. `transport_ops` is different: Phase 10.2 already built
  `ListStudentsQuery`/`list_students`, and Phase 10.3 already gave it a working (if
  tenant-*un*scoped — see that phase's own flagged gap, `infra/repositories.py`'s module
  docstring) infra implementation. Declining to expose it here would mean sitting on a
  complete, working use-case for no documented reason — so, unlike the precedent modules, this
  route **is** implemented, carrying the inherited scoping caveat forward via this docstring
  rather than silently presenting it as production-ready.
- `GET /students/{id}` — get by id (uniform CRUD, API Contracts §4 preamble)
- `PATCH /students/{id}` — update `full_name`/`external_ref` (uniform CRUD; see
  `UpdateStudentRequest`'s docstring for why `status` is not accepted here)
- `POST /students/{id}/status` — activate/disable/graduate/transfer, dispatched by the
  `status` value (API Contracts §4.3 line 123 verbatim; see `UpdateStudentStatusRequest`'s
  docstring for the `active`-is-also-accepted interpretation)

**Endpoints deliberately not implemented** (documented, not silently dropped):
- `DELETE /students/{id}` (uniform-CRUD soft delete, §4 preamble) — `Student` has no
  soft-delete domain behavior (Database Design §9 keeps soft delete and business status
  explicitly separate concepts, `deleted_at` vs. `status`); same deferral `iam`/`fleet_device`
  already apply to `DELETE /users`/`DELETE /vehicles`.

**Phase 10.6: `parents_router` — four routes, matching API Contracts §4.3's `/parents` row**
(line 124: `GET/POST /parents | Org Admin |`, no notes column, unlike `/students`' explicit
`/status` sub-route line):
- `POST /parents` — register
- `GET /parents` — list (same inherited unrestricted-`TenantRegionScope` caveat as
  `list_students`)
- `GET /parents/{id}` — get by id (uniform CRUD)
- `PATCH /parents/{id}` — update `full_name`/`phone`/`status` **together** — unlike
  `Student`'s split between a details-only `PATCH` and a dedicated `POST .../status` route,
  `Parent` has no documented behavioral status sub-route to dispatch to, so `status` folds
  into the uniform `PATCH` instead, mirroring `organization.api.routers.update_organization`/
  `fleet_device.api.routers.update_vehicle`'s status-in-PATCH shape (via
  `UpdateParentRequest`, which — like `iam.api.schemas.UpdateUserRequest` — composes multiple
  optional fields into one request, each independently dispatched, not atomically).
- `DELETE /parents/{id}` not implemented, for the identical reason `DELETE /students/{id}`
  isn't: `Parent` has no soft-delete domain behavior.

**Phase 10.7: Parent<->Student relationship — four routes, no documented API Contracts route
at all** (confirmed by re-reading §4.3 in full: the `/students`/`/parents` rows list no linking
sub-route, unlike `/routes/{id}/stops`'s documented "ordered stops" nesting). Modeled as nested
sub-resource collections under the two existing routers — the one documented precedent in this
same table for a child collection nested under a parent resource — rather than inventing a new
top-level `/student-parents` router:

- `POST /students/{student_id}/parents` — link (`students_router`) — body `{parent_id,
  relationship?, is_primary?}`. Cross-organization/duplicate/not-found rejections all surface
  through the standard error envelope automatically (`DomainError`/`ConflictError`/
  `NotFoundError` from `application/services.py` and `domain/entities.py`).
- `DELETE /students/{student_id}/parents/{parent_id}` — unlink (`students_router`) — the
  **first real `DELETE` in this module**: unlike `Student`/`Parent`'s deferred soft-delete,
  removing a link is a genuine deletion (`domain/entities.py`'s `StudentParent` docstring), so
  this is the correct semantics, not a gap being filled in.
- `GET /students/{student_id}/parents` — list a student's parents (`students_router`).
- `GET /parents/{parent_id}/students` — list a parent's students (`parents_router`).

**Phase 10.8: `drivers_router` — four routes, `/drivers` (Database Design §6.1, ADR-0001).
Flagged, not silently assumed: unlike `/students`/`/parents`, API Contracts §4.3 documents
*no* `/drivers` resource row at all** (re-read in full before implementing — the only
`Driver`-related rows are `/trips/{id}/driver` PATCH, `/trips/{id}/start`, `/trips/{id}/end`,
all `Trip`-aggregate concerns, not `Driver`-profile CRUD). Built anyway, for the same reason
Phase 10.7 built `StudentParent`'s routes despite an identical documentation gap: Database
Design §6.1 unambiguously defines the `drivers` table and ADR-0001 unambiguously assigns it to
this module, the task's own requirements explicitly ask for "FastAPI endpoints", and API
Contracts §4's own preamble establishes a *uniform CRUD pattern per resource* that this
resource simply isn't enumerated under (the `4.3` table is headed "(representative)" — not
exhaustive). This is a real documentation gap, reported here rather than silently decided:

- `POST /drivers` — register (uniform CRUD)
- `GET /drivers` — list (same inherited unrestricted-`TenantRegionScope` caveat as
  `list_students`/`list_parents`)
- `GET /drivers/{id}` — get by id (uniform CRUD)
- `PATCH /drivers/{id}` — update `license_no`/`status` together, mirroring `update_parent`'s
  exact shape (no dedicated behavioral status sub-route is documented for `/drivers` either)
- `DELETE /drivers/{id}` not implemented, for the identical reason `DELETE /students/{id}`/
  `DELETE /parents/{id}` aren't: `Driver` has no soft-delete domain behavior.

**Phase 11: `routes_router` — six routes, matching API Contracts §4.3's `/routes` rows.**
Unlike `Driver`/`StudentParent`, this phase's core routes **are** documented (line 125:
`GET/POST /routes | Org Admin |`; line 126: `GET/POST /routes/{id}/stops | Org Admin | ordered
stops`) — no documentation gap for these six:

- `POST /routes` — create (the doc's uniform "`GET/POST /routes`" create half)
- `GET /routes` — list (the doc's uniform "`GET/POST /routes`" list half; same inherited
  unrestricted-`TenantRegionScope` caveat as `list_students`/`list_parents`/`list_drivers`)
- `GET /routes/{id}` — get by id (uniform CRUD; embeds the route's ordered stops)
- `PATCH /routes/{id}` — update `name`/`status` together, mirroring `update_parent`'s exact
  shape (no dedicated behavioral status sub-route is documented for `/routes` either, and no
  `archived` status value exists to dispatch to — see `domain/entities.py`'s module docstring)
- `POST /routes/{route_id}/stops` — add a stop (API Contracts §4.3 line 126 verbatim: "ordered
  stops"). Returns the created `StopResponse`, mirroring `StudentParentLinkResponse`'s
  "POST-to-a-nested-collection returns the created child" shape (Phase 10.7) rather than the
  whole parent — the closer precedent here than `fleet_device`'s `register_camera` (which has
  no HTTP route at all to set a response-shape precedent from).
- `GET /routes/{route_id}/stops` — list a route's stops, already ordered by `sequence_no`
  (`domain/entities.py`'s `Route.stops` property).

**Documentation gap encountered and flagged, not silently decided:** API Contracts §4.3 line
126 documents only `GET/POST /routes/{id}/stops` for the stops sub-resource — no route exists
for updating, removing, or reordering an individual stop. `Route.remove_stop`/`Route.move_stop`
and their application-service/command counterparts (`application/services.py`,
`application/commands.py`) are fully implemented and unit-tested, but **no HTTP endpoint is
exposed for them this phase** — mirroring `fleet_device.api.routers`'s identical restraint for
`RegisterCameraCommand` ("routes are contract-driven, not capability-driven"). A future API
Contracts revision that documents `PATCH`/`DELETE /routes/{route_id}/stops/{stop_id}` can wire
these straight through with no domain/application change.

**Endpoints deliberately not implemented:**
- `DELETE /routes/{id}` (uniform-CRUD soft delete, §4 preamble) — `Route` has no soft-delete
  domain behavior, the identical deferral `DELETE /students/{id}`/`DELETE /parents/{id}`/
  `DELETE /drivers/{id}` already apply.

**Phase 12: `trips_router` — six routes.** Matches API Contracts §4.3 lines 129-132 for five of
them; the sixth (`GET /trips/{id}`) is this phase's own uniform-CRUD addition, flagged below:

- `POST /trips` — schedule (the doc's uniform "`GET/POST /trips`" create half; line 129, "Org
  Admin", "scheduled trips").
- `GET /trips` — list (the list half of the same line; same inherited unrestricted-
  `TenantRegionScope` caveat every other list endpoint in this module carries).
- `GET /trips/{id}` — get by id. Not literally itemized in §4.3's compact table (only
  `GET/POST /trips` appears), but every sibling resource in this module has this uniform-CRUD
  route (API Contracts §4 preamble) — built for the same reason `Driver`'s whole resource was,
  flagged here rather than silently assumed.
- `POST /trips/{id}/start` — line 130, **Driver (own)** → `TripStarted`. No request body (the
  documented "Trip start response" sample shows no request example).
- `POST /trips/{id}/end` — line 131, **Driver (own)** → `TripEnded`. No request body, same
  reasoning.
- `PATCH /trips/{id}/driver` — line 132, **Org Admin**, body `{driver_id}` verbatim — "change
  driver — no device change".

**`start`/`end` are this module's first "Driver (own)" routes** — every prior route in
`transport_ops` is Org-Admin-only. Driver-ownership is now verified (`_ensure_driver_owns_trip`,
below): `principal.user_id` is resolved against `trip.driver_id`'s linked `Driver.user_id`,
403 `FORBIDDEN` on a mismatch — a no-op for Org Admin, whose `transport_ops.trips.start`/`.end`
grant (the seeded matrix's blanket transport_ops CRUD bundle, ADR-0004) is an intentional
admin-override, not ownership-scoped.

**Not exposed this phase** (flagged, not silently dropped): `Trip.interrupt`/`resume`
(`InterruptTripCommand`/`ResumeTripCommand`) have no approved HTTP route — no documented
`/trips/{id}/interrupt` or `/trips/{id}/resume` path exists anywhere in API Contracts §4.3 —
mirroring `Route.remove_stop`/`move_stop`'s identical "use-case exists, no approved endpoint
yet" posture; a generic `PATCH /trips/{id}` and `DELETE /trips/{id}` — no field beyond `driver`
is documented as post-creation-editable, and `Trip` has no soft-delete domain behavior, the
identical deferral every other `DELETE` in this module already applies.

**Phase 13: `student_assignments_router` — four routes, matching API Contracts §4.3's
`/student-assignments` rows exactly (lines 127-128):**

- `POST /student-assignments` — assign (the doc's uniform "`GET/POST /student-assignments`"
  create half; line 127, "Org Admin", "the CR-1 gate record").
- `GET /student-assignments` — list (the list half of the same line; same inherited
  unrestricted-`TenantRegionScope` caveat every other list endpoint in this module carries).
- `GET /student-assignments/{id}` — get by id. Not literally itemized in §4.3's compact table
  (only `GET/POST /student-assignments` appears), but every sibling resource in this module has
  this uniform-CRUD route — built for the same reason `Trip`'s equivalent was, flagged here
  rather than silently assumed.
- `POST /student-assignments/{id}/end` — line 128 verbatim: "status→removed/transferred/… →
  CR-1 revocation event". Org Admin. Body `{status}`, dispatched to
  `remove`/`transfer`/`graduate`/`disable` exactly like `update_student_status` already
  dispatches `Student`'s own four-way status field — see `domain/entities.py`'s module docstring
  for the `event_type` collision this shares with `Student`'s own status events.

**Not exposed this phase:** a generic `PATCH /student-assignments/{id}` and
`DELETE /student-assignments/{id}` — no field is documented as post-creation-editable beyond
status (which has its own dedicated `/end` route, mirroring `Student`'s `/status` split), and no
soft-delete domain behavior exists, the identical deferral every other `DELETE` in this module
already applies.
"""

from __future__ import annotations

import dataclasses

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, status

from raad.core.errors.exceptions import (
    ConflictError,
    AuthorizationError,
    NotFoundError,
    ValidationError,
)
from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal, Role
from raad.interfaces.http.deps import (
    get_filter_conditions,
    get_offset_page_request,
    get_search_query,
    get_sort_params,
    require_permission,
)
from raad.interfaces.http.pagination import OffsetPageResponse, to_offset_page_response
from raad.modules.transport_ops.api.deps import (
    get_driver_service,
    get_parent_service,
    get_route_service,
    get_student_assignment_service,
    get_student_parent_service,
    get_student_service,
    get_transport_ops_uow,
    get_daily_operations_service,
    get_incident_service,
    get_transport_staff_service,
    get_trip_service,
)
from raad.modules.transport_ops.api.schemas import (
    AddStopToRouteRequest,
    AssignStaffToVehicleRequest,
    CancelTripRequest,
    IncidentNoteRequest,
    IncidentParentNoticeRequest,
    IncidentResponse,
    IncidentStatusRequest,
    RecordIncidentRequest,
    UpdateIncidentRequest,
    ClosureRequest,
    ClosureResponse,
    CoverRequest,
    CoverResponse,
    DailyBoardResponse,
    GenerateTripsRequest,
    GenerationResultResponse,
    TimetableEntryRequest,
    TimetableEntryResponse,
    UnavailabilityRequest,
    UnavailabilityResponse,
    ChangeTransportStaffStatusRequest,
    EndStaffAssignmentRequest,
    GrantDriverAccessRequest,
    RecordStaffDocumentRequest,
    RegisterTransportStaffRequest,
    StaffDocumentResponse,
    StaffDocumentTypeRequest,
    DocumentTypeImpactResponse,
    StaffComplianceRowResponse,
    StaffDocumentTypeResponse,
    StaffRoleRequest,
    StaffRoleResponse,
    StaffSetupDefaultsRequest,
    TransportStaffResponse,
    TransportStaffSummaryResponse,
    UpdateStaffDocumentRequest,
    UpdateTransportStaffRequest,
    VehicleStaffAssignmentResponse,
    AssignStudentToRouteRequest,
    ChangeTripDriverRequest,
    CountResponse,
    CreateRouteRequest,
    DriverCreatedResponse,
    DriverResponse,
    DriverSummaryResponse,
    EnrollStudentRequest,
    LinkParentToStudentRequest,
    ParentCreatedResponse,
    ParentForStudentResponse,
    ParentResponse,
    ParentSummaryResponse,
    RegisterDriverRequest,
    RegisterParentRequest,
    RouteResponse,
    RouteSummaryResponse,
    ScheduleTripRequest,
    SetFamilyTransportationRequest,
    SetFamilyTransportationResponse,
    StopResponse,
    StudentAssignmentResponse,
    StudentAssignmentSummaryResponse,
    StudentForParentResponse,
    StudentParentLinkResponse,
    StudentResponse,
    StudentSummaryResponse,
    TripResponse,
    TripSummaryResponse,
    UpdateDriverRequest,
    UpdateParentRequest,
    UpdateParentVideoAccessRequest,
    UpdateRouteRequest,
    UpdateStudentAssignmentStatusRequest,
    UpdateStudentRequest,
    UpdateStudentStatusRequest,
)
from raad.modules.transport_ops.application.commands import (
    AddDefaultStaffSetupCommand,
    CancelTripCommand,
    CreateCoverCommand,
    GenerateTripsCommand,
    RecordClosureCommand,
    RecordUnavailabilityCommand,
    SaveTimetableEntryCommand,
    AssignStaffToVehicleCommand,
    ChangeTransportStaffStatusCommand,
    EndStaffAssignmentCommand,
    GrantDriverAccessCommand,
    RecordStaffDocumentCommand,
    RegisterTransportStaffCommand,
    SaveStaffDocumentTypeCommand,
    SaveStaffRoleCommand,
    UpdateStaffDocumentCommand,
    UpdateTransportStaffCommand,
    ActivateDriverCommand,
    ActivateParentCommand,
    ActivateRouteCommand,
    ActivateStudentCommand,
    AddStopToRouteCommand,
    AssignStudentToRouteCommand,
    ChangeTripDriverCommand,
    ChildEnrollmentSpec,
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
    GrantParentVideoLiveAccessCommand,
    GrantParentVideoPlaybackAccessCommand,
    LinkParentToStudentCommand,
    RegisterDriverCommand,
    RegisterParentCommand,
    RegisterParentWithChildrenCommand,
    RemoveStudentAssignmentCommand,
    RevokeParentVideoLiveAccessCommand,
    RevokeParentVideoPlaybackAccessCommand,
    ScheduleTripCommand,
    SetFamilyTransportationCommand,
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
    CoverDTO,
    ListTransportStaffQuery,
    UnavailabilityDTO,
    StaffDocumentDTO,
    StaffDocumentTypeDTO,
    TransportStaffDTO,
    TransportStaffRoleDTO,
    TransportStaffSummaryDTO,
    VehicleStaffAssignmentDTO,
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
)
from raad.modules.tracking.api.deps import (
    get_safety_alert_service,
    get_scoped_tracking_uow,
    get_scoped_tracking_uow_fresh,
)
from raad.modules.tracking.application.ports import TrackingUnitOfWork
from raad.modules.tracking.application.safety_services import SafetyAlertApplicationService
from raad.modules.transport_ops.application.incident_services import (
    IncidentApplicationService,
    IncidentDTO,
    RecordIncidentCommand,
)
from raad.modules.transport_ops.application.operations_services import (
    DailyOperationsApplicationService,
)
from raad.modules.transport_ops.application.staff_services import (
    TransportStaffApplicationService,
)
from raad.modules.transport_ops.application.services import (
    DriverApplicationService,
    ParentApplicationService,
    RouteApplicationService,
    StudentApplicationService,
    StudentAssignmentApplicationService,
    StudentParentApplicationService,
    TripApplicationService,
)

students_router = APIRouter()
parents_router = APIRouter()
routes_router = APIRouter()
trips_router = APIRouter()
drivers_router = APIRouter()
student_assignments_router = APIRouter()


def _student_dto_to_response(student: StudentDTO) -> StudentResponse:
    return StudentResponse(
        id=student.id,
        organization_id=student.organization_id,
        full_name=student.full_name,
        external_ref=student.external_ref,
        status=student.status,
        created_at=student.created_at,
        updated_at=student.updated_at,
        date_of_birth=student.date_of_birth,
        gender=student.gender,
        notes=student.notes,
    )


def _student_summary_dto_to_response(
    student: StudentSummaryDTO,
) -> StudentSummaryResponse:
    return StudentSummaryResponse(
        id=student.id, full_name=student.full_name, status=student.status
    )


def _parent_dto_to_response(parent: ParentDTO) -> ParentResponse:
    return ParentResponse(
        id=parent.id,
        organization_id=parent.organization_id,
        user_id=parent.user_id,
        full_name=parent.full_name,
        phone=parent.phone,
        status=parent.status,
        has_video_live_access=parent.has_video_live_access,
        has_video_playback_access=parent.has_video_playback_access,
        created_at=parent.created_at,
        updated_at=parent.updated_at,
        alternate_phone=parent.alternate_phone,
        address=parent.address,
        emergency_contact_name=parent.emergency_contact_name,
        emergency_contact_phone=parent.emergency_contact_phone,
        notes=parent.notes,
    )


def _parent_summary_dto_to_response(
    parent: ParentSummaryDTO,
) -> ParentSummaryResponse:
    return ParentSummaryResponse(
        id=parent.id, full_name=parent.full_name, status=parent.status
    )


def _student_parent_dto_to_response(
    link: StudentParentDTO,
) -> StudentParentLinkResponse:
    return StudentParentLinkResponse(
        student_id=link.student_id,
        parent_id=link.parent_id,
        relationship=link.relationship,
        is_primary=link.is_primary,
    )


def _parent_for_student_dto_to_response(
    dto: ParentForStudentDTO,
) -> ParentForStudentResponse:
    return ParentForStudentResponse(
        parent_id=dto.parent_id,
        full_name=dto.full_name,
        phone=dto.phone,
        status=dto.status,
        relationship=dto.relationship,
        is_primary=dto.is_primary,
    )


def _student_for_parent_dto_to_response(
    dto: StudentForParentDTO,
) -> StudentForParentResponse:
    return StudentForParentResponse(
        student_id=dto.student_id,
        full_name=dto.full_name,
        status=dto.status,
        relationship=dto.relationship,
        is_primary=dto.is_primary,
        date_of_birth=dto.date_of_birth,
    )


def _driver_dto_to_response(driver: DriverDTO) -> DriverResponse:
    return DriverResponse(
        id=driver.id,
        organization_id=driver.organization_id,
        user_id=driver.user_id,
        license_no=driver.license_no,
        status=driver.status,
        created_at=driver.created_at,
        updated_at=driver.updated_at,
        staff_id=driver.staff_id,
    )


def _driver_summary_dto_to_response(
    driver: DriverSummaryDTO,
) -> DriverSummaryResponse:
    return DriverSummaryResponse(
        id=driver.id,
        license_no=driver.license_no,
        status=driver.status,
        staff_id=driver.staff_id,
        full_name=driver.full_name,
    )


def _stop_dto_to_response(stop: StopDTO) -> StopResponse:
    return StopResponse(
        id=stop.id,
        name=stop.name,
        latitude=stop.latitude,
        longitude=stop.longitude,
        sequence_no=stop.sequence_no,
        geofence_radius_m=stop.geofence_radius_m,
    )


def _route_dto_to_response(route: RouteDTO) -> RouteResponse:
    return RouteResponse(
        id=route.id,
        organization_id=route.organization_id,
        name=route.name,
        status=route.status,
        created_at=route.created_at,
        updated_at=route.updated_at,
        stops=[_stop_dto_to_response(stop) for stop in route.stops],
    )


def _route_summary_dto_to_response(route: RouteSummaryDTO) -> RouteSummaryResponse:
    return RouteSummaryResponse(id=route.id, name=route.name, status=route.status)


def _trip_dto_to_response(trip: TripDTO) -> TripResponse:
    return TripResponse(
        id=trip.id,
        organization_id=trip.organization_id,
        vehicle_id=trip.vehicle_id,
        driver_id=trip.driver_id,
        route_id=trip.route_id,
        trip_type=trip.trip_type,
        status=trip.status,
        scheduled_date=trip.scheduled_date,
        started_at=trip.started_at,
        ended_at=trip.ended_at,
        created_at=trip.created_at,
        updated_at=trip.updated_at,
        timetable_entry_id=trip.timetable_entry_id,
        planned_departure=trip.planned_departure,
        cancelled_at=trip.cancelled_at,
        cancelled_reason=trip.cancelled_reason,
        warnings=list(trip.warnings),
    )


def _trip_summary_dto_to_response(trip: TripSummaryDTO) -> TripSummaryResponse:
    return TripSummaryResponse(
        id=trip.id,
        vehicle_id=trip.vehicle_id,
        driver_id=trip.driver_id,
        route_id=trip.route_id,
        trip_type=trip.trip_type,
        status=trip.status,
        scheduled_date=trip.scheduled_date,
        planned_departure=trip.planned_departure,
    )


def _student_assignment_dto_to_response(
    assignment: StudentAssignmentDTO,
) -> StudentAssignmentResponse:
    return StudentAssignmentResponse(
        id=assignment.id,
        organization_id=assignment.organization_id,
        student_id=assignment.student_id,
        route_id=assignment.route_id,
        pickup_stop_id=assignment.pickup_stop_id,
        dropoff_stop_id=assignment.dropoff_stop_id,
        vehicle_id=assignment.vehicle_id,
        status=assignment.status,
        assigned_at=assignment.assigned_at,
        ended_at=assignment.ended_at,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _student_assignment_summary_dto_to_response(
    assignment: StudentAssignmentSummaryDTO,
) -> StudentAssignmentSummaryResponse:
    return StudentAssignmentSummaryResponse(
        id=assignment.id,
        student_id=assignment.student_id,
        route_id=assignment.route_id,
        status=assignment.status,
    )


@students_router.post(
    "",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll a new student",
    description=(
        "Org Admin (API Contracts §4.3). Authorization uses `require_permission`, resolving "
        "against the real seeded RBAC permission matrix (ADR-0004), matching "
        "`organization`/`fleet_device`'s posture."
    ),
)
async def enroll_student(
    body: EnrollStudentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.students.create"))
    ),
    student_service: StudentApplicationService = Depends(get_student_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentResponse:
    command = EnrollStudentCommand(
        organization_id=body.organization_id,
        full_name=body.full_name,
        external_ref=body.external_ref,
        actor=principal,
        date_of_birth=body.date_of_birth,
        gender=body.gender,
        notes=body.notes,
    )
    student = await student_service.enroll_student(command, uow=uow)
    return _student_dto_to_response(student)


@students_router.get(
    "",
    response_model=OffsetPageResponse[StudentSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List students",
    description=(
        "Org Admin (API Contracts §4.3). Not yet tenant-scoped — see this module's own "
        "docstring and `infra/repositories.py`'s (Phase 10.3): `list_page` uses an "
        "unrestricted `TenantRegionScope` pending a system-wide `ScopeResolver` binding. "
        "Paginated/filterable/sortable per §7/§8. Authorization resolves against the real "
        "seeded RBAC permission matrix — see `enroll_student`'s note."
    ),
)
async def list_students(
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.students.list"))
    ),
    student_service: StudentApplicationService = Depends(get_student_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[StudentSummaryResponse]:
    page = await student_service.list_students(
        ListStudentsQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _student_summary_dto_to_response)


@students_router.get(
    "/count",
    response_model=CountResponse,
    status_code=status.HTTP_200_OK,
    summary="Total student count (no row data)",
    description=(
        "RAAD business model realignment: `transport_ops.students.count`, held by "
        "founder/regional_manager/support_staff (migration granting this permission) — "
        "distinct from `.list`, which those roles no longer hold (migration `c4d9a2e6f813`). "
        "Backs the RAAD Platform's aggregated-statistics KPI strip ('Total Students (count "
        "only)') without exposing individual student rows. Reuses `list_students` internally "
        "(`page_size=1`) and returns only its `.total` — no new query logic."
    ),
)
async def count_students(
    organization_id: str | None = Query(
        default=None,
        description=(
            "Narrow the count to one organization. Omit for the platform-wide total, "
            "which is what the RAAD dashboard KPI strip uses."
        ),
    ),
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.students.count"))
    ),
    student_service: StudentApplicationService = Depends(get_student_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> CountResponse:
    filters = (
        [FilterCondition(field="organization_id", op="eq", value=organization_id)]
        if organization_id
        else []
    )
    page = await student_service.list_students(
        ListStudentsQuery(
            page_request=OffsetPageRequest(page=1, page_size=1), filters=filters
        ),
        uow=uow,
    )
    return CountResponse(total=page.total)


@students_router.get(
    "/{student_id}",
    response_model=StudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a student by id",
    description=(
        "Org Admin (API Contracts §4.3/§4 uniform CRUD). Authorization resolves against the "
        "real seeded RBAC permission matrix — see `enroll_student`'s note."
    ),
)
async def get_student(
    student_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.students.read"))
    ),
    student_service: StudentApplicationService = Depends(get_student_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentResponse:
    student = await student_service.get_student_by_id(
        GetStudentByIdQuery(student_id=student_id), uow=uow
    )
    return _student_dto_to_response(student)


@students_router.patch(
    "/{student_id}",
    response_model=StudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a student's details",
    description=(
        "Org Admin (API Contracts §4 uniform CRUD). Limited to `full_name`/`external_ref` — "
        "see `UpdateStudentRequest`'s docstring for why `status` is not accepted here. "
        "Authorization resolves against the real seeded RBAC permission matrix — see "
        "`enroll_student`'s note."
    ),
)
async def update_student(
    student_id: str,
    body: UpdateStudentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.students.update"))
    ),
    student_service: StudentApplicationService = Depends(get_student_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentResponse:
    if (
        body.full_name is None
        and body.external_ref is None
        and body.date_of_birth is None
        and body.gender is None
        and body.notes is None
    ):
        raise ValidationError(
            "At least one of 'full_name', 'external_ref', 'date_of_birth', 'gender' or "
            "'notes' must be provided.",
            details={
                "fields": ["full_name", "external_ref", "date_of_birth", "gender", "notes"]
            },
        )

    current = await student_service.get_student_by_id(
        GetStudentByIdQuery(student_id=student_id), uow=uow
    )
    command = UpdateStudentCommand(
        student_id=student_id,
        full_name=body.full_name if body.full_name is not None else current.full_name,
        external_ref=(
            body.external_ref if body.external_ref is not None else current.external_ref
        ),
        date_of_birth=(
            body.date_of_birth if body.date_of_birth is not None else current.date_of_birth
        ),
        gender=body.gender if body.gender is not None else current.gender,
        notes=body.notes if body.notes is not None else current.notes,
        actor=principal,
    )
    student = await student_service.update_student(command, uow=uow)
    return _student_dto_to_response(student)


@students_router.post(
    "/{student_id}/status",
    response_model=StudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Transition a student's status",
    description=(
        "Org Admin — body `{status}` -> disable/graduate/transfer -> emits CR-1 revocation "
        "(API Contracts §4.3 line 123 verbatim). `active` is also accepted, reaching "
        "`StudentApplicationService.activate_student` — see `UpdateStudentStatusRequest`'s "
        "docstring. Authorization resolves against the real seeded RBAC permission matrix "
        "— see `enroll_student`'s note."
    ),
)
async def update_student_status(
    student_id: str,
    body: UpdateStudentStatusRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.students.update_status"))
    ),
    student_service: StudentApplicationService = Depends(get_student_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentResponse:
    if body.status == "active":
        student = await student_service.activate_student(
            ActivateStudentCommand(student_id=student_id, actor=principal), uow=uow
        )
    elif body.status == "disabled":
        student = await student_service.disable_student(
            DisableStudentCommand(student_id=student_id, actor=principal), uow=uow
        )
    elif body.status == "graduated":
        student = await student_service.graduate_student(
            GraduateStudentCommand(student_id=student_id, actor=principal), uow=uow
        )
    elif body.status == "transferred":
        student = await student_service.transfer_student(
            TransferStudentCommand(student_id=student_id, actor=principal), uow=uow
        )
    else:
        raise ValidationError(
            f"Unsupported status: {body.status!r}", details={"field": "status"}
        )

    return _student_dto_to_response(student)


@parents_router.post(
    "",
    response_model=ParentCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new parent",
    description=(
        "Org Admin (API Contracts §4.3). Authorization uses `require_permission`, resolving "
        "against the real seeded RBAC permission matrix (ADR-0004), matching "
        "`enroll_student`'s posture. ADR-0003 (accepted): also provisions the linked "
        "`iam.User` (role=parent) with a generated one-time temporary password, returned here "
        "exactly once for hand-off — never re-derivable via `GET /parents/{id}`."
    ),
)
async def register_parent(
    body: RegisterParentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.parents.create"))
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentCreatedResponse:
    if body.children is not None:
        # ADR-0041 §2: the Parent + every listed child, created and linked in one transaction.
        with_children_command = RegisterParentWithChildrenCommand(
            organization_id=body.organization_id,
            full_name=body.full_name,
            email=body.email,
            phone=body.phone,
            actor=principal,
            alternate_phone=body.alternate_phone,
            address=body.address,
            emergency_contact_name=body.emergency_contact_name,
            emergency_contact_phone=body.emergency_contact_phone,
            notes=body.notes,
            children=[
                ChildEnrollmentSpec(
                    full_name=child.full_name,
                    external_ref=child.external_ref,
                    date_of_birth=child.date_of_birth,
                    gender=child.gender,
                    notes=child.notes,
                    relationship=child.relationship,
                    is_primary=child.is_primary,
                )
                for child in body.children
            ],
            route_id=body.route_id,
            pickup_stop_id=body.pickup_stop_id,
            dropoff_stop_id=body.dropoff_stop_id,
            vehicle_id=body.vehicle_id,
        )
        parent, children, temporary_password = await parent_service.register_parent_with_children(
            with_children_command, uow=uow
        )
        return ParentCreatedResponse(
            parent=_parent_dto_to_response(parent),
            temporary_password=temporary_password,
            children=[_student_dto_to_response(child) for child in children],
        )

    command = RegisterParentCommand(
        organization_id=body.organization_id,
        full_name=body.full_name,
        email=body.email,
        phone=body.phone,
        actor=principal,
        alternate_phone=body.alternate_phone,
        address=body.address,
        emergency_contact_name=body.emergency_contact_name,
        emergency_contact_phone=body.emergency_contact_phone,
        notes=body.notes,
    )
    parent, temporary_password = await parent_service.register_parent(command, uow=uow)
    return ParentCreatedResponse(
        parent=_parent_dto_to_response(parent), temporary_password=temporary_password
    )


@parents_router.get(
    "",
    response_model=OffsetPageResponse[ParentSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List parents",
    description=(
        "Org Admin (API Contracts §4.3). Not yet tenant-scoped — same inherited caveat as "
        "`list_students`; see this module's own docstring and `infra/repositories.py`'s "
        "(Phase 10.3). Paginated/filterable/sortable per §7/§8. Authorization resolves "
        "against the real seeded RBAC permission matrix."
    ),
)
async def list_parents(
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.parents.list"))
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[ParentSummaryResponse]:
    page = await parent_service.list_parents(
        ListParentsQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _parent_summary_dto_to_response)


@parents_router.get(
    "/count",
    response_model=CountResponse,
    status_code=status.HTTP_200_OK,
    summary="Total parent count (no row data)",
    description=(
        "RAAD business model realignment: `transport_ops.parents.count`, held by "
        "founder/regional_manager/support_staff — distinct from `.list`, which those roles no "
        "longer hold (migration `c4d9a2e6f813`). Backs the RAAD Platform's aggregated-"
        "statistics KPI strip ('Total Parents (count only)') without exposing individual "
        "parent rows. Reuses `list_parents` internally (`page_size=1`) and returns only its "
        "`.total` — no new query logic. See `count_students`'s identical note."
    ),
)
async def count_parents(
    organization_id: str | None = Query(
        default=None,
        description=(
            "Narrow the count to one organization. Omit for the platform-wide total, "
            "which is what the RAAD dashboard KPI strip uses."
        ),
    ),
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.parents.count"))
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> CountResponse:
    filters = (
        [FilterCondition(field="organization_id", op="eq", value=organization_id)]
        if organization_id
        else []
    )
    page = await parent_service.list_parents(
        ListParentsQuery(
            page_request=OffsetPageRequest(page=1, page_size=1), filters=filters
        ),
        uow=uow,
    )
    return CountResponse(total=page.total)


@parents_router.get(
    "/{parent_id}",
    response_model=ParentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a parent by id",
    description=(
        "Org Admin (API Contracts §4.3/§4 uniform CRUD). Authorization resolves against the "
        "real seeded RBAC permission matrix — see `register_parent`'s note."
    ),
)
async def get_parent(
    parent_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.parents.read"))
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentResponse:
    parent = await parent_service.get_parent_by_id(
        GetParentByIdQuery(parent_id=parent_id), uow=uow
    )
    return _parent_dto_to_response(parent)


@parents_router.patch(
    "/{parent_id}",
    response_model=ParentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a parent's details and/or status",
    description=(
        "Org Admin (API Contracts §4 uniform CRUD). Composes `full_name`/`phone` (dispatched "
        "to `update_parent`) and `status` (dispatched to `activate_parent`/`disable_parent`) "
        "in one request, each independently — not atomically — mirroring "
        "`iam.api.routers.update_user`'s identical composition. See `UpdateParentRequest`'s "
        "docstring for why `status` is folded in here rather than a dedicated route, unlike "
        "`Student`. Authorization resolves against the real seeded RBAC permission matrix."
    ),
)
async def update_parent(
    parent_id: str,
    body: UpdateParentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.parents.update"))
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentResponse:
    _profile_fields = (
        body.full_name,
        body.phone,
        body.alternate_phone,
        body.address,
        body.emergency_contact_name,
        body.emergency_contact_phone,
        body.notes,
    )
    if all(field is None for field in _profile_fields) and body.status is None:
        raise ValidationError(
            "At least one of 'full_name', 'phone', 'alternate_phone', 'address', "
            "'emergency_contact_name', 'emergency_contact_phone', 'notes', or 'status' must "
            "be provided.",
            details={
                "fields": [
                    "full_name",
                    "phone",
                    "alternate_phone",
                    "address",
                    "emergency_contact_name",
                    "emergency_contact_phone",
                    "notes",
                    "status",
                ]
            },
        )

    parent: ParentDTO | None = None

    if any(field is not None for field in _profile_fields):
        current = await parent_service.get_parent_by_id(
            GetParentByIdQuery(parent_id=parent_id), uow=uow
        )
        command = UpdateParentCommand(
            parent_id=parent_id,
            full_name=(
                body.full_name if body.full_name is not None else current.full_name
            ),
            phone=body.phone if body.phone is not None else current.phone,
            actor=principal,
            alternate_phone=(
                body.alternate_phone
                if body.alternate_phone is not None
                else current.alternate_phone
            ),
            address=body.address if body.address is not None else current.address,
            emergency_contact_name=(
                body.emergency_contact_name
                if body.emergency_contact_name is not None
                else current.emergency_contact_name
            ),
            emergency_contact_phone=(
                body.emergency_contact_phone
                if body.emergency_contact_phone is not None
                else current.emergency_contact_phone
            ),
            notes=body.notes if body.notes is not None else current.notes,
        )
        parent = await parent_service.update_parent(command, uow=uow)

    if body.status is not None:
        if body.status == "active":
            parent = await parent_service.activate_parent(
                ActivateParentCommand(parent_id=parent_id, actor=principal), uow=uow
            )
        elif body.status == "inactive":
            parent = await parent_service.disable_parent(
                DisableParentCommand(parent_id=parent_id, actor=principal), uow=uow
            )
        else:
            raise ValidationError(
                f"Unsupported status: {body.status!r}", details={"field": "status"}
            )

    if parent is None:
        # Guaranteed not to happen by the "at least one field" guard above — an explicit
        # raise rather than `assert`, matching `iam.api.routers.update_user`'s identical
        # invariant-holds-regardless-of-interpreter-flags reasoning.
        raise RuntimeError(
            "update_parent: no field was processed despite the guard above."
        )
    return _parent_dto_to_response(parent)


@parents_router.patch(
    "/{parent_id}/video-access",
    response_model=ParentResponse,
    status_code=status.HTTP_200_OK,
    summary="Grant or revoke a parent's video access",
    description=(
        "Org Admin (+ Founder) only (ADR-0026 SS2) - a dedicated, more restrictive permission "
        "than `PATCH /parents/{id}` (`transport_ops.parents.grant_video_access`, not "
        "`.update`). Off by default for every parent; this is the only way either flag ever "
        "becomes `true`. Live and playback are independently grantable/revocable."
    ),
)
async def update_parent_video_access(
    parent_id: str,
    body: UpdateParentVideoAccessRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.parents.grant_video_access"))
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ParentResponse:
    if body.has_video_live_access is None and body.has_video_playback_access is None:
        raise ValidationError(
            "At least one of 'has_video_live_access' or 'has_video_playback_access' must be "
            "provided.",
            details={"fields": ["has_video_live_access", "has_video_playback_access"]},
        )

    parent: ParentDTO | None = None

    if body.has_video_live_access is True:
        parent = await parent_service.grant_parent_video_live_access(
            GrantParentVideoLiveAccessCommand(parent_id=parent_id, actor=principal), uow=uow
        )
    elif body.has_video_live_access is False:
        parent = await parent_service.revoke_parent_video_live_access(
            RevokeParentVideoLiveAccessCommand(parent_id=parent_id, actor=principal), uow=uow
        )

    if body.has_video_playback_access is True:
        parent = await parent_service.grant_parent_video_playback_access(
            GrantParentVideoPlaybackAccessCommand(parent_id=parent_id, actor=principal), uow=uow
        )
    elif body.has_video_playback_access is False:
        parent = await parent_service.revoke_parent_video_playback_access(
            RevokeParentVideoPlaybackAccessCommand(parent_id=parent_id, actor=principal), uow=uow
        )

    if parent is None:
        # Guaranteed not to happen by the "at least one field" guard above - an explicit raise
        # rather than `assert`, matching `update_parent`'s own identical invariant-holds-
        # regardless-of-interpreter-flags reasoning.
        raise RuntimeError(
            "update_parent_video_access: no field was processed despite the guard above."
        )
    return _parent_dto_to_response(parent)


@parents_router.put(
    "/{parent_id}/transportation",
    response_model=SetFamilyTransportationResponse,
    status_code=status.HTTP_200_OK,
    summary="Set or change a family's transportation assignment",
    description=(
        "Org Admin. 2026-09-12 business-model correction: RAAD's 'one Parent/family = one bus' "
        "rule, made structural — the family's route/pickup stop/dropoff stop/vehicle is set "
        "once here and applied identically to every one of this Parent's currently-linked "
        "children, replacing each child's own current active assignment (if any) with a fresh "
        "one against the new values, all in one transaction. Reuses "
        "`transport_ops.student_assignments.create` (no new permission/migration) — the "
        "underlying effect is still 'create a StudentAssignment', just for every linked child "
        "at once rather than one student at a time. A Parent with no linked children yet "
        "returns an empty `assignments` list, not an error."
    ),
)
async def set_family_transportation(
    parent_id: str,
    body: SetFamilyTransportationRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_assignments.create"))
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> SetFamilyTransportationResponse:
    command = SetFamilyTransportationCommand(
        parent_id=parent_id,
        route_id=body.route_id,
        pickup_stop_id=body.pickup_stop_id,
        dropoff_stop_id=body.dropoff_stop_id,
        vehicle_id=body.vehicle_id,
        actor=principal,
    )
    assignments = await parent_service.set_family_transportation(command, uow=uow)
    return SetFamilyTransportationResponse(
        assignments=[
            _student_assignment_dto_to_response(assignment) for assignment in assignments
        ]
    )


@students_router.post(
    "/{student_id}/parents",
    response_model=StudentParentLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link a parent to a student",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.7 — see `routers.py`'s "
        "module docstring). Rejects cross-organization links (`DomainError`) and duplicate "
        "links (`ConflictError`, both from `StudentParent.link`/`application/validators.py`). "
        "Authorization resolves against the real seeded RBAC permission matrix — see "
        "`enroll_student`'s note."
    ),
)
async def link_parent_to_student(
    student_id: str,
    body: LinkParentToStudentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_parents.create"))
    ),
    student_parent_service: StudentParentApplicationService = Depends(
        get_student_parent_service
    ),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentParentLinkResponse:
    command = LinkParentToStudentCommand(
        student_id=student_id,
        parent_id=body.parent_id,
        relationship=body.relationship,
        is_primary=body.is_primary,
        actor=principal,
    )
    link = await student_parent_service.link_parent_to_student(command, uow=uow)
    return _student_parent_dto_to_response(link)


@students_router.delete(
    "/{student_id}/parents/{parent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a parent-student link",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.7). A real deletion, unlike "
        "every other `DELETE` in this module (both currently unimplemented, see "
        "`StudentParent`'s docstring for why this one differs). Authorization resolves "
        "against the real seeded RBAC permission matrix."
    ),
)
async def unlink_parent_from_student(
    student_id: str,
    parent_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_parents.delete"))
    ),
    student_parent_service: StudentParentApplicationService = Depends(
        get_student_parent_service
    ),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> None:
    command = UnlinkParentFromStudentCommand(
        student_id=student_id, parent_id=parent_id, actor=principal
    )
    await student_parent_service.unlink_parent_from_student(command, uow=uow)


@students_router.get(
    "/{student_id}/parents",
    response_model=list[ParentForStudentResponse],
    status_code=status.HTTP_200_OK,
    summary="List a student's linked parents",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.7). Authorization resolves "
        "against the real seeded RBAC permission matrix."
    ),
)
async def list_parents_for_student(
    student_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_parents.list"))
    ),
    student_parent_service: StudentParentApplicationService = Depends(
        get_student_parent_service
    ),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[ParentForStudentResponse]:
    results = await student_parent_service.list_parents_for_student(
        ListParentsForStudentQuery(student_id=student_id), uow=uow
    )
    return [_parent_for_student_dto_to_response(dto) for dto in results]


@parents_router.get(
    "/{parent_id}/students",
    response_model=list[StudentForParentResponse],
    status_code=status.HTTP_200_OK,
    summary="List a parent's linked students",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.7). Authorization resolves "
        "against the real seeded RBAC permission matrix."
    ),
)
async def list_students_for_parent(
    parent_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_parents.list"))
    ),
    student_parent_service: StudentParentApplicationService = Depends(
        get_student_parent_service
    ),
    parent_service: ParentApplicationService = Depends(get_parent_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StudentForParentResponse]:
    # Audit finding B12 — defence in depth against a cross-parent leak.
    #
    # This route takes `parent_id` straight from the URL and, until now, checked nothing about
    # whose parent record it named. It is safe *today* only because of a fact outside this
    # function: `transport_ops.student_parents.list` happens to be held by
    # founder/regional_manager/support_staff/org_admin and NOT by `parent` — so no caller who
    # could abuse it can currently reach it. That is an accident of the RBAC matrix, not a
    # property of this code, and a single future grant would turn it into a live IDOR silently.
    #
    # ADR-0023 closed this class of bug *structurally* for the parent-facing path by giving
    # `/me/students` no client-supplied identifier at all. This route keeps its path parameter
    # (staff legitimately query any parent in their scope), so it gets an explicit check instead:
    # a PARENT caller may only ever read their own record.
    #
    # `NotFoundError` (404), never `AuthorizationError` (403) — this codebase's established
    # convention for out-of-scope resource access (`resolve_cr1_decision`, ADR-0021), so a
    # probing caller cannot distinguish "exists but not yours" from "does not exist".
    #
    # Cross-*tenant* access is already closed independently by ADR-0021's repository scoping;
    # this closes the cross-*parent*, same-tenant case that scoping alone cannot see.
    if principal.role is Role.PARENT:
        own = await parent_service.get_parent_by_user_id(principal.user_id, uow=uow)
        if own is None or own.id != parent_id:
            raise NotFoundError(f"Parent {parent_id} not found.")

    results = await student_parent_service.list_students_for_parent(
        ListStudentsForParentQuery(parent_id=parent_id), uow=uow
    )
    return [_student_for_parent_dto_to_response(dto) for dto in results]


@drivers_router.post(
    "",
    response_model=DriverCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new driver",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.8 — see this module's own "
        "docstring for the full gap: Database Design §6.1/ADR-0001 define the `drivers` table "
        "and its ownership unambiguously, but API Contracts §4.3 lists no `/drivers` resource "
        "row). Authorization uses `require_permission`, resolving against the real seeded "
        "RBAC permission matrix (ADR-0004), matching `enroll_student`'s posture. ADR-0003 "
        "(accepted): also provisions the linked `iam.User` (role=driver) with a generated "
        "one-time temporary password, returned here exactly once for hand-off."
    ),
)
async def register_driver(
    body: RegisterDriverRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.drivers.create"))
    ),
    driver_service: DriverApplicationService = Depends(get_driver_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> DriverCreatedResponse:
    command = RegisterDriverCommand(
        organization_id=body.organization_id,
        full_name=body.full_name,
        email=body.email,
        phone=body.phone,
        license_no=body.license_no,
        actor=principal,
    )
    driver, temporary_password = await driver_service.register_driver(command, uow=uow)
    return DriverCreatedResponse(
        driver=_driver_dto_to_response(driver), temporary_password=temporary_password
    )


@drivers_router.get(
    "",
    response_model=OffsetPageResponse[DriverSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List drivers",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.8, see this module's own "
        "docstring). Not yet tenant-scoped — same inherited caveat as `list_students`/"
        "`list_parents`. Paginated/filterable/sortable per §7/§8. Authorization resolves "
        "against the real seeded RBAC permission matrix."
    ),
)
async def list_drivers(
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.drivers.list"))
    ),
    driver_service: DriverApplicationService = Depends(get_driver_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[DriverSummaryResponse]:
    page = await driver_service.list_drivers(
        ListDriversQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _driver_summary_dto_to_response)


@drivers_router.get(
    "/{driver_id}",
    response_model=DriverResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a driver by id",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.8, see this module's own "
        "docstring). Authorization resolves against the real seeded RBAC permission matrix "
        "— see `register_driver`'s note."
    ),
)
async def get_driver(
    driver_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.drivers.read"))
    ),
    driver_service: DriverApplicationService = Depends(get_driver_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> DriverResponse:
    driver = await driver_service.get_driver_by_id(
        GetDriverByIdQuery(driver_id=driver_id), uow=uow
    )
    return _driver_dto_to_response(driver)


@drivers_router.patch(
    "/{driver_id}",
    response_model=DriverResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a driver's details and/or status",
    description=(
        "Org Admin. No documented API Contracts route (Phase 10.8, see this module's own "
        "docstring). Composes `license_no` (dispatched to `update_driver`) and `status` "
        "(dispatched to `activate_driver`/`disable_driver`) in one request, each "
        "independently — not atomically — mirroring `update_parent`'s identical composition. "
        "Authorization resolves against the real seeded RBAC permission matrix."
    ),
)
async def update_driver(
    driver_id: str,
    body: UpdateDriverRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.drivers.update"))
    ),
    driver_service: DriverApplicationService = Depends(get_driver_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> DriverResponse:
    if body.license_no is None and body.status is None:
        raise ValidationError(
            "At least one of 'license_no' or 'status' must be provided.",
            details={"fields": ["license_no", "status"]},
        )

    driver: DriverDTO | None = None

    if body.license_no is not None:
        command = UpdateDriverCommand(
            driver_id=driver_id,
            license_no=body.license_no,
            actor=principal,
        )
        driver = await driver_service.update_driver(command, uow=uow)

    if body.status is not None:
        if body.status == "active":
            driver = await driver_service.activate_driver(
                ActivateDriverCommand(driver_id=driver_id, actor=principal), uow=uow
            )
        elif body.status == "inactive":
            driver = await driver_service.disable_driver(
                DisableDriverCommand(driver_id=driver_id, actor=principal), uow=uow
            )
        else:
            raise ValidationError(
                f"Unsupported status: {body.status!r}", details={"field": "status"}
            )

    if driver is None:
        # Guaranteed not to happen by the "at least one field" guard above — an explicit
        # raise rather than `assert`, matching `update_parent`'s identical
        # invariant-holds-regardless-of-interpreter-flags reasoning.
        raise RuntimeError(
            "update_driver: no field was processed despite the guard above."
        )
    return _driver_dto_to_response(driver)


@routes_router.post(
    "",
    response_model=RouteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new route",
    description=(
        "Org Admin (API Contracts §4.3 line 125). Authorization uses `require_permission`, "
        "resolving against the real seeded RBAC permission matrix (ADR-0004), matching "
        "`enroll_student`'s posture."
    ),
)
async def create_route(
    body: CreateRouteRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.create"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> RouteResponse:
    command = CreateRouteCommand(
        organization_id=body.organization_id,
        name=body.name,
        actor=principal,
    )
    route = await route_service.create_route(command, uow=uow)
    return _route_dto_to_response(route)


@routes_router.get(
    "",
    response_model=OffsetPageResponse[RouteSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List routes",
    description=(
        "Org Admin (API Contracts §4.3 line 125). Not yet tenant-scoped — same inherited "
        "caveat as `list_students`/`list_parents`/`list_drivers`. Paginated/filterable/"
        "sortable per §7/§8. Authorization resolves against the real seeded RBAC permission "
        "matrix."
    ),
)
async def list_routes(
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.list"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[RouteSummaryResponse]:
    page = await route_service.list_routes(
        ListRoutesQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _route_summary_dto_to_response)


@routes_router.get(
    "/{route_id}",
    response_model=RouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a route by id",
    description=(
        "Org Admin (API Contracts §4.3/§4 uniform CRUD). Embeds the route's ordered stops. "
        "Authorization resolves against the real seeded RBAC permission matrix — see "
        "`create_route`'s note."
    ),
)
async def get_route(
    route_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.read"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> RouteResponse:
    route = await route_service.get_route_by_id(
        GetRouteByIdQuery(route_id=route_id), uow=uow
    )
    return _route_dto_to_response(route)


@routes_router.patch(
    "/{route_id}",
    response_model=RouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a route's details and/or status",
    description=(
        "Org Admin (API Contracts §4 uniform CRUD). Composes `name` (dispatched to "
        "`update_route`) and `status` (dispatched to `activate_route`/`disable_route`) in one "
        "request, each independently — not atomically — mirroring `update_parent`'s identical "
        "composition. No `archived` status value exists to dispatch to (Database Design §6.5's "
        "enum is exhaustively `active`/`inactive`, `domain/entities.py`'s module docstring). "
        "Authorization resolves against the real seeded RBAC permission matrix."
    ),
)
async def update_route(
    route_id: str,
    body: UpdateRouteRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.update"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> RouteResponse:
    if body.name is None and body.status is None:
        raise ValidationError(
            "At least one of 'name' or 'status' must be provided.",
            details={"fields": ["name", "status"]},
        )

    route: RouteDTO | None = None

    if body.name is not None:
        command = UpdateRouteCommand(
            route_id=route_id,
            name=body.name,
            actor=principal,
        )
        route = await route_service.update_route(command, uow=uow)

    if body.status is not None:
        if body.status == "active":
            route = await route_service.activate_route(
                ActivateRouteCommand(route_id=route_id, actor=principal), uow=uow
            )
        elif body.status == "inactive":
            route = await route_service.disable_route(
                DisableRouteCommand(route_id=route_id, actor=principal), uow=uow
            )
        else:
            raise ValidationError(
                f"Unsupported status: {body.status!r}", details={"field": "status"}
            )

    if route is None:
        # Guaranteed not to happen by the "at least one field" guard above — an explicit
        # raise rather than `assert`, matching `update_parent`'s identical
        # invariant-holds-regardless-of-interpreter-flags reasoning.
        raise RuntimeError(
            "update_route: no field was processed despite the guard above."
        )
    return _route_dto_to_response(route)


@routes_router.post(
    "/{route_id}/stops",
    response_model=StopResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a stop to a route",
    description=(
        "Org Admin — 'ordered stops' (API Contracts §4.3 line 126 verbatim). Rejects a "
        "duplicate `sequence_no` (`ConflictError`) and out-of-range coordinates/sequence "
        "(`DomainError`), both from `Route.add_stop` (`domain/entities.py`). Authorization "
        "resolves against the real seeded RBAC permission matrix — see `create_route`'s "
        "note."
    ),
)
async def add_stop_to_route(
    route_id: str,
    body: AddStopToRouteRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.stops.create"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StopResponse:
    command = AddStopToRouteCommand(
        route_id=route_id,
        name=body.name,
        latitude=body.latitude,
        longitude=body.longitude,
        sequence_no=body.sequence_no,
        geofence_radius_m=body.geofence_radius_m,
        actor=principal,
    )
    stop = await route_service.add_stop_to_route(command, uow=uow)
    return _stop_dto_to_response(stop)


@routes_router.get(
    "/{route_id}/stops",
    response_model=list[StopResponse],
    status_code=status.HTTP_200_OK,
    summary="List a route's stops in order",
    description=(
        "Org Admin — 'ordered stops' (API Contracts §4.3 line 126 verbatim). Always sorted by "
        "`sequence_no` (`domain/entities.py`'s `Route.stops` property). Authorization "
        "resolves against the real seeded RBAC permission matrix — see `create_route`'s "
        "note."
    ),
)
async def list_stops_for_route(
    route_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.routes.stops.list"))
    ),
    route_service: RouteApplicationService = Depends(get_route_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StopResponse]:
    stops = await route_service.list_stops_for_route(
        ListStopsForRouteQuery(route_id=route_id), uow=uow
    )
    return [_stop_dto_to_response(stop) for stop in stops]


@trips_router.post(
    "",
    response_model=TripResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a new trip",
    description=(
        "Org Admin — 'scheduled trips' (API Contracts §4.3 line 129). Rejects a driver/route "
        "not found (`NotFoundError`) and cross-organization driver/route assignment "
        "(`DomainError`), from `ensure_driver_exists`/`ensure_route_exists`/`Trip.schedule`. "
        "Authorization resolves against the real seeded RBAC permission matrix — see "
        "`enroll_student`'s note."
    ),
)
async def schedule_trip(
    body: ScheduleTripRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.trips.create"))
    ),
    trip_service: TripApplicationService = Depends(get_trip_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TripResponse:
    command = ScheduleTripCommand(
        organization_id=body.organization_id,
        vehicle_id=body.vehicle_id,
        driver_id=body.driver_id,
        route_id=body.route_id,
        trip_type=body.trip_type,
        scheduled_date=body.scheduled_date,
        actor=principal,
    )
    trip = await trip_service.schedule_trip(command, uow=uow)
    return _trip_dto_to_response(trip)


@trips_router.get(
    "",
    response_model=OffsetPageResponse[TripSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List trips",
    description=(
        "Org Admin (API Contracts §4.3 line 129). Not yet tenant-scoped — same inherited "
        "caveat as `list_students`/`list_parents`/`list_drivers`/`list_routes`. Paginated/"
        "filterable/sortable per §7/§8 — `Trip` is API Contracts §8's own filtering example "
        "resource (`filter[trip_type][in]=morning,afternoon`, "
        "`filter[scheduled_date][gte]=...`). Authorization resolves against the real seeded "
        "RBAC permission matrix."
    ),
)
async def list_trips(
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.trips.list"))
    ),
    trip_service: TripApplicationService = Depends(get_trip_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[TripSummaryResponse]:
    page = await trip_service.list_trips(
        ListTripsQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _trip_summary_dto_to_response)


@trips_router.get(
    "/{trip_id}",
    response_model=TripResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a trip by id",
    description=(
        "Org Admin (API Contracts §4 uniform CRUD — not itemized separately in §4.3's compact "
        "table, see `routers.py`'s module docstring). Authorization resolves against the "
        "real seeded RBAC permission matrix — see `schedule_trip`'s note."
    ),
)
async def get_trip(
    trip_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.trips.read"))
    ),
    trip_service: TripApplicationService = Depends(get_trip_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TripResponse:
    trip = await trip_service.get_trip_by_id(
        GetTripByIdQuery(trip_id=trip_id), uow=uow
    )
    return _trip_dto_to_response(trip)


async def _ensure_driver_owns_trip(
    *,
    trip_id: str,
    principal: Principal,
    trip_service: TripApplicationService,
    driver_service: DriverApplicationService,
    uow: TransportOpsUnitOfWork,
) -> None:
    """"Driver (own)" (API Contracts §4.3 lines 130-131) — only the `Driver` linked to this
    trip's `driver_id` may start/end it. A no-op for every other role that also holds
    `transport_ops.trips.start`/`.end` (Org Admin, per the seeded RBAC matrix's blanket
    transport_ops CRUD grant) — that access is an intentional admin-override, not
    ownership-scoped, mirroring `enforce_cr1`/`enforce_d5`'s own "apply only to the role this
    check is about" posture."""
    trip = await trip_service.get_trip_by_id(GetTripByIdQuery(trip_id=trip_id), uow=uow)
    driver = await driver_service.get_driver_by_id(
        GetDriverByIdQuery(driver_id=trip.driver_id), uow=uow
    )
    if driver.user_id != principal.user_id:
        raise AuthorizationError("This trip is not assigned to you.")


@trips_router.post(
    "/{trip_id}/start",
    response_model=TripResponse,
    status_code=status.HTTP_200_OK,
    summary="Start a trip",
    description=(
        "**Driver (own)** -> `TripStarted` (API Contracts §4.3 line 130 verbatim). Legal only "
        "from `SCHEDULED` (Phase-2 §6.2) — any other status raises `RuleViolationError` "
        "(`409 RULE_VIOLATION`, §5.2's own 'start an already-in-progress trip' example). "
        "Rejects a vehicle that already has another active trip (`ConflictError`, "
        "`409 CONFLICT`, one-active-trip-per-vehicle, Database Design §6.8). Driver-ownership "
        "is now verified (`_ensure_driver_owns_trip`, 403 `FORBIDDEN` on mismatch) — RBAC is "
        "live, resolving what was previously a deferred gap."
    ),
)
async def start_trip(
    trip_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.trips.start"))
    ),
    trip_service: TripApplicationService = Depends(get_trip_service),
    driver_service: DriverApplicationService = Depends(get_driver_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TripResponse:
    if principal.role == Role.DRIVER:
        await _ensure_driver_owns_trip(
            trip_id=trip_id,
            principal=principal,
            trip_service=trip_service,
            driver_service=driver_service,
            uow=uow,
        )
    trip = await trip_service.start_trip(
        StartTripCommand(trip_id=trip_id, actor=principal), uow=uow
    )
    return _trip_dto_to_response(trip)


@trips_router.post(
    "/{trip_id}/end",
    response_model=TripResponse,
    status_code=status.HTTP_200_OK,
    summary="End a trip",
    description=(
        "**Driver (own)** -> `TripEnded` (API Contracts §4.3 line 131 verbatim). Legal from "
        "`IN_PROGRESS` or `INTERRUPTED` (Phase-2 §6.2's 'end'/'force end' edges) — any other "
        "status raises `RuleViolationError`. Driver-ownership is now verified — see "
        "`start_trip`'s note."
    ),
)
async def end_trip(
    trip_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.trips.end"))
    ),
    trip_service: TripApplicationService = Depends(get_trip_service),
    driver_service: DriverApplicationService = Depends(get_driver_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TripResponse:
    if principal.role == Role.DRIVER:
        await _ensure_driver_owns_trip(
            trip_id=trip_id,
            principal=principal,
            trip_service=trip_service,
            driver_service=driver_service,
            uow=uow,
        )
    trip = await trip_service.end_trip(
        EndTripCommand(trip_id=trip_id, actor=principal), uow=uow
    )
    return _trip_dto_to_response(trip)


@trips_router.patch(
    "/{trip_id}/driver",
    response_model=TripResponse,
    status_code=status.HTTP_200_OK,
    summary="Change a trip's driver",
    description=(
        "Org Admin — 'change driver — no device change' (API Contracts §4.3 line 132 "
        "verbatim), body `{driver_id}`. Rejects a driver not found (`NotFoundError`) and a "
        "cross-organization driver (`DomainError`), from `ensure_driver_exists`/"
        "`Trip.change_driver`. No status restriction — see `Trip.change_driver`'s own "
        "docstring (`domain/entities.py`). Authorization resolves against the real seeded "
        "RBAC permission matrix."
    ),
)
async def change_trip_driver(
    trip_id: str,
    body: ChangeTripDriverRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.trips.change_driver"))
    ),
    trip_service: TripApplicationService = Depends(get_trip_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TripResponse:
    command = ChangeTripDriverCommand(
        trip_id=trip_id, driver_id=body.driver_id, actor=principal
    )
    trip = await trip_service.change_trip_driver(command, uow=uow)
    return _trip_dto_to_response(trip)


@student_assignments_router.post(
    "",
    response_model=StudentAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a student to a route",
    description=(
        "Org Admin — 'the CR-1 gate record' (API Contracts §4.3 line 127). Rejects a "
        "student/route not found (`NotFoundError`), a pickup/dropoff stop not on the given "
        "route (`NotFoundError`), cross-organization student/route (`DomainError`), and a "
        "student who already has an active assignment (`ConflictError`, one-active-assignment-"
        "per-student, Database Design §6.7). Authorization resolves against the real seeded "
        "RBAC permission matrix — see `enroll_student`'s note."
    ),
)
async def assign_student_to_route(
    body: AssignStudentToRouteRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_assignments.create"))
    ),
    student_assignment_service: StudentAssignmentApplicationService = Depends(
        get_student_assignment_service
    ),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentAssignmentResponse:
    command = AssignStudentToRouteCommand(
        organization_id=body.organization_id,
        student_id=body.student_id,
        route_id=body.route_id,
        pickup_stop_id=body.pickup_stop_id,
        dropoff_stop_id=body.dropoff_stop_id,
        vehicle_id=body.vehicle_id,
        actor=principal,
    )
    assignment = await student_assignment_service.assign_student_to_route(
        command, uow=uow
    )
    return _student_assignment_dto_to_response(assignment)


@student_assignments_router.get(
    "",
    response_model=OffsetPageResponse[StudentAssignmentSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List student assignments",
    description=(
        "Org Admin (API Contracts §4.3 line 127). Not yet tenant-scoped — same inherited "
        "caveat as `list_students`/`list_trips`. Paginated/filterable/sortable per §7/§8. "
        "Authorization resolves against the real seeded RBAC permission matrix."
    ),
)
async def list_student_assignments(
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_assignments.list"))
    ),
    student_assignment_service: StudentAssignmentApplicationService = Depends(
        get_student_assignment_service
    ),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[StudentAssignmentSummaryResponse]:
    page = await student_assignment_service.list_student_assignments(
        ListStudentAssignmentsQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _student_assignment_summary_dto_to_response)


@student_assignments_router.get(
    "/{student_assignment_id}",
    response_model=StudentAssignmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a student assignment by id",
    description=(
        "Org Admin (API Contracts §4 uniform CRUD — not itemized separately in §4.3's compact "
        "table, see `routers.py`'s module docstring). Authorization resolves against the "
        "real seeded RBAC permission matrix — see `assign_student_to_route`'s note."
    ),
)
async def get_student_assignment(
    student_assignment_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_assignments.read"))
    ),
    student_assignment_service: StudentAssignmentApplicationService = Depends(
        get_student_assignment_service
    ),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentAssignmentResponse:
    assignment = await student_assignment_service.get_student_assignment_by_id(
        GetStudentAssignmentByIdQuery(student_assignment_id=student_assignment_id),
        uow=uow,
    )
    return _student_assignment_dto_to_response(assignment)


@student_assignments_router.post(
    "/{student_assignment_id}/end",
    response_model=StudentAssignmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Transition a student assignment's status",
    description=(
        "Org Admin — body `{status}` -> removed/transferred/graduated/disabled -> CR-1 "
        "revocation event (API Contracts §4.3 line 128 verbatim). Authorization resolves "
        "against the real seeded RBAC permission matrix — see `assign_student_to_route`'s "
        "note."
    ),
)
async def end_student_assignment(
    student_assignment_id: str,
    body: UpdateStudentAssignmentStatusRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.student_assignments.end"))
    ),
    student_assignment_service: StudentAssignmentApplicationService = Depends(
        get_student_assignment_service
    ),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StudentAssignmentResponse:
    if body.status == "removed":
        assignment = await student_assignment_service.remove_student_assignment(
            RemoveStudentAssignmentCommand(
                student_assignment_id=student_assignment_id, actor=principal
            ),
            uow=uow,
        )
    elif body.status == "transferred":
        assignment = await student_assignment_service.transfer_student_assignment(
            TransferStudentAssignmentCommand(
                student_assignment_id=student_assignment_id, actor=principal
            ),
            uow=uow,
        )
    elif body.status == "graduated":
        assignment = await student_assignment_service.graduate_student_assignment(
            GraduateStudentAssignmentCommand(
                student_assignment_id=student_assignment_id, actor=principal
            ),
            uow=uow,
        )
    elif body.status == "disabled":
        assignment = await student_assignment_service.disable_student_assignment(
            DisableStudentAssignmentCommand(
                student_assignment_id=student_assignment_id, actor=principal
            ),
            uow=uow,
        )
    else:
        raise ValidationError(
            f"Unsupported status: {body.status!r}", details={"field": "status"}
        )

    return _student_assignment_dto_to_response(assignment)


# ============================================================================================
# ADR-0049/0050/0051: transport staff, bus crew, staff documents
# ============================================================================================
#
# Five resource prefixes, all `transport_ops`. The bus crew lives at `/staff-assignments`
# (filtered by `vehicle_id` or `staff_id`), not `/vehicles/{id}/crew`: `/vehicles` belongs to
# `fleet_device` (`.claude/rules/api.md` #2).
#
# Manage permissions are held by `org_admin` alone, so a manage route resolves the organization
# from the caller. Read routes are also open to founder/regional_manager/support_staff, who see
# every field except the Org-Admin-only ones (emergency contact, document number: ADR-0049 §6,
# ADR-0051 §2). Those are nulled here, at the edge, and the response says so.

transport_staff_router = APIRouter()
transport_staff_roles_router = APIRouter()
staff_assignments_router = APIRouter()
staff_document_types_router = APIRouter()
staff_documents_router = APIRouter()
staff_compliance_router = APIRouter()


def _private_fields_visible(principal: Principal) -> bool:
    return principal.role is Role.ORG_ADMIN


def _resolve_organization_id(principal: Principal, requested: str | None) -> str:
    """The organization a staff request is about. An Org Admin's defaults to their own (a
    different one is refused by the service); RAAD staff must name one."""
    organization_id = requested or principal.org_id
    if not organization_id:
        raise ValidationError(
            "organization_id is required.", details={"fields": ["organization_id"]}
        )
    return organization_id


def _staff_role_to_response(role: TransportStaffRoleDTO) -> StaffRoleResponse:
    return StaffRoleResponse(**dataclasses.asdict(role))


def _document_type_to_response(doc_type: StaffDocumentTypeDTO) -> StaffDocumentTypeResponse:
    return StaffDocumentTypeResponse(**dataclasses.asdict(doc_type))


def _staff_summary_to_response(
    staff: TransportStaffSummaryDTO,
) -> TransportStaffSummaryResponse:
    return TransportStaffSummaryResponse(**dataclasses.asdict(staff))


def _staff_to_response(staff: TransportStaffDTO, principal: Principal) -> TransportStaffResponse:
    visible = _private_fields_visible(principal)
    values = dataclasses.asdict(staff)
    if not visible:
        values["emergency_contact_name"] = None
        values["emergency_contact_phone"] = None
    return TransportStaffResponse(**values, private_fields_visible=visible)


def _assignment_to_response(
    assignment: VehicleStaffAssignmentDTO,
) -> VehicleStaffAssignmentResponse:
    return VehicleStaffAssignmentResponse(**dataclasses.asdict(assignment))


def _document_to_response(
    document: StaffDocumentDTO, principal: Principal
) -> StaffDocumentResponse:
    visible = _private_fields_visible(principal)
    values = dataclasses.asdict(document)
    if not visible:
        values["number"] = None
    return StaffDocumentResponse(**values, private_fields_visible=visible)


# ---- job titles ------------------------------------------------------------------------------


@transport_staff_roles_router.get(
    "",
    response_model=list[StaffRoleResponse],
    summary="List an organization's job titles",
)
async def list_staff_roles(
    organization_id: str | None = Query(None),
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_roles.list"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StaffRoleResponse]:
    roles = await service.list_roles(
        _resolve_organization_id(principal, organization_id), uow=uow
    )
    return [_staff_role_to_response(role) for role in roles]


@transport_staff_roles_router.post(
    "",
    response_model=StaffRoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a job title",
)
async def create_staff_role(
    body: StaffRoleRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_roles.manage"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StaffRoleResponse:
    role = await service.save_role(
        SaveStaffRoleCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            name=body.name,
            sort_order=body.sort_order,
            actor=principal,
        ),
        uow=uow,
    )
    return _staff_role_to_response(role)


@transport_staff_roles_router.post(
    "/defaults",
    response_model=list[StaffRoleResponse],
    summary="Add the default job titles the organization does not have yet",
)
async def add_default_staff_roles(
    body: StaffSetupDefaultsRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_roles.manage"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StaffRoleResponse]:
    roles = await service.add_default_roles(
        AddDefaultStaffSetupCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            actor=principal,
        ),
        uow=uow,
    )
    return [_staff_role_to_response(role) for role in roles]


@transport_staff_roles_router.patch(
    "/{role_id}",
    response_model=StaffRoleResponse,
    summary="Rename, reorder or archive a job title",
)
async def update_staff_role(
    role_id: str,
    body: StaffRoleRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_roles.manage"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StaffRoleResponse:
    role = await service.save_role(
        SaveStaffRoleCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            name=body.name,
            sort_order=body.sort_order,
            is_archived=body.is_archived,
            role_id=role_id,
            actor=principal,
        ),
        uow=uow,
    )
    return _staff_role_to_response(role)


# ---- staff records ---------------------------------------------------------------------------


@transport_staff_router.get(
    "",
    response_model=OffsetPageResponse[TransportStaffSummaryResponse],
    summary="List transport staff",
    description=(
        "Tenant-scoped. Filterable by `organization_id`, `status`, `role_id`; searchable by "
        "name, employee reference and phone."
    ),
)
async def list_transport_staff(
    principal: Principal = Depends(require_permission(Permission("transport_ops.staff.list"))),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[TransportStaffSummaryResponse]:
    page = await service.list_staff(
        ListTransportStaffQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _staff_summary_to_response)


@transport_staff_router.post(
    "",
    response_model=TransportStaffResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a staff member",
    description="No login is created: only drivers log in (use driver access for that).",
)
async def register_transport_staff(
    body: RegisterTransportStaffRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.staff.manage"))),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TransportStaffResponse:
    values = body.model_dump(exclude={"organization_id"})
    staff = await service.register_staff(
        RegisterTransportStaffCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            actor=principal,
            **values,
        ),
        uow=uow,
    )
    return _staff_to_response(staff, principal)


@transport_staff_router.get(
    "/{staff_id}",
    response_model=TransportStaffResponse,
    summary="Get a staff member",
)
async def get_transport_staff(
    staff_id: str,
    principal: Principal = Depends(require_permission(Permission("transport_ops.staff.read"))),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TransportStaffResponse:
    return _staff_to_response(await service.get_staff(staff_id, uow=uow), principal)


@transport_staff_router.patch(
    "/{staff_id}",
    response_model=TransportStaffResponse,
    summary="Edit a staff member's profile",
    description="Only the fields present in the body change; `null` clears a field.",
)
async def update_transport_staff(
    staff_id: str,
    body: UpdateTransportStaffRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.staff.manage"))),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TransportStaffResponse:
    changes = body.model_dump(include=body.model_fields_set)
    if "full_name" in changes and changes["full_name"] is None:
        raise ValidationError("full_name cannot be cleared.", details={"fields": ["full_name"]})
    staff = await service.update_staff(
        UpdateTransportStaffCommand(staff_id=staff_id, changes=changes, actor=principal),
        uow=uow,
    )
    return _staff_to_response(staff, principal)


@transport_staff_router.post(
    "/{staff_id}/status",
    response_model=TransportStaffResponse,
    summary="Mark a staff member active, inactive or left",
    description=(
        "`left` also ends every current or planned bus assignment and disables their driver "
        "profile, in one transaction (ADR-0049 §4)."
    ),
)
async def change_transport_staff_status(
    staff_id: str,
    body: ChangeTransportStaffStatusRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.staff.manage"))),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TransportStaffResponse:
    staff = await service.change_status(
        ChangeTransportStaffStatusCommand(
            staff_id=staff_id, status=body.status, actor=principal
        ),
        uow=uow,
    )
    return _staff_to_response(staff, principal)


@transport_staff_router.post(
    "/{staff_id}/driver-access",
    response_model=DriverCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Give a staff member driver access (a login plus a driver profile)",
    description=(
        "Needs both `transport_ops.staff.manage` and `transport_ops.drivers.create`. Returns the "
        "one-time temporary password exactly once, like `POST /drivers`."
    ),
)
async def grant_driver_access(
    staff_id: str,
    body: GrantDriverAccessRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.staff.manage"))),
    _can_create_drivers: Principal = Depends(
        require_permission(Permission("transport_ops.drivers.create"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> DriverCreatedResponse:
    driver, temporary_password = await service.grant_driver_access(
        GrantDriverAccessCommand(
            staff_id=staff_id,
            license_no=body.license_no,
            email=body.email,
            phone=body.phone,
            actor=principal,
        ),
        uow=uow,
    )
    return DriverCreatedResponse(
        driver=_driver_dto_to_response(driver), temporary_password=temporary_password
    )


@transport_staff_router.get(
    "/{staff_id}/documents",
    response_model=list[StaffDocumentResponse],
    summary="A staff member's documents, including superseded ones",
)
async def list_staff_documents(
    staff_id: str,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_documents.list"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StaffDocumentResponse]:
    documents = await service.list_documents_for_staff(staff_id, uow=uow)
    return [_document_to_response(d, principal) for d in documents]


@transport_staff_router.post(
    "/{staff_id}/documents",
    response_model=StaffDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a document (or a renewal, with `replaces_id`)",
)
async def record_staff_document(
    staff_id: str,
    body: RecordStaffDocumentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_documents.manage"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StaffDocumentResponse:
    document = await service.record_document(
        RecordStaffDocumentCommand(staff_id=staff_id, actor=principal, **body.model_dump()),
        uow=uow,
    )
    return _document_to_response(document, principal)


# ---- bus crew --------------------------------------------------------------------------------


@staff_assignments_router.get(
    "",
    response_model=list[VehicleStaffAssignmentResponse],
    summary="A bus's crew, or a staff member's buses, with history",
    description="Give `vehicle_id` or `staff_id`. `current=true` keeps only today's rows.",
)
async def list_staff_assignments(
    vehicle_id: str | None = Query(None),
    staff_id: str | None = Query(None),
    current: bool = Query(False),
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_assignments.list"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[VehicleStaffAssignmentResponse]:
    rows = await service.list_assignments(
        uow=uow, vehicle_id=vehicle_id, staff_id=staff_id, current_only=current
    )
    return [_assignment_to_response(row) for row in rows]


@staff_assignments_router.post(
    "",
    response_model=VehicleStaffAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Put a staff member on a bus",
    description=(
        "Records the job title held now. A temporary assignment needs `ends_on`. The same "
        "person cannot be on the same bus twice for overlapping dates (409)."
    ),
)
async def assign_staff_to_vehicle(
    body: AssignStaffToVehicleRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_assignments.manage"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> VehicleStaffAssignmentResponse:
    assignment = await service.assign_to_vehicle(
        AssignStaffToVehicleCommand(actor=principal, **body.model_dump()), uow=uow
    )
    return _assignment_to_response(assignment)


@staff_assignments_router.post(
    "/{assignment_id}/end",
    response_model=VehicleStaffAssignmentResponse,
    summary="End a crew assignment (kept as history)",
)
async def end_staff_assignment(
    assignment_id: str,
    body: EndStaffAssignmentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_assignments.manage"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> VehicleStaffAssignmentResponse:
    assignment = await service.end_assignment(
        EndStaffAssignmentCommand(
            assignment_id=assignment_id, ends_on=body.ends_on, actor=principal
        ),
        uow=uow,
    )
    return _assignment_to_response(assignment)


# ---- document types and documents ------------------------------------------------------------


@staff_document_types_router.get(
    "",
    response_model=list[StaffDocumentTypeResponse],
    summary="List an organization's staff document types",
)
async def list_staff_document_types(
    organization_id: str | None = Query(None),
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_documents.list"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StaffDocumentTypeResponse]:
    types = await service.list_document_types(
        _resolve_organization_id(principal, organization_id), uow=uow
    )
    return [_document_type_to_response(t) for t in types]


@staff_document_types_router.post(
    "",
    response_model=StaffDocumentTypeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a staff document type",
)
async def create_staff_document_type(
    body: StaffDocumentTypeRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_documents.manage"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StaffDocumentTypeResponse:
    doc_type = await service.save_document_type(
        SaveStaffDocumentTypeCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            name=body.name,
            alert_lead_days=tuple(body.alert_lead_days),
            required_for=body.required_for,
            enforcement=body.enforcement,
            actor=principal,
        ),
        uow=uow,
    )
    return _document_type_to_response(doc_type)


@staff_document_types_router.post(
    "/defaults",
    response_model=list[StaffDocumentTypeResponse],
    summary="Add the default document types the organization does not have yet",
)
async def add_default_staff_document_types(
    body: StaffSetupDefaultsRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_documents.manage"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StaffDocumentTypeResponse]:
    types = await service.add_default_document_types(
        AddDefaultStaffSetupCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            actor=principal,
        ),
        uow=uow,
    )
    return [_document_type_to_response(t) for t in types]


@staff_document_types_router.patch(
    "/{type_id}",
    response_model=StaffDocumentTypeResponse,
    summary="Rename, change alert days or archive a document type",
)
async def update_staff_document_type(
    type_id: str,
    body: StaffDocumentTypeRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_documents.manage"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StaffDocumentTypeResponse:
    doc_type = await service.save_document_type(
        SaveStaffDocumentTypeCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            name=body.name,
            alert_lead_days=tuple(body.alert_lead_days),
            is_archived=body.is_archived,
            required_for=body.required_for,
            enforcement=body.enforcement,
            type_id=type_id,
            actor=principal,
        ),
        uow=uow,
    )
    return _document_type_to_response(doc_type)


@staff_document_types_router.get(
    "/{type_id}/impact",
    response_model=DocumentTypeImpactResponse,
    summary="How many staff a requirement would apply to, and how many do not meet it today",
    description="ADR-0058 §3. Reads only; shown before a requirement is saved.",
)
async def staff_document_type_impact(
    type_id: str,
    required_for: Literal["none", "drivers", "all_staff"] = Query(...),
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_documents.manage"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> DocumentTypeImpactResponse:
    impact = await service.document_type_impact(type_id, required_for, uow=uow)
    return DocumentTypeImpactResponse(**dataclasses.asdict(impact))


@staff_compliance_router.get(
    "",
    response_model=list[StaffComplianceRowResponse],
    summary="Staff who do not meet a document requirement, or are about to stop meeting one",
    description=(
        "ADR-0058 §3. Not compliant first, then expiring. Reasons name the document type and "
        "say `missing` or `expired`; a document number is never returned."
    ),
)
async def list_staff_compliance(
    organization_id: str | None = Query(None),
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_documents.list"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StaffComplianceRowResponse]:
    rows = await service.list_staff_compliance(uow=uow, organization_id=organization_id)
    return [StaffComplianceRowResponse(**dataclasses.asdict(r)) for r in rows]


@staff_documents_router.get(
    "/expiring",
    response_model=list[StaffDocumentResponse],
    summary="Current documents that are expiring or expired, soonest first",
)
async def list_expiring_staff_documents(
    organization_id: str | None = Query(None),
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_documents.list"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[StaffDocumentResponse]:
    documents = await service.list_expiring_documents(
        uow=uow, organization_id=organization_id
    )
    return [_document_to_response(d, principal) for d in documents]


@staff_documents_router.patch(
    "/{document_id}",
    response_model=StaffDocumentResponse,
    summary="Correct a document's details",
    description=(
        "Only the fields present in the body change. Changing the expiry restarts its alerts."
    ),
)
async def update_staff_document(
    document_id: str,
    body: UpdateStaffDocumentRequest,
    principal: Principal = Depends(
        require_permission(Permission("transport_ops.staff_documents.manage"))
    ),
    service: TransportStaffApplicationService = Depends(get_transport_staff_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> StaffDocumentResponse:
    document = await service.update_document(
        UpdateStaffDocumentCommand(
            document_id=document_id,
            changes=body.model_dump(include=body.model_fields_set),
            actor=principal,
        ),
        uow=uow,
    )
    return _document_to_response(document, principal)


# ============================================================================================
# ADR-0052/0053/0054: daily transport operations
# ============================================================================================
#
# Manage permissions are `org_admin` only; list/read also go to founder, regional_manager and
# support_staff, who never see an unavailability note (nulled here, like the Phase 1 private
# fields). Trip generation and cancellation hang off `/trips`, which they act on.

route_timetable_router = APIRouter()
operating_closures_router = APIRouter()
staff_unavailability_router = APIRouter()
staff_covers_router = APIRouter()
daily_operations_router = APIRouter()


def _cover_to_response(cover: CoverDTO) -> CoverResponse:
    return CoverResponse(**dataclasses.asdict(cover))


def _unavailability_to_response(item: UnavailabilityDTO, principal: Principal) -> UnavailabilityResponse:
    visible = _private_fields_visible(principal)
    values = dataclasses.asdict(item)
    if not visible:
        values["note"] = None
    return UnavailabilityResponse(**values, private_fields_visible=visible)


# ---- timetable -------------------------------------------------------------------------------


@route_timetable_router.get(
    "",
    response_model=list[TimetableEntryResponse],
    summary="The weekly timetable, optionally for one route",
)
async def list_route_timetable(
    route_id: str | None = Query(None),
    principal: Principal = Depends(require_permission(Permission("transport_ops.timetable.list"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[TimetableEntryResponse]:
    entries = await service.list_timetable(uow=uow, route_id=route_id)
    return [TimetableEntryResponse(**dataclasses.asdict(e)) for e in entries]


def _timetable_command(
    body: TimetableEntryRequest, principal: Principal, entry_id: str | None
) -> SaveTimetableEntryCommand:
    return SaveTimetableEntryCommand(
        organization_id=_resolve_organization_id(principal, body.organization_id),
        route_id=body.route_id,
        vehicle_id=body.vehicle_id,
        trip_type=body.trip_type,
        weekdays=tuple(body.weekdays),
        default_driver_id=body.default_driver_id,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        planned_departure=body.planned_departure,
        is_active=body.is_active,
        entry_id=entry_id,
        actor=principal,
    )


@route_timetable_router.post(
    "",
    response_model=TimetableEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a regular run to the weekly timetable",
    description="409 when the bus already has an entry for that period on one of those weekdays.",
)
async def create_route_timetable_entry(
    body: TimetableEntryRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.timetable.manage"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TimetableEntryResponse:
    entry = await service.save_timetable_entry(_timetable_command(body, principal, None), uow=uow)
    return TimetableEntryResponse(**dataclasses.asdict(entry))


@route_timetable_router.put(
    "/{entry_id}",
    response_model=TimetableEntryResponse,
    summary="Replace a timetable entry (trips already generated are not changed)",
)
async def update_route_timetable_entry(
    entry_id: str,
    body: TimetableEntryRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.timetable.manage"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TimetableEntryResponse:
    entry = await service.save_timetable_entry(_timetable_command(body, principal, entry_id), uow=uow)
    return TimetableEntryResponse(**dataclasses.asdict(entry))


# ---- closures --------------------------------------------------------------------------------


@operating_closures_router.get(
    "",
    response_model=list[ClosureResponse],
    summary="Closed days overlapping a date range",
)
async def list_operating_closures(
    start: date = Query(...),
    end: date = Query(...),
    principal: Principal = Depends(require_permission(Permission("transport_ops.closures.list"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[ClosureResponse]:
    closures = await service.list_closures(uow=uow, start=start, end=end)
    return [ClosureResponse(**dataclasses.asdict(c)) for c in closures]


@operating_closures_router.post(
    "",
    response_model=ClosureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record days without transport",
    description="Trips already generated inside it are not cancelled; the daily board shows them.",
)
async def record_operating_closure(
    body: ClosureRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.closures.manage"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ClosureResponse:
    closure = await service.record_closure(
        RecordClosureCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id),
            starts_on=body.starts_on,
            ends_on=body.ends_on,
            label=body.label,
            actor=principal,
        ),
        uow=uow,
    )
    return ClosureResponse(**dataclasses.asdict(closure))


@operating_closures_router.post(
    "/{closure_id}/withdraw",
    response_model=ClosureResponse,
    summary="Withdraw a closure (kept as history)",
)
async def withdraw_operating_closure(
    closure_id: str,
    principal: Principal = Depends(require_permission(Permission("transport_ops.closures.manage"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> ClosureResponse:
    closure = await service.withdraw_closure(closure_id, actor=principal, uow=uow)
    return ClosureResponse(**dataclasses.asdict(closure))


# ---- unavailability and cover ----------------------------------------------------------------


@staff_unavailability_router.get(
    "",
    response_model=list[UnavailabilityResponse],
    summary="Unavailability of one person, or of everyone over a date range",
)
async def list_staff_unavailability(
    staff_id: str | None = Query(None),
    start: date | None = Query(None),
    end: date | None = Query(None),
    principal: Principal = Depends(require_permission(Permission("transport_ops.unavailability.list"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[UnavailabilityResponse]:
    items = await service.list_unavailability(uow=uow, staff_id=staff_id, start=start, end=end)
    return [_unavailability_to_response(i, principal) for i in items]


@staff_unavailability_router.post(
    "",
    response_model=UnavailabilityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record that someone cannot work for a period",
    description="Changes nothing else: affected trips and crew are flagged, never reassigned.",
)
async def record_staff_unavailability(
    body: UnavailabilityRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.unavailability.manage"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> UnavailabilityResponse:
    item = await service.record_unavailability(
        RecordUnavailabilityCommand(actor=principal, **body.model_dump()), uow=uow
    )
    return _unavailability_to_response(item, principal)


@staff_unavailability_router.post(
    "/{unavailability_id}/withdraw",
    response_model=UnavailabilityResponse,
    summary="Withdraw an unavailability and its covers",
)
async def withdraw_staff_unavailability(
    unavailability_id: str,
    principal: Principal = Depends(require_permission(Permission("transport_ops.unavailability.manage"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> UnavailabilityResponse:
    item = await service.withdraw_unavailability(unavailability_id, actor=principal, uow=uow)
    return _unavailability_to_response(item, principal)


@staff_covers_router.post(
    "",
    response_model=CoverResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Name a substitute for an unavailable person on a bus",
    description=(
        "Creates the substitute's temporary crew assignment. When a driver is covered, the "
        "substitute (who must have active driver access) takes their scheduled trips on that bus."
    ),
)
async def create_staff_cover(
    body: CoverRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.covers.manage"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> CoverResponse:
    cover = await service.create_cover(CreateCoverCommand(actor=principal, **body.model_dump()), uow=uow)
    return _cover_to_response(cover)


@staff_covers_router.post(
    "/{cover_id}/withdraw",
    response_model=CoverResponse,
    summary="Withdraw a cover; the original driver gets their scheduled trips back",
)
async def withdraw_staff_cover(
    cover_id: str,
    principal: Principal = Depends(require_permission(Permission("transport_ops.covers.manage"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> CoverResponse:
    return _cover_to_response(await service.withdraw_cover(cover_id, actor=principal, uow=uow))


# ---- the daily board -------------------------------------------------------------------------


@daily_operations_router.get(
    "",
    response_model=DailyBoardResponse,
    summary="Every bus's trips, crew, absences and cover for one date",
)
async def get_daily_operations(
    day: date = Query(..., alias="date"),
    principal: Principal = Depends(require_permission(Permission("transport_ops.daily_operations.read"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> DailyBoardResponse:
    return DailyBoardResponse(**dataclasses.asdict(await service.daily_board(day, uow=uow)))


# ---- trip generation and cancellation --------------------------------------------------------


@trips_router.post(
    "/generate",
    response_model=GenerationResultResponse,
    summary="Generate trips from the timetable (or preview with dry_run)",
    description="Idempotent: trips that already exist for a bus, date and period are never duplicated.",
)
async def generate_trips(
    body: GenerateTripsRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.trips.generate"))),
    service: DailyOperationsApplicationService = Depends(get_daily_operations_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> GenerationResultResponse:
    result = await service.generate_trips(
        GenerateTripsCommand(actor=principal, start=body.start, days=body.days, dry_run=body.dry_run),
        uow=uow,
    )
    return GenerationResultResponse(**dataclasses.asdict(result))


@trips_router.post(
    "/{trip_id}/cancel",
    response_model=TripResponse,
    summary="Cancel a scheduled trip; its children's parents are told",
)
async def cancel_trip(
    trip_id: str,
    body: CancelTripRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.trips.cancel"))),
    trip_service: TripApplicationService = Depends(get_trip_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> TripResponse:
    trip = await trip_service.cancel_trip(
        CancelTripCommand(trip_id=trip_id, reason=body.reason, actor=principal), uow=uow
    )
    return _trip_dto_to_response(trip)


# ============================================================================================
# ADR-0056: the incident log
# ============================================================================================

incidents_router = APIRouter()

_INCIDENT_PRIVATE_TEXT = ("title", "description", "actions_taken", "resolution")
_INCIDENT_PRIVATE_LISTS = ("staff_ids", "staff_names", "student_ids", "student_names", "notes")


def _incident_to_response(incident: IncidentDTO, principal: Principal) -> IncidentResponse:
    visible = _private_fields_visible(principal)
    values = dataclasses.asdict(incident)
    if not visible:
        for key in _INCIDENT_PRIVATE_TEXT:
            values[key] = None
        for key in _INCIDENT_PRIVATE_LISTS:
            values[key] = []
    return IncidentResponse(**values, private_fields_visible=visible)


@incidents_router.get("", response_model=list[IncidentResponse], summary="Incidents, newest first")
async def list_incidents(
    status_filter: list[str] = Query(default=[], alias="status"),
    category: str | None = Query(None),
    vehicle_id: str | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    principal: Principal = Depends(require_permission(Permission("transport_ops.incidents.list"))),
    service: IncidentApplicationService = Depends(get_incident_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> list[IncidentResponse]:
    incidents = await service.list_incidents(
        uow=uow, statuses=status_filter, category=category, vehicle_id=vehicle_id, start=start, end=end
    )
    return [_incident_to_response(i, principal) for i in incidents]


@incidents_router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record an incident",
    description="Picking a trip fills in its bus, route and driver unless given.",
)
async def record_incident(
    body: RecordIncidentRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.incidents.manage"))),
    service: IncidentApplicationService = Depends(get_incident_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> IncidentResponse:
    values = body.model_dump(exclude={"organization_id"})
    values["staff_ids"] = tuple(values["staff_ids"])
    values["student_ids"] = tuple(values["student_ids"])
    incident = await service.record(
        RecordIncidentCommand(
            organization_id=_resolve_organization_id(principal, body.organization_id), actor=principal, **values
        ),
        uow=uow,
    )
    return _incident_to_response(incident, principal)


@incidents_router.post(
    "/from-alert/{alert_id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Turn a safety alert into an incident and resolve the alert",
    description=(
        "Two modules, two transactions: the incident is recorded, then the alert is resolved "
        "with its id. If the second step fails the incident stands and the alert stays open."
    ),
)
async def record_incident_from_alert(
    alert_id: str,
    principal: Principal = Depends(require_permission(Permission("transport_ops.incidents.manage"))),
    _alerts_permission: Principal = Depends(require_permission(Permission("tracking.safety_alerts.manage"))),
    service: IncidentApplicationService = Depends(get_incident_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
    alert_service: SafetyAlertApplicationService = Depends(get_safety_alert_service),
    tracking_uow: TrackingUnitOfWork = Depends(get_scoped_tracking_uow),
    tracking_uow_for_resolve: TrackingUnitOfWork = Depends(get_scoped_tracking_uow_fresh),
) -> IncidentResponse:
    alert = await alert_service.get_alert(alert_id, uow=tracking_uow)
    if alert.incident_id:
        raise ConflictError("This alert already has an incident.")
    incident = await service.record_from_alert(alert, actor=principal, uow=uow)
    await alert_service.resolve(alert_id, actor=principal, uow=tracking_uow_for_resolve, incident_id=incident.id)
    return _incident_to_response(incident, principal)


@incidents_router.get("/{incident_id}", response_model=IncidentResponse, summary="One incident with its timeline")
async def get_incident(
    incident_id: str,
    principal: Principal = Depends(require_permission(Permission("transport_ops.incidents.read"))),
    service: IncidentApplicationService = Depends(get_incident_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> IncidentResponse:
    return _incident_to_response(await service.get(incident_id, uow=uow), principal)


@incidents_router.patch("/{incident_id}", response_model=IncidentResponse, summary="Edit an incident")
async def update_incident(
    incident_id: str,
    body: UpdateIncidentRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.incidents.manage"))),
    service: IncidentApplicationService = Depends(get_incident_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> IncidentResponse:
    changes = body.model_dump(include=body.model_fields_set)
    for key in ("category", "severity", "occurred_at", "title"):
        if key in changes and changes[key] is None:
            raise ValidationError(f"{key} cannot be cleared.", details={"fields": [key]})
    for key in ("staff_ids", "student_ids"):
        if key in changes:
            changes[key] = tuple(changes[key] or ())
    return _incident_to_response(await service.update(incident_id, changes, actor=principal, uow=uow), principal)


@incidents_router.post("/{incident_id}/status", response_model=IncidentResponse, summary="Move an incident on")
async def change_incident_status(
    incident_id: str,
    body: IncidentStatusRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.incidents.manage"))),
    service: IncidentApplicationService = Depends(get_incident_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> IncidentResponse:
    incident = await service.change_status(
        incident_id,
        body.status,
        resolution=body.resolution,
        recorded_in_error=body.recorded_in_error,
        actor=principal,
        uow=uow,
    )
    return _incident_to_response(incident, principal)


@incidents_router.post("/{incident_id}/notes", response_model=IncidentResponse, summary="Add a timeline note")
async def add_incident_note(
    incident_id: str,
    body: IncidentNoteRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.incidents.manage"))),
    service: IncidentApplicationService = Depends(get_incident_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> IncidentResponse:
    return _incident_to_response(await service.add_note(incident_id, body.body, actor=principal, uow=uow), principal)


@incidents_router.post(
    "/{incident_id}/notify-parents",
    response_model=IncidentResponse,
    summary="Send a notice to the parents of the students linked to the incident",
)
async def notify_incident_parents(
    incident_id: str,
    body: IncidentParentNoticeRequest,
    principal: Principal = Depends(require_permission(Permission("transport_ops.incidents.manage"))),
    service: IncidentApplicationService = Depends(get_incident_service),
    uow: TransportOpsUnitOfWork = Depends(get_transport_ops_uow),
) -> IncidentResponse:
    return _incident_to_response(
        await service.notify_parents(incident_id, body.message, actor=principal, uow=uow), principal
    )
