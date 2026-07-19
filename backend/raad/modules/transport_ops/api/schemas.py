"""HTTP request/response DTOs for `transport_ops` (Backend LLD §16; API Contracts §4.3).
Pydantic models are transport-only — the boundary at which JSON becomes/comes-from the
application layer's plain-dataclass commands/DTOs. No business logic lives here; routers do
that translation (`routers.py`), never the schemas themselves. Mirrors
`organization.api.schemas`'s shape exactly.

`status` is transported as the approved lower-case snake_case string (Database Design §6.2:
`active`/`disabled`/`graduated`/`transferred`), matching `transport_ops.domain.value_objects.
StudentStatus`'s enum values one-for-one — no case-folding translation needed here (unlike
`iam.api.schemas`'s `Role`).

Only `StudentSummaryResponse` omits `organization_id`/`external_ref`, mirroring
`StudentSummaryDTO`'s own lighter shape (`application/queries.py`) for the list endpoint.

**Phase 10.6 addition: `Parent` schemas.** `ParentStatus`'s two values (`active`/`inactive`,
`domain/value_objects.py`) transport the same way. Unlike `Student`, `Parent` has no
documented behavioral status sub-route (API Contracts §4.3's `/parents` row carries no notes,
unlike `/students/{id}/status`'s explicit line) — see `routers.py`'s module docstring for why
`status` therefore folds into the uniform `PATCH` here instead, mirroring `organization`'s/
`fleet_device`'s status-in-PATCH shape rather than `Student`'s dedicated-route shape.

**Phase 10.7 addition: `StudentParent` link schemas.** No documented API Contracts route
either (see `routers.py`'s module docstring for the nested-sub-resource shape chosen instead,
mirroring the one documented precedent for a child collection, `/routes/{id}/stops`).

**Phase 10.8 addition: `Driver` schemas.** `DriverStatus`'s two values (`active`/`inactive`,
`domain/value_objects.py`) transport the same way `ParentStatus`'s do. Like `Parent`, `Driver`
has no documented behavioral status sub-route (in fact **no** `/drivers` route of any kind is
documented in API Contracts §4.3 — see `routers.py`'s module docstring for the full gap and why
a uniform-CRUD resource is built anyway), so `status` folds into the uniform `PATCH` here too.

**Phase 11 addition: `Route`/`Stop` schemas.** `RouteStatus`'s two values transport the same
way, folded into `UpdateRouteRequest`'s `PATCH` for the identical reason (no documented status
sub-route for `/routes`). `RouteResponse` embeds `stops: list[StopResponse]`, mirroring
`fleet_device.api.schemas.DeviceResponse`'s identical `cameras: list[CameraResponse]` shape.
`/routes` and `/routes/{id}/stops` **are** documented (API Contracts §4.3: `GET/POST /routes`,
`GET/POST /routes/{id}/stops` "ordered stops") — unlike `Driver`/`StudentParent` above, no
documentation gap exists for the routes this phase actually exposes; see `routers.py`'s module
docstring for the one real gap this phase does have (individual stop update/removal/reorder).

**Phase 12 addition: `Trip` schemas.** `TripStatus`'s four values (`scheduled`/`in_progress`/
`interrupted`/`completed`) and `TripType`'s two (`morning`/`afternoon`) transport the same
lower-case snake_case way. `ScheduleTripRequest` backs the documented `POST /trips` (API
Contracts §4.3 line 129). `start`/`end` (lines 130-131) take no request body — the documented
"Trip start response" sample shows no request example, matching a Driver-initiated,
path-identified action. `ChangeTripDriverRequest` backs the documented
`PATCH /trips/{id}/driver` (line 132, body `{driver_id}` verbatim) — this is Trip's *only*
uniform-CRUD-style `PATCH`; no other field is documented as post-creation-editable, so there is
no general `UpdateTripRequest` the way every other aggregate in this module has one.

**Phase 13 addition: `StudentAssignment` schemas.** `StudentAssignmentStatus`'s five values
transport the same lower-case snake_case way. `AssignStudentToRouteRequest` backs the documented
`POST /student-assignments` (API Contracts line 127). `UpdateStudentAssignmentStatusRequest`
(body `{status}`) backs the documented `POST /student-assignments/{id}/end` (line 128:
"status→removed/transferred/… → CR-1 revocation event"), mirroring `UpdateStudentStatusRequest`'s
identical one-endpoint-many-transitions shape even though the mount path is named `/end`, not
`/status`. **Not included:** `created_at`/`updated_at` — see `application/queries.py`'s Phase 13
addition for the flagged, pre-existing, module-wide gap this follows rather than fixes one-off.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class StudentResponse(BaseModel):
    id: str
    organization_id: str
    full_name: str
    external_ref: str | None
    status: str


class StudentSummaryResponse(BaseModel):
    id: str
    full_name: str
    status: str


class EnrollStudentRequest(BaseModel):
    organization_id: str
    full_name: str
    external_ref: str | None = None


class UpdateStudentRequest(BaseModel):
    """Uniform-CRUD `PATCH /students/{id}` (API Contracts §4 preamble). Limited to the field
    edit the Application layer actually exposes (`StudentApplicationService.update_student` ->
    `Student.update_details`) — `full_name`/`external_ref`. **Not** `status`: status
    transitions are their own approved, behavioral route (`POST /students/{id}/status`, API
    Contracts §4.3 line 123, with its own CR-1 consequence) — the same separation
    `fleet_device.api.routers` draws between its uniform `PATCH /devices/{id}` and its
    behavioral `POST /devices/{id}/activate`, rather than `iam.api.schemas.UpdateUserRequest`'s
    bundled-fields shape, since Student's status route is independently documented with its
    own role/notes row, unlike `iam`'s status field.

    At least one field must be given."""

    full_name: str | None = None
    external_ref: str | None = None


class UpdateStudentStatusRequest(BaseModel):
    """`POST /students/{id}/status` (API Contracts §4.3 line 123 verbatim: 'body `{status}`
    -> disable/graduate/transfer -> emits CR-1 revocation'). `status` accepts any of
    `StudentStatus`'s four values (`active`/`disabled`/`graduated`/`transferred`) — the
    documented prose names only the three revoking transitions as the notable/CR-1-relevant
    ones, but the route itself is the single generic status-transition endpoint (the same
    "one PATCH/POST dispatches by status string" shape `organization`/`fleet_device` already
    use for their own multi-value status fields), and `StudentApplicationService.
    activate_student` is an equally-approved Phase 10.2 use-case with no other route to reach
    it from. Treating `active` as reachable here too is an interpretation, not a silent
    assumption — flagged in `routers.py`."""

    status: str


class ParentResponse(BaseModel):
    id: str
    organization_id: str
    user_id: str
    full_name: str
    phone: str | None
    status: str


class ParentSummaryResponse(BaseModel):
    id: str
    full_name: str
    status: str


class RegisterParentRequest(BaseModel):
    organization_id: str
    user_id: str
    full_name: str
    phone: str | None = None


class UpdateParentRequest(BaseModel):
    """Uniform-CRUD `PATCH /parents/{id}` (API Contracts §4 preamble). Unlike
    `UpdateStudentRequest`, this bundles `status` alongside `full_name`/`phone` in one
    request — mirroring `iam.api.schemas.UpdateUserRequest`'s composed-fields shape — since no
    dedicated behavioral status sub-route is documented for `/parents` (see `routers.py`'s
    module docstring). `status` accepts `ParentStatus`'s two values (`active`/`inactive`).

    At least one field must be given."""

    full_name: str | None = None
    phone: str | None = None
    status: str | None = None


class LinkParentToStudentRequest(BaseModel):
    """`POST /students/{student_id}/parents` (Phase 10.7 — no documented API Contracts route,
    see `routers.py`'s module docstring). `relationship`/`is_primary` map 1:1 to `student_
    parents`' own columns (Database Design §6.4); both are optional/defaulted since §6.4 marks
    `relationship` nullable and gives `is_primary` no documented default of its own (`false`
    chosen as the least-surprising default, matching a boolean's ordinary zero-value).
    """

    parent_id: str
    relationship: str | None = None
    is_primary: bool = False


class StudentParentLinkResponse(BaseModel):
    """The raw link record — the response body for `POST /students/{student_id}/parents`,
    mirroring `StudentParentDTO`'s shape (`application/queries.py`)."""

    student_id: str
    parent_id: str
    relationship: str | None
    is_primary: bool


class ParentForStudentResponse(BaseModel):
    """`GET /students/{student_id}/parents` — mirrors `ParentForStudentDTO`'s shape."""

    parent_id: str
    full_name: str
    phone: str | None
    status: str
    relationship: str | None
    is_primary: bool


class StudentForParentResponse(BaseModel):
    """`GET /parents/{parent_id}/students` — mirrors `StudentForParentDTO`'s shape."""

    student_id: str
    full_name: str
    status: str
    relationship: str | None
    is_primary: bool


class DriverResponse(BaseModel):
    id: str
    organization_id: str
    user_id: str
    license_no: str
    status: str


class DriverSummaryResponse(BaseModel):
    id: str
    license_no: str
    status: str


class RegisterDriverRequest(BaseModel):
    organization_id: str
    user_id: str
    license_no: str


class UpdateDriverRequest(BaseModel):
    """Uniform-CRUD `PATCH /drivers/{id}` (API Contracts §4 preamble's general uniform-CRUD
    convention — no `/drivers` row exists in §4.3 itself, see `routers.py`'s module docstring).
    Bundles `license_no`/`status` in one request, mirroring `UpdateParentRequest`'s composed-
    fields shape, since no dedicated behavioral status sub-route is documented for `/drivers`
    either.

    At least one field must be given."""

    license_no: str | None = None
    status: str | None = None


class StopResponse(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    sequence_no: int
    geofence_radius_m: int | None


class RouteResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    status: str
    stops: list[StopResponse]


class RouteSummaryResponse(BaseModel):
    id: str
    name: str
    status: str


class CreateRouteRequest(BaseModel):
    organization_id: str
    name: str


class UpdateRouteRequest(BaseModel):
    """Uniform-CRUD `PATCH /routes/{id}` (API Contracts §4 preamble). Bundles `name`/`status`
    in one request, mirroring `UpdateParentRequest`'s composed-fields shape, since no dedicated
    behavioral status sub-route is documented for `/routes` either.

    At least one field must be given."""

    name: str | None = None
    status: str | None = None


class AddStopToRouteRequest(BaseModel):
    """`POST /routes/{route_id}/stops` (API Contracts §4.3 verbatim: "ordered stops").
    `geofence_radius_m` is optional — Database Design §6.6 marks it nullable ("overrides org
    default")."""

    name: str
    latitude: float
    longitude: float
    sequence_no: int
    geofence_radius_m: int | None = None


class TripResponse(BaseModel):
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


class TripSummaryResponse(BaseModel):
    id: str
    vehicle_id: str
    driver_id: str
    route_id: str
    trip_type: str
    status: str
    scheduled_date: date


class ScheduleTripRequest(BaseModel):
    organization_id: str
    vehicle_id: str
    driver_id: str
    route_id: str
    trip_type: str
    scheduled_date: date


class ChangeTripDriverRequest(BaseModel):
    """`PATCH /trips/{id}/driver` (API Contracts §4.3 line 132 verbatim: "change driver — no
    device change")."""

    driver_id: str


class StudentAssignmentResponse(BaseModel):
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


class StudentAssignmentSummaryResponse(BaseModel):
    id: str
    student_id: str
    route_id: str
    status: str


class AssignStudentToRouteRequest(BaseModel):
    organization_id: str
    student_id: str
    route_id: str
    pickup_stop_id: str
    dropoff_stop_id: str
    vehicle_id: str | None = None


class UpdateStudentAssignmentStatusRequest(BaseModel):
    """`POST /student-assignments/{id}/end` (API Contracts §4.3 line 128 verbatim: 'body
    `{status}` -> removed/transferred/graduated/disabled -> CR-1 revocation event')."""

    status: str
