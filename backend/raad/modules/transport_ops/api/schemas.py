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

from datetime import date, datetime, time

from typing import Literal

from pydantic import BaseModel, Field


class StudentResponse(BaseModel):
    id: str
    organization_id: str
    full_name: str
    external_ref: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    #: 2026-09-10 explicit user directive — additive, optional profile fields, not in Database
    #: Design §6.2.
    date_of_birth: date | None = None
    gender: str | None = None
    notes: str | None = None


class StudentSummaryResponse(BaseModel):
    id: str
    full_name: str
    status: str


class CountResponse(BaseModel):
    """RAAD business model realignment: the RAAD Platform "may only display aggregated
    statistics... Total Students (count only), Total Parents (count only)" but "must not list
    or manage individual Students or Parents across organizations." `GET /students`/
    `GET /parents` already carry a `.total` on their own paginated envelope, but reaching that
    requires `transport_ops.students.list`/`.parents.list` — exactly the permission RAAD
    Platform roles no longer hold (migration `c4d9a2e6f813`). This is the narrower response
    shape that lets a caller learn *how many* without being able to list *which* — reused
    identically by `GET /students/count` and `GET /parents/count`."""

    total: int


class EnrollStudentRequest(BaseModel):
    organization_id: str
    full_name: str
    external_ref: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    notes: str | None = None


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

    2026-09-10: extended with the additive `date_of_birth`/`gender`/`notes` profile fields, in
    the same uniform `PATCH` rather than a second route — one "edit this student's profile"
    surface, matching `Student.update_details`'s own extension.

    At least one field must be given."""

    full_name: str | None = None
    external_ref: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    notes: str | None = None


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
    has_video_live_access: bool
    has_video_playback_access: bool
    created_at: datetime
    updated_at: datetime
    #: 2026-09-10 explicit user directive — additive, optional family/contact profile fields,
    #: not in Database Design §6.3.
    alternate_phone: str | None = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    notes: str | None = None


class ParentSummaryResponse(BaseModel):
    id: str
    full_name: str
    status: str


class ChildEnrollmentRequest(BaseModel):
    """One child inside `RegisterParentRequest.children` (ADR-0041 §2) — the same fields
    `EnrollStudentRequest` takes, minus `organization_id` (the parent's own), plus the
    `student_parents` link fields `POST /students/{id}/parents` normally takes separately."""

    full_name: str
    external_ref: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    notes: str | None = None
    relationship: str | None = None
    is_primary: bool = False


class RegisterParentRequest(BaseModel):
    """ADR-0003 (accepted): `user_id` is no longer supplied by the caller — the login-capable
    `iam.User` (role=parent) is provisioned by this service itself from `full_name`/`email`/
    `phone` below (at least one of `email`/`phone` required, `iam.User`'s own invariant).

    **`children` (ADR-0041 §2, 2026-09-10):** when given (even as an empty list), the Parent and
    every listed child are created and linked together in one transaction
    (`ParentApplicationService.register_parent_with_children`). When omitted (`None`, the
    default), behaviour is byte-for-byte the original `register_parent` path — this is one
    endpoint with an additive optional field, not a second competing one.

    **`route_id`/`pickup_stop_id`/`dropoff_stop_id`/`vehicle_id` (2026-09-12 business-model
    correction):** the family's *one* transportation assignment, applied identically to every
    listed child in the same transaction — RAAD's "one Parent/family = one bus" rule. Only
    consumed when `children` is also given; `pickup_stop_id`/`dropoff_stop_id` are required
    together with `route_id` (`vehicle_id` alone stays optional). Omit all four to register a
    parent (and children) with no transportation yet — assignable later via
    `PUT /parents/{id}/transportation`."""

    organization_id: str
    full_name: str
    email: str | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    notes: str | None = None
    children: list[ChildEnrollmentRequest] | None = None
    route_id: str | None = None
    pickup_stop_id: str | None = None
    dropoff_stop_id: str | None = None
    vehicle_id: str | None = None


class ParentCreatedResponse(BaseModel):
    """`POST /parents`'s actual response shape (ADR-0003/ADR-0017) — wraps the usual
    `ParentResponse` with the generated one-time temporary password for the new linked login,
    surfaced exactly once, here, for hand-off. Never re-derivable via `GET /parents/{id}`.

    `children` (ADR-0041 §2) is populated exactly when the request's own `children` was given —
    every child `Student` created and linked in the same transaction as `parent`."""

    parent: ParentResponse
    temporary_password: str
    children: list[StudentResponse] = []


class UpdateParentRequest(BaseModel):
    """Uniform-CRUD `PATCH /parents/{id}` (API Contracts §4 preamble). Unlike
    `UpdateStudentRequest`, this bundles `status` alongside `full_name`/`phone` in one
    request — mirroring `iam.api.schemas.UpdateUserRequest`'s composed-fields shape — since no
    dedicated behavioral status sub-route is documented for `/parents` (see `routers.py`'s
    module docstring). `status` accepts `ParentStatus`'s two values (`active`/`inactive`).

    2026-09-10: extended with the additive `alternate_phone`/`address`/`emergency_contact_name`/
    `emergency_contact_phone`/`notes` profile fields, in the same composed `PATCH`, matching
    `Parent.update_details`'s own extension.

    At least one field must be given."""

    full_name: str | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    notes: str | None = None
    status: str | None = None


class UpdateParentVideoAccessRequest(BaseModel):
    """`PATCH /parents/{id}/video-access` (ADR-0026 §2) — a dedicated route, not folded into
    `UpdateParentRequest` above, because it is gated by its own, more restrictive permission
    (`transport_ops.parents.grant_video_access`, org_admin/founder only) rather than
    `transport_ops.parents.update`. At least one field must be given."""

    has_video_live_access: bool | None = None
    has_video_playback_access: bool | None = None


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
    date_of_birth: date | None = None


class DriverResponse(BaseModel):
    id: str
    organization_id: str
    user_id: str
    license_no: str
    status: str
    created_at: datetime
    updated_at: datetime
    #: ADR-0049: the staff record holding this driver's name and phone.
    staff_id: str


class DriverSummaryResponse(BaseModel):
    id: str
    license_no: str
    status: str
    staff_id: str
    #: The staff member's name (ADR-0049); `None` only if the staff record is out of scope.
    full_name: str | None = None


class RegisterDriverRequest(BaseModel):
    """ADR-0003 (accepted): `user_id` is no longer supplied by the caller — see
    `RegisterParentRequest`'s identical docstring. `Driver` itself has no `full_name` of its
    own, so `full_name`/`email`/`phone` here exist solely to provision the linked `iam.User`
    (role=driver)."""

    organization_id: str
    full_name: str
    email: str | None = None
    phone: str | None = None
    license_no: str


class DriverCreatedResponse(BaseModel):
    """`POST /drivers`'s actual response shape — mirrors `ParentCreatedResponse` exactly."""

    driver: DriverResponse
    temporary_password: str


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
    created_at: datetime
    updated_at: datetime
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
    created_at: datetime
    updated_at: datetime
    #: ADR-0052/0054.
    timetable_entry_id: str | None = None
    planned_departure: time | None = None
    cancelled_at: datetime | None = None
    cancelled_reason: str | None = None


class TripSummaryResponse(BaseModel):
    id: str
    vehicle_id: str
    driver_id: str
    route_id: str
    trip_type: str
    status: str
    scheduled_date: date
    planned_departure: time | None = None


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
    created_at: datetime
    updated_at: datetime


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


class SetFamilyTransportationRequest(BaseModel):
    """`PUT /parents/{parent_id}/transportation` (2026-09-12 business-model correction): the
    family's one Vehicle/Route/Stop pair, applied identically to every one of this Parent's
    linked children. Unlike `AssignStudentToRouteRequest`, this has no `organization_id` field —
    the Parent's own is used, and no `student_id` — every currently-linked child is affected."""

    route_id: str
    pickup_stop_id: str
    dropoff_stop_id: str
    vehicle_id: str | None = None


class SetFamilyTransportationResponse(BaseModel):
    """One row per child actually (re)assigned — empty when the Parent has no linked children
    yet (a legal no-op, not an error)."""

    assignments: list[StudentAssignmentResponse]


# ---- ADR-0049/0050/0051: transport staff, bus crew, staff documents ----------------------------


class StaffRoleRequest(BaseModel):
    """Create a job title (`organization_id` required) or update one (ignored)."""

    organization_id: str | None = None
    name: str = Field(min_length=1, max_length=80)
    sort_order: int = Field(default=0, ge=0, le=10000)
    is_archived: bool = False


class StaffRoleResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    sort_order: int
    is_archived: bool


class StaffSetupDefaultsRequest(BaseModel):
    organization_id: str | None = None


class RegisterTransportStaffRequest(BaseModel):
    """`organization_id` may be omitted by an Org Admin; it is then their own."""

    organization_id: str | None = None
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = None
    alternate_phone: str | None = None
    role_id: str | None = None
    employee_ref: str | None = Field(default=None, max_length=64)
    start_date: date | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_phone: str | None = None
    notes: str | None = None


class UpdateTransportStaffRequest(BaseModel):
    """Partial update: only fields present in the body change; `null` clears a field."""

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = None
    alternate_phone: str | None = None
    role_id: str | None = None
    employee_ref: str | None = Field(default=None, max_length=64)
    start_date: date | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_phone: str | None = None
    notes: str | None = None


class ChangeTransportStaffStatusRequest(BaseModel):
    status: Literal["active", "inactive", "left"]


class StaffDriverProfileResponse(BaseModel):
    driver_id: str
    user_id: str
    license_no: str
    status: str


class TransportStaffSummaryResponse(BaseModel):
    id: str
    organization_id: str
    full_name: str
    phone: str | None
    role_id: str | None
    role_name: str | None
    employee_ref: str | None
    status: str
    is_driver: bool


class TransportStaffResponse(BaseModel):
    """`emergency_contact_name`/`emergency_contact_phone` are `null` for every caller but the
    Org Admin (ADR-0049 §6); `private_fields_visible` says which case applies, so a `null` is
    never mistaken for "not recorded"."""

    id: str
    organization_id: str
    full_name: str
    phone: str | None
    alternate_phone: str | None
    role_id: str | None
    role_name: str | None
    employee_ref: str | None
    start_date: date | None
    status: str
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    notes: str | None
    left_on: date | None
    driver: StaffDriverProfileResponse | None
    private_fields_visible: bool
    created_at: datetime
    updated_at: datetime


class GrantDriverAccessRequest(BaseModel):
    """Login details for a staff member becoming a driver. `phone` defaults to the staff
    record's own phone; the login needs an email or a phone."""

    license_no: str = Field(min_length=1, max_length=64)
    email: str | None = None
    phone: str | None = None


class AssignStaffToVehicleRequest(BaseModel):
    staff_id: str
    vehicle_id: str
    kind: Literal["permanent", "temporary"] = "permanent"
    starts_on: date | None = None
    ends_on: date | None = None
    route_id: str | None = None
    role_id: str | None = None
    reason: str | None = Field(default=None, max_length=255)


class EndStaffAssignmentRequest(BaseModel):
    ends_on: date | None = None


class VehicleStaffAssignmentResponse(BaseModel):
    id: str
    organization_id: str
    staff_id: str
    staff_name: str
    vehicle_id: str
    role_id: str | None
    role_name: str | None
    route_id: str | None
    starts_on: date
    ends_on: date | None
    kind: str
    reason: str | None
    is_current: bool
    created_at: datetime


class StaffDocumentTypeRequest(BaseModel):
    organization_id: str | None = None
    name: str = Field(min_length=1, max_length=80)
    alert_lead_days: list[int] = Field(default_factory=lambda: [30, 7], max_length=5)
    is_archived: bool = False


class StaffDocumentTypeResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    alert_lead_days: list[int]
    is_archived: bool


class RecordStaffDocumentRequest(BaseModel):
    type_id: str
    number: str | None = Field(default=None, max_length=64)
    issued_on: date | None = None
    expires_on: date | None = None
    notes: str | None = None
    replaces_id: str | None = None


class UpdateStaffDocumentRequest(BaseModel):
    """Partial update: only fields present in the body change."""

    number: str | None = Field(default=None, max_length=64)
    issued_on: date | None = None
    expires_on: date | None = None
    notes: str | None = None


class StaffDocumentResponse(BaseModel):
    """`number` is `null` for every caller but the Org Admin (ADR-0051 §2)."""

    id: str
    organization_id: str
    staff_id: str
    staff_name: str
    type_id: str
    type_name: str
    number: str | None
    issued_on: date | None
    expires_on: date | None
    notes: str | None
    status: str
    days_left: int | None
    replaced_by_id: str | None
    private_fields_visible: bool
    created_at: datetime


# ---- ADR-0052/0053/0054: daily transport operations -----------------------------------------


class TimetableEntryRequest(BaseModel):
    organization_id: str | None = None
    route_id: str
    vehicle_id: str
    trip_type: Literal["morning", "afternoon"]
    weekdays: list[int] = Field(min_length=1, max_length=7)
    default_driver_id: str
    valid_from: date
    valid_until: date | None = None
    planned_departure: time | None = None
    is_active: bool = True


class TimetableEntryResponse(BaseModel):
    id: str
    organization_id: str
    route_id: str
    route_name: str | None
    vehicle_id: str
    trip_type: str
    weekdays: list[int]
    planned_departure: time | None
    default_driver_id: str
    default_driver_name: str | None
    valid_from: date
    valid_until: date | None
    is_active: bool


class ClosureRequest(BaseModel):
    organization_id: str | None = None
    starts_on: date
    ends_on: date
    label: str = Field(min_length=1, max_length=120)


class ClosureResponse(BaseModel):
    id: str
    organization_id: str
    starts_on: date
    ends_on: date
    label: str
    withdrawn_at: datetime | None


class UnavailabilityRequest(BaseModel):
    staff_id: str
    starts_on: date
    ends_on: date
    reason: Literal["sick", "personal", "training", "other"]
    note: str | None = Field(default=None, max_length=500)


class CoverRequest(BaseModel):
    unavailability_id: str
    substitute_staff_id: str
    vehicle_id: str
    starts_on: date | None = None
    ends_on: date | None = None


class CoverResponse(BaseModel):
    id: str
    unavailability_id: str
    absent_staff_id: str
    absent_staff_name: str
    substitute_staff_id: str
    substitute_staff_name: str
    vehicle_id: str
    starts_on: date
    ends_on: date
    withdrawn_at: datetime | None
    trips_reassigned: int = 0
    warnings: list[str] = []


class UnavailabilityResponse(BaseModel):
    """`note` is `null` for everyone but the Org Admin (ADR-0053 §1)."""

    id: str
    organization_id: str
    staff_id: str
    staff_name: str
    starts_on: date
    ends_on: date
    reason: str
    note: str | None
    withdrawn_at: datetime | None
    covers: list[CoverResponse]
    private_fields_visible: bool


class BoardTripResponse(BaseModel):
    id: str
    trip_type: str
    route_id: str
    route_name: str | None
    planned_departure: time | None
    driver_id: str
    driver_name: str | None
    status: str
    cancelled_reason: str | None
    uncovered_reason: str | None


class BoardCrewResponse(BaseModel):
    staff_id: str
    staff_name: str
    role_name: str | None
    is_substitute: bool
    is_unavailable: bool
    covered_by: str | None


class BoardVehicleResponse(BaseModel):
    vehicle_id: str
    trips: list[BoardTripResponse]
    crew: list[BoardCrewResponse]
    crew_gaps: int


class DailyBoardResponse(BaseModel):
    date: date
    closures: list[str]
    vehicles: list[BoardVehicleResponse]
    uncovered_trips: int


class GenerateTripsRequest(BaseModel):
    start: date | None = None
    days: int = Field(default=7, ge=1, le=31)
    dry_run: bool = False


class PlannedTripResponse(BaseModel):
    timetable_entry_id: str
    scheduled_date: date
    trip_type: str
    route_id: str
    vehicle_id: str
    driver_id: str
    is_substitute: bool


class SkippedTripResponse(BaseModel):
    timetable_entry_id: str
    scheduled_date: date | None
    reason: str


class GenerationResultResponse(BaseModel):
    start: date
    days: int
    dry_run: bool
    to_create: list[PlannedTripResponse]
    skipped: list[SkippedTripResponse]
    closed_days: list[date]
    created: int


class CancelTripRequest(BaseModel):
    """The reason is shown to the parents of the children on this trip (ADR-0054 §2)."""

    reason: str = Field(min_length=1, max_length=255)
