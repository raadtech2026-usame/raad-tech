"""Transport Operations application commands (Backend LLD §4.2 "intent DTOs"). Immutable
request objects describing what the caller wants done, matching `organization.application.
commands`'s exact shape: every command carries the calling `Principal` as `actor`, and
identifiers are plain `str` (converted to value objects inside the service).

Phase 10.2 scope: `Student` lifecycle commands only, matching `domain/entities.py`'s
`Student`-only scope (Phase 10.1).

**No approved document names any of these commands** (Backend LLD §5.2 gives no `Student`
use-case skeleton — confirmed again for this phase; see `services.py`'s module docstring for
the full research record). Names below follow the established `<Verb><Noun>Command` convention
and match `Student`'s own domain method names 1:1 (`Student.enroll` ↔ `EnrollStudentCommand`,
etc.), the same relationship `organization.application.commands` has to `Organization`'s
methods.

**API Contracts §4.3 note:** the only documented Student HTTP surface is `POST /students`
(create) and `POST /students/{id}/status` (body `{status}` → disable/graduate/transfer) — one
endpoint fanning out to three of these four status-change commands, not a per-verb endpoint
each (unlike `fleet_device`'s `/devices/{id}/activate`-style routes). That fan-out is an HTTP
API-layer concern (a later phase); at the application layer each transition is still its own
command, matching `Student`'s own domain method granularity and every sibling module's
1:1 command-per-domain-method convention.

**Phase 10.6 addition: `Parent` commands.** `RegisterParentCommand`/`UpdateParentCommand`/
`ActivateParentCommand`/`DisableParentCommand`, 1:1 with `Parent`'s own domain method names
(`domain/entities.py`) — no `Transfer`/`Graduate` equivalent, since `ParentStatus` is a flat
active/inactive toggle (`domain/value_objects.py`), unlike `StudentStatus`'s four values.
`RegisterParentCommand` (not `EnrollParentCommand`) mirrors `Parent.register`'s own naming,
itself mirroring `Organization.register`/`Vehicle.register`/`Device.register`'s established
"register a new instance of this aggregate" convention — `enroll` is `Student`-specific
ubiquitous language (Ch. 6), not a generic verb this aggregate reuses.

**Phase 10.8 addition: `Driver` commands.** `RegisterDriverCommand`/`UpdateDriverCommand`/
`ActivateDriverCommand`/`DisableDriverCommand`, 1:1 with `Driver`'s own domain method names
(`domain/entities.py`), mirroring `Parent`'s command set exactly (`register`, not `enroll`; no
`Transfer`/`Graduate` equivalent, since `DriverStatus` is likewise a flat active/inactive
toggle).

**Phase 11 addition: `Route`/`Stop` commands.** `CreateRouteCommand` (not `RegisterRouteCommand`
or `EnrollRouteCommand`) — "Route creation" is this phase's own scope wording verbatim, and no
approved document gives Route a more specific ubiquitous-language verb the way `Student.enroll`
has one; flagged as this phase's own naming choice, not a silently-assumed one.
`UpdateRouteCommand`/`ActivateRouteCommand`/`DisableRouteCommand` mirror `Driver`'s command set
shape exactly. `AddStopToRouteCommand`/`RemoveStopFromRouteCommand`/`MoveStopCommand` back the
`Stop` child-entity operations (`domain/entities.py`) — 1:1 with `Route.add_stop`/`remove_stop`/
`move_stop`. Only `AddStopToRouteCommand`/list-stops are reachable via HTTP this phase
(`api/routers.py`'s module docstring); `RemoveStopFromRouteCommand`/`MoveStopCommand` stay
reachable for the future contract revision that documents a route for them, mirroring
`fleet_device.application.commands.RegisterCameraCommand`'s identical "use-case exists, no
approved endpoint yet" posture.

**Phase 12 addition: `Trip` commands.** `ScheduleTripCommand`/`StartTripCommand`/
`EndTripCommand`/`ChangeTripDriverCommand`, 1:1 with `Trip`'s own domain method names
(`domain/entities.py`). `StartTripCommand`/`EndTripCommand`/`ChangeTripDriverCommand` back
API Contracts §4.3's documented `/trips/{id}/start`, `/trips/{id}/end`, `PATCH /trips/{id}/driver`
routes (lines 130-132). `InterruptTripCommand`/`ResumeTripCommand` back `Trip.interrupt`/
`resume` — no approved HTTP route exists for either this phase (`api/routers.py`'s module
docstring), the same "reachable at the application layer only" posture
`RemoveStopFromRouteCommand`/`MoveStopCommand` already establish.

**Phase 13 addition: `StudentAssignment` commands.** `AssignStudentToRouteCommand` — "Assign
Student to Route" is this phase's own task wording verbatim, the same "no more specific approved
verb exists" posture `CreateRouteCommand` already establishes. `RemoveStudentAssignmentCommand`/
`TransferStudentAssignmentCommand`/`GraduateStudentAssignmentCommand`/
`DisableStudentAssignmentCommand`, 1:1 with `StudentAssignment`'s own domain method names
(`domain/entities.py`) — prefixed `StudentAssignment...`, not `Student...`, to stay unambiguous
next to `Student`'s own identically-shaped `TransferStudentCommand`/`GraduateStudentCommand`/
`DisableStudentCommand` above (see `domain/events.py`'s Phase 13 addition for the same
underlying `event_type` collision this naming keeps the *command* layer clear of, even though
the events themselves still collide). All four back the single documented
`POST /student-assignments/{id}/end` route (API Contracts line 128: "status→removed/
transferred/… → CR-1 revocation event"), fanning out by `status` exactly like `Student`'s own
`/status` route already does — the identical one-endpoint-many-commands shape
`services.py`'s module docstring documents for `Student`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from raad.core.tenancy.principal import Principal


@dataclass(frozen=True)
class EnrollStudentCommand:
    organization_id: str
    full_name: str
    external_ref: str | None
    actor: Principal
    #: 2026-09-10 explicit user directive — additive, optional profile fields, not in Database
    #: Design §6.2. `date_of_birth` is a `date` (already parsed at the API boundary, matching
    #: `school_erp`'s own "parse once, at the boundary" convention for structured fields).
    date_of_birth: date | None = None
    gender: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class UpdateStudentCommand:
    student_id: str
    full_name: str
    external_ref: str | None
    actor: Principal
    date_of_birth: date | None = None
    gender: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class TransferStudentCommand:
    student_id: str
    actor: Principal


@dataclass(frozen=True)
class GraduateStudentCommand:
    student_id: str
    actor: Principal


@dataclass(frozen=True)
class ActivateStudentCommand:
    student_id: str
    actor: Principal


@dataclass(frozen=True)
class DisableStudentCommand:
    student_id: str
    actor: Principal


@dataclass(frozen=True)
class RegisterParentCommand:
    """ADR-0003 (accepted): `user_id` is no longer a caller-supplied input — the login-capable
    `iam.User` (role=parent) this `Parent` links to is created by this service itself, via
    `UserProvisioningPort`, from the identity fields below. `email` is new (at least one of
    `email`/`phone` is required by `iam.User`'s own invariant); `phone` is reused as both this
    `Parent`'s own display field and the created `User`'s login phone."""

    organization_id: str
    full_name: str
    email: str | None
    phone: str | None
    actor: Principal
    #: 2026-09-10 explicit user directive — additive, optional family/contact profile fields,
    #: not in Database Design §6.3.
    alternate_phone: str | None = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class UpdateParentCommand:
    parent_id: str
    full_name: str
    phone: str | None
    actor: Principal
    alternate_phone: str | None = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ChildEnrollmentSpec:
    """2026-09-10 explicit user directive (ADR-0041 §2) — one child inside a
    `RegisterParentWithChildrenCommand`. Field-for-field the same shape `EnrollStudentCommand`
    already carries, plus the `student_parents` link fields `StudentParent.link` needs, since
    this spec produces both a `Student` and its link to the new `Parent` in one step."""

    full_name: str
    external_ref: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    notes: str | None = None
    relationship: str | None = None
    is_primary: bool = False


@dataclass(frozen=True)
class RegisterParentWithChildrenCommand:
    """ADR-0041 §2: creates a `Parent` and zero or more `Student`s, linking every child to the
    new parent, in one `TransportOpsUnitOfWork` transaction — the "Add Parent -> add children ->
    Save" primary registration flow. Field-for-field identical to `RegisterParentCommand` plus
    `children`; a request with an empty `children` list behaves exactly like
    `RegisterParentCommand` (a Parent with no children yet, addable later).

    **Family transportation (2026-09-12 business-model correction).** `route_id`/
    `pickup_stop_id`/`dropoff_stop_id`/`vehicle_id` are the family's *one* Vehicle/Route/Stop
    pair, set once here rather than per child — RAAD's "one Parent/family = one bus" rule
    (`services.py`'s `ParentApplicationService` docstring). When `route_id` is given, every
    child in `children` is assigned to that exact same route/stops/vehicle in this same
    transaction; omit all four to register a parent (and children) with no transportation yet,
    assignable later via `SetFamilyTransportationCommand`. `pickup_stop_id`/`dropoff_stop_id`
    are required together with `route_id`; `vehicle_id` alone stays optional, mirroring
    `StudentAssignment.assign`'s own nullable `vehicle_id`."""

    organization_id: str
    full_name: str
    email: str | None
    phone: str | None
    actor: Principal
    alternate_phone: str | None = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    notes: str | None = None
    children: list[ChildEnrollmentSpec] = field(default_factory=list)
    route_id: str | None = None
    pickup_stop_id: str | None = None
    dropoff_stop_id: str | None = None
    vehicle_id: str | None = None


@dataclass(frozen=True)
class ActivateParentCommand:
    parent_id: str
    actor: Principal


@dataclass(frozen=True)
class DisableParentCommand:
    parent_id: str
    actor: Principal


@dataclass(frozen=True)
class GrantParentVideoLiveAccessCommand:
    """ADR-0026 §2. `actor` is org_admin (or founder), never the parent themselves - enforced by
    `require_permission(Permission("transport_ops.parents.grant_video_access"))` at the route."""

    parent_id: str
    actor: Principal


@dataclass(frozen=True)
class RevokeParentVideoLiveAccessCommand:
    parent_id: str
    actor: Principal


@dataclass(frozen=True)
class GrantParentVideoPlaybackAccessCommand:
    parent_id: str
    actor: Principal


@dataclass(frozen=True)
class RevokeParentVideoPlaybackAccessCommand:
    parent_id: str
    actor: Principal


@dataclass(frozen=True)
class LinkParentToStudentCommand:
    """Phase 10.7. `relationship`/`is_primary` are set-once-at-link-time only (Database Design
    §6.4) — no `Update*Command` exists for this pair, matching `StudentParent`'s own domain
    docstring (`domain/entities.py`)."""

    student_id: str
    parent_id: str
    relationship: str | None
    is_primary: bool
    actor: Principal


@dataclass(frozen=True)
class UnlinkParentFromStudentCommand:
    student_id: str
    parent_id: str
    actor: Principal


@dataclass(frozen=True)
class CreateRouteCommand:
    organization_id: str
    name: str
    actor: Principal


@dataclass(frozen=True)
class UpdateRouteCommand:
    route_id: str
    name: str
    actor: Principal


@dataclass(frozen=True)
class ActivateRouteCommand:
    route_id: str
    actor: Principal


@dataclass(frozen=True)
class DisableRouteCommand:
    route_id: str
    actor: Principal


@dataclass(frozen=True)
class AddStopToRouteCommand:
    route_id: str
    name: str
    latitude: float
    longitude: float
    sequence_no: int
    geofence_radius_m: int | None
    actor: Principal


@dataclass(frozen=True)
class RemoveStopFromRouteCommand:
    """No approved HTTP route yet (`api/routers.py`'s module docstring) — reachable at the
    application layer only, mirroring `RegisterCameraCommand`'s identical posture."""

    route_id: str
    stop_id: str
    actor: Principal


@dataclass(frozen=True)
class MoveStopCommand:
    """No approved HTTP route yet (`api/routers.py`'s module docstring) — reachable at the
    application layer only, mirroring `RegisterCameraCommand`'s identical posture."""

    route_id: str
    stop_id: str
    new_sequence_no: int
    actor: Principal


@dataclass(frozen=True)
class RegisterDriverCommand:
    """ADR-0003 (accepted): `user_id` is no longer a caller-supplied input — see
    `RegisterParentCommand`'s identical docstring. `Driver` itself carries no `full_name` of its
    own (unlike `Parent`), so `full_name`/`email`/`phone` here exist solely to provision the
    linked `iam.User` (role=driver)."""

    organization_id: str
    full_name: str
    email: str | None
    phone: str | None
    license_no: str
    actor: Principal


@dataclass(frozen=True)
class UpdateDriverCommand:
    driver_id: str
    license_no: str
    actor: Principal


@dataclass(frozen=True)
class ActivateDriverCommand:
    driver_id: str
    actor: Principal


@dataclass(frozen=True)
class DisableDriverCommand:
    driver_id: str
    actor: Principal


@dataclass(frozen=True)
class ScheduleTripCommand:
    organization_id: str
    vehicle_id: str
    driver_id: str
    route_id: str
    trip_type: str
    scheduled_date: date
    actor: Principal


@dataclass(frozen=True)
class StartTripCommand:
    trip_id: str
    actor: Principal


@dataclass(frozen=True)
class EndTripCommand:
    trip_id: str
    actor: Principal


@dataclass(frozen=True)
class InterruptTripCommand:
    """No approved HTTP route yet (`api/routers.py`'s module docstring) — reachable at the
    application layer only, mirroring `RemoveStopFromRouteCommand`'s identical posture."""

    trip_id: str
    reason: str
    actor: Principal


@dataclass(frozen=True)
class ResumeTripCommand:
    """No approved HTTP route yet (`api/routers.py`'s module docstring) — reachable at the
    application layer only, same posture as `InterruptTripCommand` above."""

    trip_id: str
    actor: Principal


@dataclass(frozen=True)
class ChangeTripDriverCommand:
    trip_id: str
    driver_id: str
    actor: Principal


@dataclass(frozen=True)
class AssignStudentToRouteCommand:
    organization_id: str
    student_id: str
    route_id: str
    pickup_stop_id: str
    dropoff_stop_id: str
    vehicle_id: str | None
    actor: Principal


@dataclass(frozen=True)
class RemoveStudentAssignmentCommand:
    student_assignment_id: str
    actor: Principal


@dataclass(frozen=True)
class TransferStudentAssignmentCommand:
    student_assignment_id: str
    actor: Principal


@dataclass(frozen=True)
class GraduateStudentAssignmentCommand:
    student_assignment_id: str
    actor: Principal


@dataclass(frozen=True)
class DisableStudentAssignmentCommand:
    student_assignment_id: str
    actor: Principal


@dataclass(frozen=True)
class SetFamilyTransportationCommand:
    """2026-09-12 business-model correction: RAAD's "one Parent/family = one bus" rule made
    structural, not merely validated — see `ParentApplicationService.set_family_transportation`'s
    own docstring (`services.py`). Ends every one of this Parent's linked children's current
    active `StudentAssignment` (if any) and creates a fresh one for each, all sharing this exact
    route/stops/vehicle, in one transaction. Used both to assign a family's transportation for
    the first time (an existing parent registered before this correction, or one who skipped it
    at registration) and to change it later — the same one operation either way."""

    parent_id: str
    route_id: str
    pickup_stop_id: str
    dropoff_stop_id: str
    actor: Principal
    vehicle_id: str | None = None
