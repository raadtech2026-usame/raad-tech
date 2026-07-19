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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from raad.core.tenancy.principal import Principal


@dataclass(frozen=True)
class EnrollStudentCommand:
    organization_id: str
    full_name: str
    external_ref: str | None
    actor: Principal


@dataclass(frozen=True)
class UpdateStudentCommand:
    student_id: str
    full_name: str
    external_ref: str | None
    actor: Principal


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
    organization_id: str
    user_id: str
    full_name: str
    phone: str | None
    actor: Principal


@dataclass(frozen=True)
class UpdateParentCommand:
    parent_id: str
    full_name: str
    phone: str | None
    actor: Principal


@dataclass(frozen=True)
class ActivateParentCommand:
    parent_id: str
    actor: Principal


@dataclass(frozen=True)
class DisableParentCommand:
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
    organization_id: str
    user_id: str
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
