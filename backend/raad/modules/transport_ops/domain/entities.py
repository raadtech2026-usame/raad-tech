"""Transport Operations entities (Backend LLD §5.1/§5.2; Database Design §6.2). Framework-
free — no SQLAlchemy/Pydantic/FastAPI, no I/O. Behavior methods mutate state, enforce
invariants, and buffer the resulting `DomainEvent`s, matching the same shape as
`modules.organization.domain.entities` (`Clock` passed in, never called internally, so
behavior stays deterministic and unit-testable with a fake clock).

**Phase 10.1 scope: `Student` only** — confirmed with the user before implementing, after
research surfaced that `transport_ops`'s C4 bounded context (Database Design §6) covers seven
tables (`students`, `parents`, `student_parents`, `routes`, `stops`, `trips`,
`student_assignments`, `trip_students`). Two competing precedents exist in this codebase for how
much to build in one domain-layer phase: `tracking`'s Phase 8.1 built exactly two tightly-scoped
entities (`VehiclePosition`, `GeofenceCrossing`), deferring `Route`/`Stop`/`Trip` entirely;
`fleet_device`'s Phase 7.1 built three entities (`Vehicle`, `Device`, `DeviceAssignment`)
together in one phase. The user chose the tighter `tracking`-style scope: this phase implements
only `students` (Database Design §6.2). `student_assignments` (§6.7, "the CR-1 access gate" —
student↔route↔stops↔vehicle) is a distinct aggregate with its own 5-value status enum, its own
generated-column uniqueness constraint, and its own documented event set
(`StudentAssignmentRemoved`/`Transferred`/`Graduated`/`Disabled`, Backend LLD §10.3) — left for
a later phase. `Parent`/`student_parents` (§6.3/§6.4), `Route`/`Stop` (§6.5/§6.6), and
`Trip`/`trip_students` (§6.8/§6.9) are likewise out of scope; `Student` holds no field
referencing any of them (see below).

**Why `Student` holds no `route_id`/`trip_id`/`parent_id` field.** Database Design confirms the
`students` table itself carries no such column — the student↔route↔stops↔vehicle linkage lives
entirely in `student_assignments` (§6.7) and the student↔trip roster snapshot lives in
`trip_students` (§6.9); both are separate tables/aggregates this phase does not build. Modeling
a `route_id` directly on `Student` here would invent a column no approved document defines.

**No documented state-transition diagram for `students.status`** (`active/disabled/graduated/
transferred`, Database Design §6.2) — unlike `Device`'s Phase 2 §19.2 diagram or `Trip`'s Phase
2 §6.2 machine, only the flat enum plus its CR-1 consequence are documented (see `value_objects.
py`'s `StudentStatus` docstring). Every status-change method below is therefore directly
settable with an idempotent same-state no-op — the exact precedent `organization.domain.
entities.Organization.suspend/reactivate/deactivate` already establishes in this same codebase
for an equally undocumented transition set, not an invented restriction graph.

**"Student transport eligibility" is not modeled here.** Research found no approved document
defining a transport-eligibility concept distinct from the CR-1 parent-access gate
(`SubscriptionAccessPolicy`, Backend LLD §5.4) — which is itself owned by `billing`/`core/
policies`, not `transport_ops` (mirroring `organization.domain.policies`'s identical reasoning
for why `SubscriptionAccessPolicy`/`VideoAccessPolicy` aren't domain policies of that module
either). See `policies.py`.

**Phase 10.2 addendum: `update_details`.** The Phase 10.2 application layer needs an
`UpdateStudentCommand` (editing `full_name`/`external_ref` post-enrollment) with no matching
domain behavior method here — flagged as a conflict between that phase's own instructions
("reuse only the completed Student Domain" vs. "implement `UpdateStudentCommand`") and
confirmed with the user before adding this single, strictly-additive method below, rather than
having the application layer mutate `full_name`/`external_ref` directly (which would either
bypass this class's own validation or force the application layer to duplicate it — both
forbidden). `_validate_full_name`/`_validate_external_ref` are factored out so `__init__` and
`update_details` share exactly one copy of each rule.

**Phase 10.6 scope: `Parent` added.** The `Parent` aggregate only (Database Design §6.3) —
`student_parents` linking (§6.4), guardian relationships beyond this aggregate, notifications,
authentication, and any change to `Student` are explicitly out of scope for this phase, per
its own instructions. `Parent` holds no field referencing `Student`/`student_parents`, for the
identical reason `Student` above holds no `route_id`/`trip_id`/`parent_id`.

**Phase 10.7 addition: `StudentParent`.** The M:N association between `Student` and `Parent`
(Database Design §6.4). Confirmed with the user before implementing: §6.4 lists exactly four
columns (`student_id`, `parent_id`, `relationship`, `is_primary`) with composite PK
`(student_id, parent_id)` and **no** "+ standard audit cols" line — unlike every other table in
that document, including `students`/`parents` above. `StudentParent` is therefore modeled with
no surrogate `id` and no audit/soft-delete fields, unlike every other aggregate in this file;
its constructor only carries the four persisted columns. Neither `Student` nor `Parent` gain a
field referencing the other — the association lives entirely in this separate aggregate, the
same reasoning `student_assignments`/`trip_students` are deferred as their own tables rather
than inlined fields (see this module's Phase 10.1 scope note above).

**Phase 10.8 addition: `Driver`.** The `Driver` aggregate only (Database Design §6.1, ADR-0001:
Driver owned by `transport_ops`, "no separate driver identity concern beyond IAM login"). Mirrors
`Parent`'s exact shape — a profile linked to an `iam.User` login via `user_id`, tenant-owned,
flat active/inactive status — since Database Design §6.1's own compact notation
(`drivers(id, organization_id, user_id FK→users, license_no, status, +audit)`) is structurally
identical to §6.3's `parents(...)` notation, just with `license_no` in place of
`full_name`/`phone`. `Driver` holds no `vehicle_id`/`trip_id`/`route_id` field — §6.1's own
closing line ("Vehicle↔driver is per-trip ... not stored here") places that linkage entirely on
the out-of-scope `Trip` aggregate (`trips.driver_id`), the same reasoning `Student` above holds
no `route_id`/`trip_id`/`parent_id` of its own.

**Phase 11 addition: `Route` (+ `Stop` child entity).** Database Design §6.5/§6.6 define
`routes`/`stops` as a 1:N parent-child pair (`stops.route_id → routes.id`), not an M:N like
`student_parents` — structurally the same shape `fleet_device.domain.entities.Device` (root) /
`Camera` (child) already establishes for this codebase, verified before implementing: camera
channel-uniqueness (`ux_cameras__device_channel`) is an intra-aggregate invariant enforced by
the `Device` root, and `ux_stops__route_sequence` is the identical shape for `Route`/`Stop`.
`Stop` is therefore modeled the same way `Camera` is — identity + fields only, no aggregate
root behavior of its own, mutated exclusively through `Route`'s own methods
(`add_stop`/`remove_stop`/`move_stop`).

**Naming note.** The task's own scope names this "RouteStop" descriptively (the Stop entity
within a Route's aggregate boundary); the class below is named `Stop`, matching Database
Design §6.6's table name and Project Brief Ch. 6.9's ubiquitous-language noun exactly
(`.claude/rules/naming.md`: "use the Ch. 6 ubiquitous language verbatim ... Stop"), the same
"table/ubiquitous-language name, not a compound" convention `Camera` (not `DeviceCamera`)
already establishes for an identically-shaped child entity.

**No `Route.archive()` — flagged, not silently built.** Database Design §6.5 gives
`routes.status ENUM(active,inactive)` — exhaustively two values, no `archived`. This phase's
own scope lists "Archive (if specified)"; since no approved document specifies a third status
value or an archival concept for routes, `activate`/`disable` are the only two lifecycle
methods here, the same restraint `ParentStatus`/`DriverStatus` already establish for their own
undocumented-richer-lifecycle situations (`value_objects.py`).

**Stop validation scope.** `add_stop`/`move_stop` enforce: `sequence_no` is a positive integer
(a sequence number of 0 or below is not a meaningful position); `latitude`/`longitude` fall
within the actual geographic range a coordinate can hold (±90/±180) — a definitional bound on
what the DECIMAL(9,6) columns represent, not an invented business rule; and
`ux_stops__route_sequence` (no two stops in one route share a `sequence_no`) as an
intra-aggregate invariant, the same reasoning `Device.register_camera` gives for
`ux_cameras__device_channel`. No "sequence numbers must be contiguous, no gaps" rule is
enforced — no approved document requires it, and inventing one would reject a legitimate
delete-the-middle-stop-and-renumber-later workflow no design document forbids.

**Phase 12 addition: `Trip`.** Database Design §6.8's aggregate — vehicle+driver+route for a
day's journey. Confirmed with the user before implementing: `trip_students` (§6.9, "roster
snapshot") is deferred entirely this phase, since its documented data source,
`student_assignments` (§6.7), is not built yet — `Trip` therefore holds no roster/student
reference, the same "don't model what an out-of-scope table would supply" reasoning `Student`'s
own module docstring gives for its absent `route_id`/`trip_id`/`parent_id` fields above.
`Trip.vehicle_id` is a cross-module reference (`value_objects.py`'s Phase 12 addition) —
opaque, never existence-checked — while `driver_id`/`route_id` are same-module references,
existence-checked at the application layer (`ensure_driver_exists`/`ensure_route_exists`,
`application/validators.py`) exactly like `ensure_student_exists`/`ensure_parent_exists`
already are for `StudentParent`.

Unlike every prior aggregate in this module, `Trip.status` has a **documented transition
graph** (Phase-2 §6.2), not a flat undocumented toggle — so `Trip`'s behavior methods below are
the first in this module to raise `RuleViolationError` for an illegal transition, rather than
silently treating every value as directly settable. `interrupt()`'s `reason` is carried only in
the `TripInterrupted` event payload, never persisted on the row — Database Design §6.8 has no
`interrupted_at`/`interrupt_reason` column, so no such field is invented here.

**Phase 13 addition: `StudentAssignment`.** Database Design §6.7's aggregate — "the CR-1 access
gate" binding Student↔Route↔pickup/dropoff Stop, with an optional assigned Vehicle. Confirmed
with the user before implementing: `trip_students` snapshot generation, `Notifications`,
`Billing`, and geofence processing are all explicitly out of scope for this phase, per its own
instructions — `StudentAssignment` therefore has no field or method touching any of those.

**No documented transition graph for `student_assignments.status`** — mirrors `StudentStatus`'s
exact situation (`value_objects.py`'s Phase 13 addition), not `TripStatus`'s: every status is
directly settable with an idempotent same-state no-op, the same `organization.domain.entities.
Organization.suspend/reactivate/deactivate` precedent `Student` already follows. `ended_at` is
set only on the specific transition where `self.status == ACTIVE` at the moment a non-active
status is applied — matching Database Design §6.7's literal wording ("set when status **leaves**
active") precisely; a later move between two already-non-active statuses (e.g. `removed` ->
`disabled`) does not re-stamp it. This is an interpretive reading of ambiguous wording, flagged
here rather than silently picked.

**Event-name collision — flagged, not silently resolved.** Backend LLD §5.4 names this
aggregate's four status-change events verbatim: `StudentAssignmentRemoved`, `StudentTransferred`,
`StudentGraduated`, `StudentDisabled` (`domain/events.py`'s Phase 13 addition uses these exact
strings). Three of the four — `StudentTransferred`/`StudentGraduated`/`StudentDisabled` — are
**already** the exact `event_type` strings the `Student` aggregate's own status-change methods
emit (Phase 10.1, this file's own `Student.transfer`/`graduate`/`disable`, `aggregate_type=
"Student"`). The LLD's own event catalog does not disambiguate which aggregate emits these names
— read in context (§5.4's "Inputs" section defines `assignment_state` as the
`student_assignments`-owned fact), they are unambiguously meant for *this* aggregate, not
`Student`. Implemented here exactly as named, matching the task's explicit instruction — the
collision (identical `event_type`, distinguished only by `aggregate_type`) is a pre-existing LLD
naming gap, surfaced now because this is the first phase to actually implement the second half
of it, not something invented by this implementation.

**`created_at`/`updated_at` not exposed — a pre-existing, module-wide gap, not new.** API
Contracts §6's documented example resource for this aggregate includes `created_at`/`updated_at`
in the response body. No aggregate in this module (`Student`/`Parent`/`Driver`/`Route`/`Trip`)
has ever carried these as domain fields — they are ORM-only audit columns
(`core/db/mixins.py`), invisible to the domain layer by this codebase's own established layering
(`.claude/rules/backend.md` #2). Adding them only for `StudentAssignment` would create a
one-off inconsistency across the module rather than fix anything; retrofitting all five prior
aggregates is a cross-cutting change well beyond this phase's scope. Flagged here and in the
final report, not silently resolved either way.

**Pickup/dropoff stop validation.** `pickup_stop_id`/`dropoff_stop_id` are validated for
existence by checking membership in the already-loaded `Route`'s own `stops` collection
(`application/validators.py`) — the only way a `Stop`'s existence can be checked at all, since
`Stop` has no repository of its own (`domain/repositories.py`'s Phase 11 addition: it is a
`Route`-owned child entity). This is existence-checking, not an invented "stop must belong to
this route" business rule — no other route could be checked against regardless."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from raad.core.errors.exceptions import ConflictError, DomainError, RuleViolationError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain import events as transport_ops_events
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    DriverStatus,
    Gender,
    IncidentCategory,
    IncidentId,
    IncidentNoteId,
    IncidentNoteKind,
    IncidentSeverity,
    IncidentStatus,
    OperatingClosureId,
    OrganizationId,
    ParentId,
    ParentStatus,
    PhoneNumber,
    RouteId,
    RouteStatus,
    RouteTimetableEntryId,
    StaffAssignmentKind,
    StaffCoverId,
    StaffDocumentId,
    StaffDocumentEnforcement,
    StaffDocumentRequirement,
    StaffDocumentStatus,
    StaffDocumentTypeId,
    StaffUnavailabilityId,
    StopId,
    StudentAssignmentId,
    StudentAssignmentStatus,
    StudentId,
    StudentStatus,
    TripId,
    TripStatus,
    TransportStaffId,
    TransportStaffRoleId,
    TransportStaffStatus,
    TripType,
    UnavailabilityReason,
    UserId,
    VehicleId,
    VehicleStaffAssignmentId,
)

_FULL_NAME_MAX_LENGTH = 200  # Database Design §6.2: full_name VARCHAR(200)
_EXTERNAL_REF_MAX_LENGTH = 64  # Database Design §6.2: external_ref VARCHAR(64)


def _validate_full_name(full_name: str) -> None:
    if not full_name:
        raise DomainError("Student full_name must not be empty")
    if len(full_name) > _FULL_NAME_MAX_LENGTH:
        raise DomainError(
            f"Student full_name must be at most {_FULL_NAME_MAX_LENGTH} characters: "
            f"{len(full_name)}"
        )


def _validate_external_ref(external_ref: str | None) -> None:
    if external_ref is not None and len(external_ref) > _EXTERNAL_REF_MAX_LENGTH:
        raise DomainError(
            f"Student external_ref must be at most {_EXTERNAL_REF_MAX_LENGTH} "
            f"characters: {len(external_ref)}"
        )


# 2026-09-10 explicit user directive (Parent & Student Domain Restructure) — additive profile
# fields, not in Database Design §6.2/§6.3. See `value_objects.py`'s own module-level comment
# for why these particular bounds.
_NOTES_MAX_LENGTH = 500
_ADDRESS_MAX_LENGTH = 255
_EMERGENCY_CONTACT_NAME_MAX_LENGTH = 200


def _validate_notes(notes: str | None, *, field: str = "notes") -> None:
    if notes is not None and len(notes) > _NOTES_MAX_LENGTH:
        raise DomainError(f"{field} must be at most {_NOTES_MAX_LENGTH} characters: {len(notes)}")


def _validate_date_of_birth(date_of_birth: date | None, *, today: date) -> None:
    """A date of birth must be a real past date — never in the future, and not implausibly
    distant (a school bus rider is a minor; 100 years bounds a fat-fingered year without
    inventing a narrower, more presumptuous age policy no approved document specifies)."""
    if date_of_birth is None:
        return
    if date_of_birth > today:
        raise DomainError(f"Student date_of_birth must not be in the future: {date_of_birth}")
    if (today.year - date_of_birth.year) > 100:
        raise DomainError(f"Student date_of_birth is implausibly distant: {date_of_birth}")


def _validate_address(address: str | None) -> None:
    if address is not None and len(address) > _ADDRESS_MAX_LENGTH:
        raise DomainError(
            f"Parent address must be at most {_ADDRESS_MAX_LENGTH} characters: {len(address)}"
        )


def _validate_emergency_contact_name(name: str | None) -> None:
    if name is not None and len(name) > _EMERGENCY_CONTACT_NAME_MAX_LENGTH:
        raise DomainError(
            "Parent emergency_contact_name must be at most "
            f"{_EMERGENCY_CONTACT_NAME_MAX_LENGTH} characters: {len(name)}"
        )


# Phase 10.6: `Parent`'s own full_name length guard — same VARCHAR(200) convention as
# `_FULL_NAME_MAX_LENGTH` above (both columns share the name/convention, see
# `value_objects.py`'s module docstring), kept as a separate constant/function rather than
# reused directly so a future change to one aggregate's column length can't silently affect
# the other's.
_PARENT_FULL_NAME_MAX_LENGTH = 200


def _validate_parent_full_name(full_name: str) -> None:
    if not full_name:
        raise DomainError("Parent full_name must not be empty")
    if len(full_name) > _PARENT_FULL_NAME_MAX_LENGTH:
        raise DomainError(
            f"Parent full_name must be at most {_PARENT_FULL_NAME_MAX_LENGTH} "
            f"characters: {len(full_name)}"
        )


# Phase 10.7: Database Design §6.4: `student_parents.relationship VARCHAR(40)`.
_RELATIONSHIP_MAX_LENGTH = 40


def _validate_relationship_label(relationship: str | None) -> None:
    if relationship is not None and len(relationship) > _RELATIONSHIP_MAX_LENGTH:
        raise DomainError(
            f"relationship label must be at most {_RELATIONSHIP_MAX_LENGTH} "
            f"characters: {len(relationship)}"
        )


# Phase 10.8: Database Design §6.1 gives no explicit VARCHAR length for `drivers.license_no`
# (compact notation, no fully-spelled-out table unlike §6.2's `students`) - mirrors
# `_EXTERNAL_REF_MAX_LENGTH` above's VARCHAR(64) precedent for an unformatted identifier string
# with no documented length of its own, rather than inventing an unrelated number.
_LICENSE_NO_MAX_LENGTH = 64


def _validate_license_no(license_no: str) -> None:
    if not license_no:
        raise DomainError("Driver license_no must not be empty")
    if len(license_no) > _LICENSE_NO_MAX_LENGTH:
        raise DomainError(
            f"Driver license_no must be at most {_LICENSE_NO_MAX_LENGTH} characters: "
            f"{len(license_no)}"
        )


# Phase 11: Database Design §6.5 gives no explicit VARCHAR length for `routes.name` (compact
# notation, same situation as `parents`/`drivers` above) - mirrors the sibling `stops.name
# VARCHAR(160)` length (§6.6, the same document section) rather than an unrelated cross-module
# borrow, since both are short human-readable labels defined side by side in the same table
# group.
_ROUTE_NAME_MAX_LENGTH = 160
_STOP_NAME_MAX_LENGTH = 160  # Database Design §6.6: name VARCHAR(160)
_MIN_LATITUDE = -90.0
_MAX_LATITUDE = 90.0
_MIN_LONGITUDE = -180.0
_MAX_LONGITUDE = 180.0


def _validate_route_name(name: str) -> None:
    if not name:
        raise DomainError("Route name must not be empty")
    if len(name) > _ROUTE_NAME_MAX_LENGTH:
        raise DomainError(
            f"Route name must be at most {_ROUTE_NAME_MAX_LENGTH} characters: {len(name)}"
        )


def _validate_stop_name(name: str) -> None:
    if not name:
        raise DomainError("Stop name must not be empty")
    if len(name) > _STOP_NAME_MAX_LENGTH:
        raise DomainError(
            f"Stop name must be at most {_STOP_NAME_MAX_LENGTH} characters: {len(name)}"
        )


def _validate_latitude(latitude: float) -> None:
    if not (_MIN_LATITUDE <= latitude <= _MAX_LATITUDE):
        raise DomainError(
            f"Stop latitude must be between {_MIN_LATITUDE} and {_MAX_LATITUDE}: {latitude}"
        )


def _validate_longitude(longitude: float) -> None:
    if not (_MIN_LONGITUDE <= longitude <= _MAX_LONGITUDE):
        raise DomainError(
            f"Stop longitude must be between {_MIN_LONGITUDE} and {_MAX_LONGITUDE}: "
            f"{longitude}"
        )


def _validate_sequence_no(sequence_no: int) -> None:
    if sequence_no < 1:
        raise DomainError(
            f"Stop sequence_no must be a positive integer (>= 1): {sequence_no}"
        )


# Phase 12: no `trips.interrupt_reason` column exists (Database Design §6.8) to borrow a
# documented length from - `reason` is only ever carried in the `TripInterrupted` event
# payload (`entities.py`'s module docstring). 500 is a generous, defensible free-text bound
# for a short diagnostic note, not a guessed DB constraint.
_INTERRUPT_REASON_MAX_LENGTH = 500


def _validate_interrupt_reason(reason: str) -> None:
    if not reason:
        raise DomainError("Trip interrupt reason must not be empty")
    if len(reason) > _INTERRUPT_REASON_MAX_LENGTH:
        raise DomainError(
            f"Trip interrupt reason must be at most {_INTERRUPT_REASON_MAX_LENGTH} "
            f"characters: {len(reason)}"
        )


class _AggregateRoot:
    """Shared "raise and buffer domain events" mechanics (LLD §8.1), identical to
    `organization.domain.entities._AggregateRoot`. Duplicated per module deliberately —
    `.claude/rules/backend.md` #1 forbids one module reaching into another's internals, and no
    approved doc calls for a shared-kernel package."""

    def __init__(self) -> None:
        self._domain_events: list[DomainEvent] = []

    def _record(self, event: DomainEvent) -> None:
        self._domain_events.append(event)

    def pull_domain_events(self) -> list[DomainEvent]:
        events = self._domain_events
        self._domain_events = []
        return events


class Student(_AggregateRoot):
    """A student enrolled with an organization (Database Design §6.2). Tenant-owned — every
    instance carries `organization_id` (`.claude/rules/database.md` #2)."""

    def __init__(
        self,
        *,
        id: StudentId,
        organization_id: OrganizationId,
        full_name: str,
        external_ref: str | None,
        status: StudentStatus,
        created_at: datetime,
        updated_at: datetime,
        date_of_birth: date | None = None,
        gender: Gender | None = None,
        notes: str | None = None,
    ) -> None:
        super().__init__()
        _validate_full_name(full_name)
        _validate_external_ref(external_ref)
        _validate_notes(notes)
        self.id = id
        self.organization_id = organization_id
        self.full_name = full_name
        self.external_ref = external_ref
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
        # 2026-09-10 explicit user directive: additive transport-facing profile fields, not in
        # Database Design §6.2 — see `value_objects.py`'s module comment for the "why now" note.
        self.date_of_birth = date_of_birth
        self.gender = gender
        self.notes = notes

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Student) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def enroll(
        cls,
        *,
        id: StudentId,
        organization_id: OrganizationId,
        full_name: str,
        external_ref: str | None = None,
        date_of_birth: date | None = None,
        gender: Gender | None = None,
        notes: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Student":
        """Factory for a newly-enrolled student. No `pending`/`invited` status exists in the
        approved enum (Database Design §6.2: `active,disabled,graduated,transferred` only), so
        an enrolled student starts `active` — the same reasoning `organization.domain.entities.
        Organization.register` gives for its own status enum."""
        now = clock.now()
        _validate_date_of_birth(date_of_birth, today=now.date())
        student = cls(
            id=id,
            organization_id=organization_id,
            full_name=full_name,
            external_ref=external_ref,
            status=StudentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            date_of_birth=date_of_birth,
            gender=gender,
            notes=notes,
        )
        student._record(
            transport_ops_events.student_enrolled(
                student_id=str(id),
                organization_id=str(organization_id),
                full_name=full_name,
                external_ref=external_ref,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return student

    def activate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == StudentStatus.ACTIVE:
            return
        self.status = StudentStatus.ACTIVE
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.student_activated(
                student_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def disable(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == StudentStatus.DISABLED:
            return
        self.status = StudentStatus.DISABLED
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.student_disabled(
                student_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def graduate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == StudentStatus.GRADUATED:
            return
        self.status = StudentStatus.GRADUATED
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.student_graduated(
                student_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def transfer(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == StudentStatus.TRANSFERRED:
            return
        self.status = StudentStatus.TRANSFERRED
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.student_transferred(
                student_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def update_details(
        self,
        *,
        full_name: str,
        external_ref: str | None,
        date_of_birth: date | None = None,
        gender: Gender | None = None,
        notes: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Phase 10.2 addition, extended 2026-09-10 to also cover the additive profile fields
        (`date_of_birth`/`gender`/`notes`) in the same single edit surface, rather than a second
        setter — one "edit this student's profile" use case, matching how the task's own "Edit
        Student" requirement was framed. Idempotent: a call that changes nothing is a no-op, the
        same "no event for no real change" precedent every status-change method above follows."""
        _validate_full_name(full_name)
        _validate_external_ref(external_ref)
        _validate_notes(notes)
        _validate_date_of_birth(date_of_birth, today=clock.now().date())
        if (
            full_name == self.full_name
            and external_ref == self.external_ref
            and date_of_birth == self.date_of_birth
            and gender == self.gender
            and notes == self.notes
        ):
            return
        self.full_name = full_name
        self.external_ref = external_ref
        self.date_of_birth = date_of_birth
        self.gender = gender
        self.notes = notes
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.student_details_updated(
                student_id=str(self.id),
                organization_id=str(self.organization_id),
                full_name=full_name,
                external_ref=external_ref,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class Parent(_AggregateRoot):
    """A parent/guardian's transport-facing profile, linked to an `iam.User` login (Database
    Design §6.3). Tenant-owned — every instance carries `organization_id`
    (`.claude/rules/database.md` #2). `user_id` is a cross-module reference only (see
    `value_objects.py`'s `UserId` docstring) — this aggregate never loads or mutates the
    linked `User`, only stores its id.

    Phase 10.6 scope: the `Parent` aggregate only — no `student_parents` linking, no guardian
    relationships beyond this aggregate, matching this phase's own explicit exclusions.
    """

    def __init__(
        self,
        *,
        id: ParentId,
        organization_id: OrganizationId,
        user_id: UserId,
        full_name: str,
        phone: PhoneNumber | None,
        status: ParentStatus,
        created_at: datetime,
        updated_at: datetime,
        has_video_live_access: bool = False,
        has_video_playback_access: bool = False,
        alternate_phone: PhoneNumber | None = None,
        address: str | None = None,
        emergency_contact_name: str | None = None,
        emergency_contact_phone: PhoneNumber | None = None,
        notes: str | None = None,
    ) -> None:
        super().__init__()
        _validate_parent_full_name(full_name)
        _validate_address(address)
        _validate_emergency_contact_name(emergency_contact_name)
        _validate_notes(notes)
        self.id = id
        self.organization_id = organization_id
        self.user_id = user_id
        self.full_name = full_name
        self.phone = phone
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
        # ADR-0026: off by default for every parent, always - never inferred, never inherited
        # from a role or another parent. Only `grant_video_live_access`/`grant_video_playback_
        # access` (org_admin-only, `interfaces/http/policy_guards`) ever flip either to `True`.
        self.has_video_live_access = has_video_live_access
        self.has_video_playback_access = has_video_playback_access
        # 2026-09-10 explicit user directive: additive family/contact profile fields, not in
        # Database Design §6.3 — see `value_objects.py`'s module comment for the "why now" note.
        self.alternate_phone = alternate_phone
        self.address = address
        self.emergency_contact_name = emergency_contact_name
        self.emergency_contact_phone = emergency_contact_phone
        self.notes = notes

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Parent) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def register(
        cls,
        *,
        id: ParentId,
        organization_id: OrganizationId,
        user_id: UserId,
        full_name: str,
        phone: PhoneNumber | None = None,
        alternate_phone: PhoneNumber | None = None,
        address: str | None = None,
        emergency_contact_name: str | None = None,
        emergency_contact_phone: PhoneNumber | None = None,
        notes: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Parent":
        """Factory for a newly-registered parent profile. No `pending`/`invited` status exists
        in the (undocumented-values) status enum — see `value_objects.py`'s `ParentStatus`
        docstring — so a registered parent starts `active`, the same reasoning
        `Student.enroll`/`Organization.register` give for their own status enums."""
        now = clock.now()
        parent = cls(
            id=id,
            organization_id=organization_id,
            user_id=user_id,
            full_name=full_name,
            phone=phone,
            status=ParentStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            alternate_phone=alternate_phone,
            address=address,
            emergency_contact_name=emergency_contact_name,
            emergency_contact_phone=emergency_contact_phone,
            notes=notes,
        )
        parent._record(
            transport_ops_events.parent_registered(
                parent_id=str(id),
                organization_id=str(organization_id),
                user_id=str(user_id),
                full_name=full_name,
                phone=str(phone) if phone is not None else None,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return parent

    def update_details(
        self,
        *,
        full_name: str,
        phone: PhoneNumber | None,
        alternate_phone: PhoneNumber | None = None,
        address: str | None = None,
        emergency_contact_name: str | None = None,
        emergency_contact_phone: PhoneNumber | None = None,
        notes: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Extended 2026-09-10 to cover the additive contact/family profile fields in the same
        single edit surface, mirroring `Student.update_details`'s identical extension and
        reasoning. Idempotent: a call that changes nothing is a no-op, the same "no event for no
        real change" precedent `Student.update_details` already establishes."""
        _validate_parent_full_name(full_name)
        _validate_address(address)
        _validate_emergency_contact_name(emergency_contact_name)
        _validate_notes(notes)
        if (
            full_name == self.full_name
            and phone == self.phone
            and alternate_phone == self.alternate_phone
            and address == self.address
            and emergency_contact_name == self.emergency_contact_name
            and emergency_contact_phone == self.emergency_contact_phone
            and notes == self.notes
        ):
            return
        self.full_name = full_name
        self.phone = phone
        self.alternate_phone = alternate_phone
        self.address = address
        self.emergency_contact_name = emergency_contact_name
        self.emergency_contact_phone = emergency_contact_phone
        self.notes = notes
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.parent_details_updated(
                parent_id=str(self.id),
                organization_id=str(self.organization_id),
                full_name=full_name,
                phone=str(phone) if phone is not None else None,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def activate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == ParentStatus.ACTIVE:
            return
        self.status = ParentStatus.ACTIVE
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.parent_activated(
                parent_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def disable(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == ParentStatus.INACTIVE:
            return
        self.status = ParentStatus.INACTIVE
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.parent_disabled(
                parent_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def grant_video_live_access(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """ADR-0026 §2: org_admin-only (enforced at the API layer, not here — this aggregate has
        no reachable way to know the caller's role, mirroring `VideoSession`'s identical
        posture). Idempotent same-state no-op, mirrors `activate`/`disable`."""
        if self.has_video_live_access:
            return
        self.has_video_live_access = True
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.parent_video_live_access_granted(
                parent_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def revoke_video_live_access(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if not self.has_video_live_access:
            return
        self.has_video_live_access = False
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.parent_video_live_access_revoked(
                parent_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def grant_video_playback_access(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.has_video_playback_access:
            return
        self.has_video_playback_access = True
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.parent_video_playback_access_granted(
                parent_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def revoke_video_playback_access(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if not self.has_video_playback_access:
            return
        self.has_video_playback_access = False
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.parent_video_playback_access_revoked(
                parent_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class StudentParent(_AggregateRoot):
    """One row of `student_parents` (Database Design §6.4): an M:N association between a
    `Student` and a `Parent`. Composite-keyed by `(student_id, parent_id)` — see module
    docstring's Phase 10.7 addendum for why this aggregate has no surrogate `id` and no audit
    columns, unlike `Student`/`Parent` above.

    The relationship's lifecycle is binary — linked or not — so creating this aggregate *is*
    the "link" event; there is no persisted status field. Unlinking removes the row entirely (a
    hard delete, `infra/repositories.py`), not a soft-delete/status transition. `relationship`/
    `is_primary` are set only at link time (Application section of this phase's task lists
    Link/Unlink/List — no update use-case), so no `update_*` method exists here; changing either
    field requires unlinking and re-linking.
    """

    def __init__(
        self,
        *,
        student_id: StudentId,
        parent_id: ParentId,
        relationship: str | None,
        is_primary: bool,
    ) -> None:
        super().__init__()
        _validate_relationship_label(relationship)
        self.student_id = student_id
        self.parent_id = parent_id
        self.relationship = relationship
        self.is_primary = is_primary

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, StudentParent)
            and self.student_id == other.student_id
            and self.parent_id == other.parent_id
        )

    def __hash__(self) -> int:
        return hash((self.student_id, self.parent_id))

    @classmethod
    def link(
        cls,
        *,
        student_id: StudentId,
        student_organization_id: OrganizationId,
        parent_id: ParentId,
        parent_organization_id: OrganizationId,
        relationship: str | None = None,
        is_primary: bool = False,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "StudentParent":
        """Factory for a new link. **Cross-organization associations are rejected here**
        (this phase's own scope: "Prevent: Cross-organization associations") by comparing the
        already-loaded `Student`'s and `Parent`'s `organization_id`s — a pure invariant, no I/O
        needed, so it lives in the domain layer. This is a deliberately different placement
        from the duplicate-link and existence checks (`application/validators.py`), which do
        need a repository read and therefore belong in the application layer instead — the same
        domain-vs-application split `fleet_device`'s intra-aggregate camera-channel-uniqueness
        (domain, no I/O, `ConflictError`) vs. its `ensure_vehicle_exists` (application, I/O)
        already establishes in this codebase."""
        if student_organization_id != parent_organization_id:
            raise DomainError(
                f"Cannot link Student {student_id} (organization "
                f"{student_organization_id}) to Parent {parent_id} (organization "
                f"{parent_organization_id}): cross-organization parent-student links are "
                "not permitted."
            )
        link = cls(
            student_id=student_id,
            parent_id=parent_id,
            relationship=relationship,
            is_primary=is_primary,
        )
        link._record(
            transport_ops_events.student_parent_linked(
                student_id=str(student_id),
                parent_id=str(parent_id),
                organization_id=str(student_organization_id),
                relationship=relationship,
                is_primary=is_primary,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return link

    def unlink(
        self,
        *,
        organization_id: OrganizationId,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Emits `StudentParentUnlinked` before the application layer removes the row
        (`application/services.py`'s `StudentParentApplicationService.unlink_parent_from_student`)
        — the aggregate still owns emitting its own domain event even though the persistence
        action that follows is a delete, the same "aggregate records, application persists"
        separation every other method in this module follows. `organization_id` is supplied by
        the caller (from the already-loaded `Student`/`Parent`) since it isn't a field on this
        aggregate — `student_parents` has no `organization_id` column (§6.4)."""
        self._record(
            transport_ops_events.student_parent_unlinked(
                student_id=str(self.student_id),
                parent_id=str(self.parent_id),
                organization_id=str(organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class Driver(_AggregateRoot):
    """A vehicle operator's transport-facing profile, linked to an `iam.User` login with
    `role=driver` (Database Design §6.1, ADR-0001). Tenant-owned — every instance carries
    `organization_id` (`.claude/rules/database.md` #2). `user_id` is a cross-module reference
    only (see `value_objects.py`'s `UserId` docstring) — this aggregate never loads or mutates
    the linked `User`, only stores its id, mirroring `Parent`'s identical treatment exactly.

    Phase 10.8 scope: the `Driver` aggregate only — no vehicle/trip assignment, no
    authentication, no scheduling (all out of scope per this phase's own instructions).
    Vehicle↔driver binding is per-trip (`trips.driver_id`, Database Design §6.1's own closing
    line), a separate, out-of-scope `Trip` aggregate — so `Driver` holds no `vehicle_id`/
    `trip_id`/`route_id` field, the same reasoning `Student`'s module docstring gives for its
    own absent cross-aggregate fields.
    """

    def __init__(
        self,
        *,
        id: DriverId,
        organization_id: OrganizationId,
        user_id: UserId,
        license_no: str,
        status: DriverStatus,
        created_at: datetime,
        updated_at: datetime,
        staff_id: TransportStaffId,
    ) -> None:
        super().__init__()
        _validate_license_no(license_no)
        self.id = id
        self.organization_id = organization_id
        self.user_id = user_id
        #: ADR-0049: the `TransportStaff` person this driver profile belongs to. The person's
        #: name and contact live there; this aggregate keeps only what driving needs.
        self.staff_id = staff_id
        self.license_no = license_no
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Driver) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def register(
        cls,
        *,
        id: DriverId,
        organization_id: OrganizationId,
        user_id: UserId,
        license_no: str,
        staff_id: TransportStaffId,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Driver":
        """Factory for a newly-registered driver profile. No `pending`/`invited` status exists
        in the (undocumented-values) status enum — see `value_objects.py`'s `DriverStatus`
        docstring — so a registered driver starts `active`, the same reasoning `Parent.register`
        gives for its own status enum."""
        now = clock.now()
        driver = cls(
            id=id,
            organization_id=organization_id,
            user_id=user_id,
            license_no=license_no,
            status=DriverStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            staff_id=staff_id,
        )
        driver._record(
            transport_ops_events.driver_registered(
                driver_id=str(id),
                organization_id=str(organization_id),
                user_id=str(user_id),
                staff_id=str(staff_id),
                license_no=license_no,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return driver

    def update_details(
        self,
        *,
        license_no: str,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Idempotent: a call that changes nothing is a no-op, the same "no event for no real
        change" precedent `Parent.update_details` already establishes."""
        _validate_license_no(license_no)
        if license_no == self.license_no:
            return
        self.license_no = license_no
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.driver_details_updated(
                driver_id=str(self.id),
                organization_id=str(self.organization_id),
                license_no=license_no,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def activate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == DriverStatus.ACTIVE:
            return
        self.status = DriverStatus.ACTIVE
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.driver_activated(
                driver_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def disable(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == DriverStatus.INACTIVE:
            return
        self.status = DriverStatus.INACTIVE
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.driver_disabled(
                driver_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class Stop:
    """Child entity of the `Route` aggregate (Database Design §6.6) — identity + fields only,
    no base class and no domain-event buffer of its own; all mutation goes through `Route`'s
    own methods, the aggregate root (`fleet_device.domain.entities.Camera`'s identical
    precedent for `Device` — same plain-class shape, not extending `_AggregateRoot`). `Route`
    is the one that records `RouteStop*` events, exactly how `Device.register_camera` records
    `CameraRegistered` rather than `Camera` recording it itself.
    """

    def __init__(
        self,
        *,
        id: StopId,
        name: str,
        latitude: float,
        longitude: float,
        sequence_no: int,
        geofence_radius_m: int | None,
    ) -> None:
        _validate_stop_name(name)
        _validate_latitude(latitude)
        _validate_longitude(longitude)
        _validate_sequence_no(sequence_no)
        self.id = id
        self.name = name
        self.latitude = latitude
        self.longitude = longitude
        self.sequence_no = sequence_no
        self.geofence_radius_m = geofence_radius_m

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Stop) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class Route(_AggregateRoot):
    """A transportation path followed by a vehicle (Database Design §6.5), owning its `Stop`
    children (§6.6). Tenant-owned — every instance carries `organization_id`
    (`.claude/rules/database.md` #2). Per-tenant name uniqueness (`Unique
    (organization_id, name)`, §6.5) needs a repository read, so it is an application-layer
    pre-check (`application/validators.py`'s `ensure_route_name_available`), not enforced here
    — the same domain-vs-application split `fleet_device`'s plate/terminal-id uniqueness
    checks already establish.

    Phase 11 scope: `Route`/`Stop` only. Trip execution, driver/vehicle assignment to trips,
    GPS tracking, geofencing execution, ETA calculation, parent notifications, and
    boarding/alighting are all explicitly out of scope for this phase (they belong to the
    `Trip`/`Tracking` phases) — `Route` therefore holds no `trip_id`/`vehicle_id`/`driver_id`
    field, the same reasoning `Student`'s module docstring gives for its own absent
    cross-aggregate fields.
    """

    def __init__(
        self,
        *,
        id: RouteId,
        organization_id: OrganizationId,
        name: str,
        status: RouteStatus,
        created_at: datetime,
        updated_at: datetime,
        stops: list[Stop] | None = None,
    ) -> None:
        super().__init__()
        _validate_route_name(name)
        self.id = id
        self.organization_id = organization_id
        self.name = name
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
        self._stops: list[Stop] = list(stops) if stops else []

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Route) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def stops(self) -> tuple[Stop, ...]:
        """Read-only view, always returned **ordered by `sequence_no`** ("ordered stops",
        API Contracts §4.3) regardless of construction/insertion order — mutation only via
        `add_stop`/`remove_stop`/`move_stop` (aggregate-root rule)."""
        return tuple(sorted(self._stops, key=lambda stop: stop.sequence_no))

    @classmethod
    def create(
        cls,
        *,
        id: RouteId,
        organization_id: OrganizationId,
        name: str,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Route":
        """Factory for a newly-created route. No `pending`/`draft` status exists in the
        documented 2-value enum (Database Design §6.5), so a created route starts `active` —
        the same reasoning `Parent.register`/`Driver.register` give for their own status
        enums."""
        now = clock.now()
        route = cls(
            id=id,
            organization_id=organization_id,
            name=name,
            status=RouteStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        route._record(
            transport_ops_events.route_created(
                route_id=str(id),
                organization_id=str(organization_id),
                name=name,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return route

    def update_details(
        self, *, name: str, clock: Clock, actor_id: str | None = None
    ) -> None:
        """Idempotent: a call that changes nothing is a no-op, the same "no event for no real
        change" precedent `Parent.update_details`/`Driver.update_details` already establish.
        """
        _validate_route_name(name)
        if name == self.name:
            return
        self.name = name
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.route_details_updated(
                route_id=str(self.id),
                organization_id=str(self.organization_id),
                name=name,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def activate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == RouteStatus.ACTIVE:
            return
        self.status = RouteStatus.ACTIVE
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.route_activated(
                route_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def disable(self, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.status == RouteStatus.INACTIVE:
            return
        self.status = RouteStatus.INACTIVE
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.route_disabled(
                route_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def _ensure_sequence_available(
        self, sequence_no: int, *, excluding_stop_id: StopId | None = None
    ) -> None:
        """`ux_stops__route_sequence` (Database Design §6.6) — an intra-aggregate uniqueness
        invariant, enforced here without I/O, the same placement `Device.register_camera`
        gives `ux_cameras__device_channel`."""
        for stop in self._stops:
            if excluding_stop_id is not None and stop.id == excluding_stop_id:
                continue
            if stop.sequence_no == sequence_no:
                raise ConflictError(
                    f"Route {self.id} already has a stop at sequence_no {sequence_no}."
                )

    def add_stop(
        self,
        *,
        id: StopId,
        name: str,
        latitude: float,
        longitude: float,
        sequence_no: int,
        geofence_radius_m: int | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> Stop:
        """Adds a stop at a free sequence position (see module docstring's Stop validation
        scope note for the exact invariants enforced)."""
        self._ensure_sequence_available(sequence_no)
        stop = Stop(
            id=id,
            name=name,
            latitude=latitude,
            longitude=longitude,
            sequence_no=sequence_no,
            geofence_radius_m=geofence_radius_m,
        )
        self._stops.append(stop)
        self._record(
            transport_ops_events.route_stop_added(
                route_id=str(self.id),
                organization_id=str(self.organization_id),
                stop_id=str(id),
                name=name,
                latitude=latitude,
                longitude=longitude,
                sequence_no=sequence_no,
                geofence_radius_m=geofence_radius_m,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return stop

    def remove_stop(
        self, stop_id: StopId, *, clock: Clock, actor_id: str | None = None
    ) -> None:
        """Removes a stop from the route. A pure in-memory operation over already-loaded child
        entities (no I/O), so a missing `stop_id` is a `DomainError` — the same "domain raises
        for invariant/precondition violations over loaded state" convention every other method
        in this module follows, distinct from the application layer's `NotFoundError` for a
        missing *aggregate root* (`application/services.py`'s `_get_route_or_raise`)."""
        match = next((stop for stop in self._stops if stop.id == stop_id), None)
        if match is None:
            raise DomainError(f"Route {self.id} has no stop {stop_id}.")
        self._stops.remove(match)
        self._record(
            transport_ops_events.route_stop_removed(
                route_id=str(self.id),
                organization_id=str(self.organization_id),
                stop_id=str(stop_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def move_stop(
        self,
        stop_id: StopId,
        *,
        new_sequence_no: int,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Reorders one existing stop to `new_sequence_no`. Idempotent: moving a stop to its
        own current position is a no-op, the same "no event for no real change" precedent
        every status-change method in this module follows."""
        match = next((stop for stop in self._stops if stop.id == stop_id), None)
        if match is None:
            raise DomainError(f"Route {self.id} has no stop {stop_id}.")
        _validate_sequence_no(new_sequence_no)
        if match.sequence_no == new_sequence_no:
            return
        self._ensure_sequence_available(new_sequence_no, excluding_stop_id=stop_id)
        match.sequence_no = new_sequence_no
        self._record(
            transport_ops_events.route_stop_reordered(
                route_id=str(self.id),
                organization_id=str(self.organization_id),
                stop_id=str(stop_id),
                new_sequence_no=new_sequence_no,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class Trip(_AggregateRoot):
    """The operational aggregate root for a day's journey (Database Design §6.8, Phase-2 §6.2).
    Tenant-owned — every instance carries `organization_id` (`.claude/rules/database.md` #2).
    `vehicle_id` is a cross-module reference (never existence-checked, see `value_objects.py`'s
    Phase 12 addition); `driver_id`/`route_id` are same-module references, existence-checked at
    the application layer before this aggregate is constructed.

    Phase 12 scope: `Trip` only — no `trip_students` roster, no GPS/geofence execution, no
    notifications (all out of scope per this phase's own instructions; see module docstring's
    Phase 12 addition for the full reasoning).
    """

    def __init__(
        self,
        *,
        id: TripId,
        organization_id: OrganizationId,
        vehicle_id: VehicleId,
        driver_id: DriverId,
        route_id: RouteId,
        trip_type: TripType,
        status: TripStatus,
        scheduled_date: date,
        started_at: datetime | None,
        ended_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
        timetable_entry_id: RouteTimetableEntryId | None = None,
        planned_departure: time | None = None,
        cancelled_at: datetime | None = None,
        cancelled_reason: str | None = None,
        coverage_alert_key: str | None = None,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.vehicle_id = vehicle_id
        self.driver_id = driver_id
        self.route_id = route_id
        self.trip_type = trip_type
        self.status = status
        self.scheduled_date = scheduled_date
        self.started_at = started_at
        self.ended_at = ended_at
        self.created_at = created_at
        self.updated_at = updated_at
        #: ADR-0052: the timetable entry this trip was generated from, if any.
        self.timetable_entry_id = timetable_entry_id
        self.planned_departure = planned_departure
        #: ADR-0054.
        self.cancelled_at = cancelled_at
        self.cancelled_reason = cancelled_reason
        #: ADR-0053 §5: the last uncovered cause alerted, so a cause is announced once.
        self.coverage_alert_key = coverage_alert_key

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Trip) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def schedule(
        cls,
        *,
        id: TripId,
        organization_id: OrganizationId,
        vehicle_id: VehicleId,
        driver_id: DriverId,
        driver_organization_id: OrganizationId,
        route_id: RouteId,
        route_organization_id: OrganizationId,
        trip_type: TripType,
        scheduled_date: date,
        clock: Clock,
        actor_id: str | None = None,
        timetable_entry_id: RouteTimetableEntryId | None = None,
        planned_departure: time | None = None,
    ) -> "Trip":
        """Factory for a newly-scheduled trip. Starts `SCHEDULED` — the sole entry point of
        the documented state diagram (Phase-2 §6.2: `[*] --> Scheduled`). Rejects
        cross-organization `driver`/`route` (`DomainError`) by comparing the already-loaded
        `Driver`/`Parent`'s own `organization_id` against this trip's — the identical pure,
        no-I/O placement `StudentParent.link`'s cross-organization check already establishes
        (the application layer loads both aggregates first, `application/services.py`).
        `vehicle_id`'s organization is **not** cross-checked — see this class's own docstring
        and `value_objects.py`'s Phase 12 addition for why."""
        if driver_organization_id != organization_id:
            raise DomainError(
                f"Cannot schedule a Trip for organization {organization_id} with Driver "
                f"{driver_id} (organization {driver_organization_id}): cross-organization "
                "trip assignments are not permitted."
            )
        if route_organization_id != organization_id:
            raise DomainError(
                f"Cannot schedule a Trip for organization {organization_id} with Route "
                f"{route_id} (organization {route_organization_id}): cross-organization "
                "trip assignments are not permitted."
            )
        now = clock.now()
        trip = cls(
            id=id,
            organization_id=organization_id,
            vehicle_id=vehicle_id,
            driver_id=driver_id,
            route_id=route_id,
            trip_type=trip_type,
            status=TripStatus.SCHEDULED,
            scheduled_date=scheduled_date,
            started_at=None,
            ended_at=None,
            created_at=now,
            updated_at=now,
            timetable_entry_id=timetable_entry_id,
            planned_departure=planned_departure,
        )
        trip._record(
            transport_ops_events.trip_scheduled(
                trip_id=str(id),
                organization_id=str(organization_id),
                vehicle_id=str(vehicle_id),
                driver_id=str(driver_id),
                route_id=str(route_id),
                trip_type=trip_type.value,
                scheduled_date=scheduled_date.isoformat(),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )
        return trip

    def cancel(self, *, reason: str, clock: Clock, actor_id: str | None = None) -> None:
        """ADR-0054: `Scheduled -> Cancelled`, final. A trip that has started is ended or
        interrupted instead; anything else is an illegal transition (409)."""
        reason = _require_text(reason, field="Cancellation reason", max_length=_CANCEL_REASON_MAX_LENGTH)
        if self.status is not TripStatus.SCHEDULED:
            raise RuleViolationError(
                f"Trip {self.id} cannot be cancelled from status {self.status.value!r}: only a "
                "scheduled trip can be cancelled."
            )
        now = clock.now()
        self.status = TripStatus.CANCELLED
        self.cancelled_at = now
        self.cancelled_reason = reason
        self.updated_at = now
        self._record(
            transport_ops_events.trip_cancelled(
                trip_id=str(self.id),
                organization_id=str(self.organization_id),
                vehicle_id=str(self.vehicle_id),
                route_id=str(self.route_id),
                trip_type=self.trip_type.value,
                scheduled_date=self.scheduled_date.isoformat(),
                reason=reason,
                occurred_at=now,
                actor_id=actor_id,
            )
        )

    def mark_coverage_alerted(self, key: str | None) -> None:
        """ADR-0053 §5 bookkeeping only: which uncovered cause was last announced."""
        self.coverage_alert_key = key

    def start(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`Scheduled -> InProgress` (Phase-2 §6.2: "Driver starts trip"). Any other current
        status is an illegal transition (`RuleViolationError` — API Contracts §5.2's own
        example: "start an already-in-progress trip" -> `409 RULE_VIOLATION`), unlike every
        other status-change method in this module, which treat their own undocumented
        transitions as idempotent no-ops (see module docstring's Phase 12 addition)."""
        if self.status != TripStatus.SCHEDULED:
            raise RuleViolationError(
                f"Trip {self.id} cannot start from status {self.status.value!r} "
                "(only SCHEDULED -> IN_PROGRESS is legal, Phase-2 §6.2)."
            )
        self.status = TripStatus.IN_PROGRESS
        self.started_at = clock.now()
        self.updated_at = self.started_at
        self._record(
            transport_ops_events.trip_started(
                trip_id=str(self.id),
                organization_id=str(self.organization_id),
                vehicle_id=str(self.vehicle_id),
                driver_id=str(self.driver_id),
                route_id=str(self.route_id),
                started_at=self.started_at,
                actor_id=actor_id,
            )
        )

    def end(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`InProgress -> Completed` or `Interrupted -> Completed` ("force end", Phase-2 §6.2)
        — the diagram's only two edges into the terminal state. Any other current status is an
        illegal transition (`RuleViolationError`)."""
        if self.status not in (TripStatus.IN_PROGRESS, TripStatus.INTERRUPTED):
            raise RuleViolationError(
                f"Trip {self.id} cannot end from status {self.status.value!r} (only "
                "IN_PROGRESS -> COMPLETED or INTERRUPTED -> COMPLETED are legal, Phase-2 "
                "§6.2)."
            )
        self.status = TripStatus.COMPLETED
        self.ended_at = clock.now()
        self.updated_at = self.ended_at
        self._record(
            transport_ops_events.trip_ended(
                trip_id=str(self.id),
                organization_id=str(self.organization_id),
                vehicle_id=str(self.vehicle_id),
                driver_id=str(self.driver_id),
                route_id=str(self.route_id),
                ended_at=self.ended_at,
                actor_id=actor_id,
            )
        )

    def interrupt(
        self, reason: str, *, clock: Clock, actor_id: str | None = None
    ) -> None:
        """`InProgress -> Interrupted` (Phase-2 §6.2: "timeout / device offline / manual").
        Legal only from `IN_PROGRESS`; else `RuleViolationError`. No approved HTTP route
        exists this phase (`api/routers.py`'s module docstring) — reachable at the application
        layer only, mirroring `Route.remove_stop`/`move_stop`'s identical posture. `reason` is
        never persisted on this row (no such column, Database Design §6.8) — it travels only
        in the `TripInterrupted` event payload."""
        if self.status != TripStatus.IN_PROGRESS:
            raise RuleViolationError(
                f"Trip {self.id} cannot be interrupted from status {self.status.value!r} "
                "(only IN_PROGRESS -> INTERRUPTED is legal, Phase-2 §6.2)."
            )
        _validate_interrupt_reason(reason)
        self.status = TripStatus.INTERRUPTED
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.trip_interrupted(
                trip_id=str(self.id),
                organization_id=str(self.organization_id),
                vehicle_id=str(self.vehicle_id),
                reason=reason,
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def resume(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`Interrupted -> InProgress` (Phase-2 §6.2: "resume"). Legal only from `INTERRUPTED`;
        else `RuleViolationError`. No approved HTTP route exists this phase — same posture as
        `interrupt` above. `TripResumed` is this phase's own PascalCase-past-tense naming
        choice — no approved document names this event, flagged in `domain/events.py`."""
        if self.status != TripStatus.INTERRUPTED:
            raise RuleViolationError(
                f"Trip {self.id} cannot resume from status {self.status.value!r} (only "
                "INTERRUPTED -> IN_PROGRESS is legal, Phase-2 §6.2)."
            )
        self.status = TripStatus.IN_PROGRESS
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.trip_resumed(
                trip_id=str(self.id),
                organization_id=str(self.organization_id),
                vehicle_id=str(self.vehicle_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def change_driver(
        self,
        new_driver_id: DriverId,
        *,
        new_driver_organization_id: OrganizationId,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Backs `PATCH /trips/{id}/driver` ("change driver — no device change", API Contracts
        line 132). Rejects a cross-organization driver (`DomainError`), the identical check
        `schedule()` above performs. Idempotent: reassigning the same driver is a no-op,
        matching every other method's "no event for no real change" convention. **No status
        restriction** — no approved document restricts changing a trip's driver at any
        particular status, and this module's own precedent (`StudentStatus`/`ParentStatus`
        methods) is to not invent a restriction graph where none is documented."""
        if new_driver_organization_id != self.organization_id:
            raise DomainError(
                f"Cannot assign Driver {new_driver_id} (organization "
                f"{new_driver_organization_id}) to Trip {self.id} (organization "
                f"{self.organization_id}): cross-organization trip assignments are not "
                "permitted."
            )
        if new_driver_id == self.driver_id:
            return
        self.driver_id = new_driver_id
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.trip_driver_changed(
                trip_id=str(self.id),
                organization_id=str(self.organization_id),
                driver_id=str(new_driver_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )


class StudentAssignment(_AggregateRoot):
    """"The CR-1 access gate" (Database Design §6.7) — binds a Student to a Route, pickup Stop,
    dropoff Stop, and optionally a Vehicle. Tenant-owned — every instance carries
    `organization_id` (`.claude/rules/database.md` #2). `vehicle_id` is a cross-module
    reference (never existence-checked, see `value_objects.py`'s Phase 13 addition);
    `student_id`/`route_id`/`pickup_stop_id`/`dropoff_stop_id` are same-module references,
    existence-checked at the application layer before this aggregate is constructed
    (`application/validators.py`).

    Phase 13 scope: `StudentAssignment` only — no `trip_students` snapshot, no Notifications,
    no Billing, no geofence processing (all out of scope per this phase's own instructions; see
    module docstring's Phase 13 addition for the full reasoning, including two flagged
    documentation gaps).
    """

    def __init__(
        self,
        *,
        id: StudentAssignmentId,
        organization_id: OrganizationId,
        student_id: StudentId,
        route_id: RouteId,
        pickup_stop_id: StopId,
        dropoff_stop_id: StopId,
        vehicle_id: VehicleId | None,
        status: StudentAssignmentStatus,
        assigned_at: datetime,
        ended_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.student_id = student_id
        self.route_id = route_id
        self.pickup_stop_id = pickup_stop_id
        self.dropoff_stop_id = dropoff_stop_id
        self.vehicle_id = vehicle_id
        self.status = status
        self.assigned_at = assigned_at
        self.ended_at = ended_at
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, StudentAssignment) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def assign(
        cls,
        *,
        id: StudentAssignmentId,
        organization_id: OrganizationId,
        student_id: StudentId,
        student_organization_id: OrganizationId,
        route_id: RouteId,
        route_organization_id: OrganizationId,
        pickup_stop_id: StopId,
        dropoff_stop_id: StopId,
        vehicle_id: VehicleId | None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "StudentAssignment":
        """Factory for a newly-created assignment ("Assign Student to Route" — this phase's own
        task wording, no more specific approved ubiquitous-language verb exists; flagged as this
        phase's own naming choice, the same posture `CreateRouteCommand` already establishes for
        an identically unnamed creation use-case). Starts `ACTIVE` — the enum's only
        non-terminal-reading value (Database Design §6.7). Rejects cross-organization
        `student`/`route` (`DomainError`), the identical pure, no-I/O placement `StudentParent.
        link`/`Trip.schedule` already establish for their own cross-aggregate organization
        checks."""
        if student_organization_id != organization_id:
            raise DomainError(
                f"Cannot assign Student {student_id} (organization "
                f"{student_organization_id}) to organization {organization_id}'s "
                "StudentAssignment: cross-organization assignments are not permitted."
            )
        if route_organization_id != organization_id:
            raise DomainError(
                f"Cannot assign Route {route_id} (organization {route_organization_id}) to "
                f"organization {organization_id}'s StudentAssignment: cross-organization "
                "assignments are not permitted."
            )
        now = clock.now()
        assignment = cls(
            id=id,
            organization_id=organization_id,
            student_id=student_id,
            route_id=route_id,
            pickup_stop_id=pickup_stop_id,
            dropoff_stop_id=dropoff_stop_id,
            vehicle_id=vehicle_id,
            status=StudentAssignmentStatus.ACTIVE,
            assigned_at=now,
            ended_at=None,
            created_at=now,
            updated_at=now,
        )
        assignment._record(
            transport_ops_events.student_assignment_created(
                student_assignment_id=str(id),
                organization_id=str(organization_id),
                student_id=str(student_id),
                route_id=str(route_id),
                pickup_stop_id=str(pickup_stop_id),
                dropoff_stop_id=str(dropoff_stop_id),
                vehicle_id=str(vehicle_id) if vehicle_id is not None else None,
                occurred_at=assignment.assigned_at,
                actor_id=actor_id,
            )
        )
        return assignment

    def remove(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`StudentAssignmentRemoved` (Backend LLD §5.4 verbatim) — CR-1 revocation event.
        Idempotent same-state no-op, mirroring `Student`'s status methods exactly. `ended_at` is
        stamped only the moment status leaves `ACTIVE` — see module docstring's Phase 13
        addition for why a later non-active-to-non-active move does not re-stamp it."""
        if self.status == StudentAssignmentStatus.REMOVED:
            return
        if self.status == StudentAssignmentStatus.ACTIVE:
            self.ended_at = clock.now()
        self.status = StudentAssignmentStatus.REMOVED
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.student_assignment_removed(
                student_assignment_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def transfer(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`StudentTransferred` (Backend LLD §5.4 verbatim) — see module docstring's Phase 13
        addition for the flagged collision with `Student.transfer`'s identically-named event.
        Idempotent same-state no-op, same `ended_at` rule as `remove` above."""
        if self.status == StudentAssignmentStatus.TRANSFERRED:
            return
        if self.status == StudentAssignmentStatus.ACTIVE:
            self.ended_at = clock.now()
        self.status = StudentAssignmentStatus.TRANSFERRED
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.student_assignment_transferred(
                student_assignment_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def graduate(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`StudentGraduated` (Backend LLD §5.4 verbatim) — see module docstring's Phase 13
        addition for the flagged collision with `Student.graduate`'s identically-named event.
        Idempotent same-state no-op, same `ended_at` rule as `remove` above."""
        if self.status == StudentAssignmentStatus.GRADUATED:
            return
        if self.status == StudentAssignmentStatus.ACTIVE:
            self.ended_at = clock.now()
        self.status = StudentAssignmentStatus.GRADUATED
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.student_assignment_graduated(
                student_assignment_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )

    def disable(self, *, clock: Clock, actor_id: str | None = None) -> None:
        """`StudentDisabled` (Backend LLD §5.4 verbatim) — see module docstring's Phase 13
        addition for the flagged collision with `Student.disable`'s identically-named event.
        Idempotent same-state no-op, same `ended_at` rule as `remove` above."""
        if self.status == StudentAssignmentStatus.DISABLED:
            return
        if self.status == StudentAssignmentStatus.ACTIVE:
            self.ended_at = clock.now()
        self.status = StudentAssignmentStatus.DISABLED
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.student_assignment_disabled(
                student_assignment_id=str(self.id),
                organization_id=str(self.organization_id),
                occurred_at=clock.now(),
                actor_id=actor_id,
            )
        )



# ============================================================================================
# ADR-0049: TransportStaff (the person) and TransportStaffRole (a configurable job title)
# ============================================================================================

_STAFF_NAME_MAX_LENGTH = 200
_STAFF_ROLE_NAME_MAX_LENGTH = 80
_EMPLOYEE_REF_MAX_LENGTH = 64
_ASSIGNMENT_REASON_MAX_LENGTH = 255
_DOCUMENT_TYPE_NAME_MAX_LENGTH = 80
_DOCUMENT_NUMBER_MAX_LENGTH = 64
_MAX_ALERT_LEAD_DAYS = 365
_MAX_ALERT_THRESHOLDS = 5


def _require_text(value: str, *, field: str, max_length: int) -> str:
    value = (value or "").strip()
    if not value:
        raise DomainError(f"{field} must not be empty")
    if len(value) > max_length:
        raise DomainError(f"{field} must be at most {max_length} characters: {len(value)}")
    return value


def _optional_text(value: str | None, *, field: str, max_length: int) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > max_length:
        raise DomainError(f"{field} must be at most {max_length} characters: {len(value)}")
    return value


class TransportStaffRole(_AggregateRoot):
    """ADR-0049 §2: an organization's own job title for bus crew — Driver, Attendant,
    Conductor, whatever the school calls them. **A title is a label and grants nothing**: the
    ability to drive a trip is the `Driver` extension, never the word "Driver". A title in use
    is archived, never deleted, so history keeps naming it."""

    def __init__(
        self,
        *,
        id: TransportStaffRoleId,
        organization_id: OrganizationId,
        name: str,
        sort_order: int,
        is_archived: bool,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.name = _require_text(name, field="Job title", max_length=_STAFF_ROLE_NAME_MAX_LENGTH)
        self.sort_order = sort_order
        self.is_archived = is_archived
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def create(
        cls,
        *,
        id: TransportStaffRoleId,
        organization_id: OrganizationId,
        name: str,
        sort_order: int,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "TransportStaffRole":
        now = clock.now()
        role = cls(
            id=id,
            organization_id=organization_id,
            name=name,
            sort_order=sort_order,
            is_archived=False,
            created_at=now,
            updated_at=now,
        )
        role._saved(created=True, actor_id=actor_id)
        return role

    def update(
        self,
        *,
        name: str,
        sort_order: int,
        is_archived: bool,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        name = _require_text(name, field="Job title", max_length=_STAFF_ROLE_NAME_MAX_LENGTH)
        if (name, sort_order, is_archived) == (self.name, self.sort_order, self.is_archived):
            return
        self.name, self.sort_order, self.is_archived = name, sort_order, is_archived
        self.updated_at = clock.now()
        self._saved(created=False, actor_id=actor_id)

    def _saved(self, *, created: bool, actor_id: str | None) -> None:
        self._record(
            transport_ops_events.transport_staff_role_saved(
                role_id=str(self.id),
                organization_id=str(self.organization_id),
                is_archived=self.is_archived,
                created=created,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


class TransportStaff(_AggregateRoot):
    """ADR-0049 §1: one person who works on school buses — the operational identity RAAD shows
    and reaches. A staff member may have no login and no bus. Driving is the separate `Driver`
    extension (licence + login), linked by `drivers.staff_id`; this record never holds a login
    itself, so a person is never recorded twice."""

    _PROFILE_FIELDS = (
        "full_name",
        "phone",
        "alternate_phone",
        "role_id",
        "employee_ref",
        "start_date",
        "emergency_contact_name",
        "emergency_contact_phone",
        "notes",
    )

    def __init__(
        self,
        *,
        id: TransportStaffId,
        organization_id: OrganizationId,
        full_name: str,
        phone: PhoneNumber | None,
        alternate_phone: PhoneNumber | None,
        role_id: TransportStaffRoleId | None,
        employee_ref: str | None,
        start_date: date | None,
        status: TransportStaffStatus,
        emergency_contact_name: str | None,
        emergency_contact_phone: PhoneNumber | None,
        notes: str | None,
        left_on: date | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.full_name = _require_text(full_name, field="Full name", max_length=_STAFF_NAME_MAX_LENGTH)
        self.phone = phone
        self.alternate_phone = alternate_phone
        self.role_id = role_id
        self.employee_ref = _optional_text(
            employee_ref, field="Employee reference", max_length=_EMPLOYEE_REF_MAX_LENGTH
        )
        self.start_date = start_date
        self.status = status
        self.emergency_contact_name = _optional_text(
            emergency_contact_name,
            field="Emergency contact name",
            max_length=_EMERGENCY_CONTACT_NAME_MAX_LENGTH,
        )
        self.emergency_contact_phone = emergency_contact_phone
        _validate_notes(notes)
        self.notes = notes
        self.left_on = left_on
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TransportStaff) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def register(
        cls,
        *,
        id: TransportStaffId,
        organization_id: OrganizationId,
        full_name: str,
        phone: PhoneNumber | None = None,
        alternate_phone: PhoneNumber | None = None,
        role_id: TransportStaffRoleId | None = None,
        employee_ref: str | None = None,
        start_date: date | None = None,
        emergency_contact_name: str | None = None,
        emergency_contact_phone: PhoneNumber | None = None,
        notes: str | None = None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "TransportStaff":
        now = clock.now()
        staff = cls(
            id=id,
            organization_id=organization_id,
            full_name=full_name,
            phone=phone,
            alternate_phone=alternate_phone,
            role_id=role_id,
            employee_ref=employee_ref,
            start_date=start_date,
            status=TransportStaffStatus.ACTIVE,
            emergency_contact_name=emergency_contact_name,
            emergency_contact_phone=emergency_contact_phone,
            notes=notes,
            left_on=None,
            created_at=now,
            updated_at=now,
        )
        staff._record(
            transport_ops_events.transport_staff_registered(
                staff_id=str(id),
                organization_id=str(organization_id),
                role_id=str(role_id) if role_id else None,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return staff

    def update_profile(self, *, clock: Clock, actor_id: str | None = None, **values: object) -> None:
        """Replaces the editable profile fields given. Only fields that actually changed are
        named in the event — never their values (personal data stays out of the audit
        payload)."""
        unknown = set(values) - set(self._PROFILE_FIELDS)
        if unknown:
            raise DomainError(f"Unknown staff profile field(s): {sorted(unknown)}")
        before = {field: getattr(self, field) for field in values}
        candidate = TransportStaff(
            id=self.id,
            organization_id=self.organization_id,
            status=self.status,
            left_on=self.left_on,
            created_at=self.created_at,
            updated_at=self.updated_at,
            **{field: values.get(field, getattr(self, field)) for field in self._PROFILE_FIELDS},
        )
        changed = [f for f in values if getattr(candidate, f) != before[f]]
        if not changed:
            return
        for field in changed:
            setattr(self, field, getattr(candidate, field))
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.transport_staff_profile_updated(
                staff_id=str(self.id),
                organization_id=str(self.organization_id),
                changed_fields=changed,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def change_status(
        self,
        status: TransportStaffStatus,
        *,
        clock: Clock,
        actor_id: str | None = None,
    ) -> bool:
        """Returns whether anything changed. Leaving records `left_on`; coming back from
        `left` clears it. The caller ends the crew assignments and deactivates a linked driver
        in the same transaction (ADR-0049 §4)."""
        if status == self.status:
            return False
        previous = self.status
        self.status = status
        now = clock.now()
        self.left_on = now.date() if status is TransportStaffStatus.LEFT else None
        self.updated_at = now
        self._record(
            transport_ops_events.transport_staff_status_changed(
                staff_id=str(self.id),
                organization_id=str(self.organization_id),
                status=status.value,
                previous_status=previous.value,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return True


# ============================================================================================
# ADR-0050: VehicleStaffAssignment — the bus crew and its history
# ============================================================================================


class VehicleStaffAssignment(_AggregateRoot):
    """One person on one bus for a period (ADR-0050). Rows are never deleted or overwritten:
    replacing someone ends their row and starts a new one, so "who was on Bus 12 last term" is
    always answerable. `ends_on` is inclusive; `None` means open-ended. The job title is the
    one held *during* this assignment, so a later title change never rewrites history."""

    def __init__(
        self,
        *,
        id: VehicleStaffAssignmentId,
        organization_id: OrganizationId,
        staff_id: TransportStaffId,
        vehicle_id: VehicleId,
        role_id: TransportStaffRoleId | None,
        route_id: RouteId | None,
        starts_on: date,
        ends_on: date | None,
        kind: StaffAssignmentKind,
        reason: str | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        if kind is StaffAssignmentKind.TEMPORARY and ends_on is None:
            raise DomainError("A temporary assignment must have an end date")
        if ends_on is not None and ends_on < starts_on - timedelta(days=1):
            raise DomainError("An assignment cannot end before it starts")
        self.id = id
        self.organization_id = organization_id
        self.staff_id = staff_id
        self.vehicle_id = vehicle_id
        self.role_id = role_id
        self.route_id = route_id
        self.starts_on = starts_on
        self.ends_on = ends_on
        self.kind = kind
        self.reason = _optional_text(reason, field="Reason", max_length=_ASSIGNMENT_REASON_MAX_LENGTH)
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, VehicleStaffAssignment) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def is_current(self, today: date) -> bool:
        return self.starts_on <= today and (self.ends_on is None or self.ends_on >= today)

    def overlaps(self, starts_on: date, ends_on: date | None) -> bool:
        """Whether this assignment shares at least one day with `[starts_on, ends_on]`."""
        mine_end = self.ends_on if self.ends_on is not None else date.max
        theirs_end = ends_on if ends_on is not None else date.max
        return self.starts_on <= theirs_end and starts_on <= mine_end

    @classmethod
    def assign(
        cls,
        *,
        id: VehicleStaffAssignmentId,
        organization_id: OrganizationId,
        staff_id: TransportStaffId,
        vehicle_id: VehicleId,
        role_id: TransportStaffRoleId | None,
        route_id: RouteId | None,
        starts_on: date,
        ends_on: date | None,
        kind: StaffAssignmentKind,
        reason: str | None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "VehicleStaffAssignment":
        if ends_on is not None and ends_on < starts_on:
            raise DomainError("An assignment cannot end before it starts")
        now = clock.now()
        assignment = cls(
            id=id,
            organization_id=organization_id,
            staff_id=staff_id,
            vehicle_id=vehicle_id,
            role_id=role_id,
            route_id=route_id,
            starts_on=starts_on,
            ends_on=ends_on,
            kind=kind,
            reason=reason,
            created_at=now,
            updated_at=now,
        )
        assignment._record(
            transport_ops_events.vehicle_staff_assigned(
                assignment_id=str(id),
                organization_id=str(organization_id),
                staff_id=str(staff_id),
                vehicle_id=str(vehicle_id),
                route_id=str(route_id) if route_id else None,
                role_id=str(role_id) if role_id else None,
                kind=kind.value,
                starts_on=starts_on.isoformat(),
                ends_on=ends_on.isoformat() if ends_on else None,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return assignment

    def end(self, on: date, *, clock: Clock, actor_id: str | None = None) -> bool:
        """Ends the assignment on `on` (inclusive). Ending never extends an assignment, and an
        assignment that has not started yet is ended the day before it starts — it never took
        effect, and its row stays as the record that it was planned. Returns whether anything
        changed."""
        effective = max(on, self.starts_on - timedelta(days=1))
        if self.ends_on is not None and self.ends_on <= effective:
            return False
        self.ends_on = effective
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.vehicle_staff_assignment_ended(
                assignment_id=str(self.id),
                organization_id=str(self.organization_id),
                staff_id=str(self.staff_id),
                vehicle_id=str(self.vehicle_id),
                ends_on=effective.isoformat(),
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )
        return True


# ============================================================================================
# ADR-0051: StaffDocumentType and StaffDocument
# ============================================================================================


def _normalise_lead_days(lead_days: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    values = sorted({int(day) for day in lead_days}, reverse=True)
    if len(values) > _MAX_ALERT_THRESHOLDS:
        raise DomainError(f"At most {_MAX_ALERT_THRESHOLDS} alert lead days are allowed")
    if any(day < 1 or day > _MAX_ALERT_LEAD_DAYS for day in values):
        raise DomainError(f"Alert lead days must be between 1 and {_MAX_ALERT_LEAD_DAYS}")
    return tuple(values)


class StaffDocumentType(_AggregateRoot):
    """An organization's own kind of staff document (licence, medical certificate, police
    clearance…) and how many days before expiry its admins are alerted (ADR-0051 §1)."""

    def __init__(
        self,
        *,
        id: StaffDocumentTypeId,
        organization_id: OrganizationId,
        name: str,
        alert_lead_days: tuple[int, ...],
        is_archived: bool,
        created_at: datetime,
        updated_at: datetime,
        required_for: StaffDocumentRequirement = StaffDocumentRequirement.NONE,
        enforcement: StaffDocumentEnforcement = StaffDocumentEnforcement.WARN,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.name = _require_text(
            name, field="Document type", max_length=_DOCUMENT_TYPE_NAME_MAX_LENGTH
        )
        self.alert_lead_days = _normalise_lead_days(alert_lead_days)
        self.is_archived = is_archived
        #: ADR-0058 §1. Both defaults leave the type exactly as it behaved before Phase 4.
        self.required_for = required_for
        self.enforcement = enforcement
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def create(
        cls,
        *,
        id: StaffDocumentTypeId,
        organization_id: OrganizationId,
        name: str,
        alert_lead_days: tuple[int, ...] = (30, 7),
        required_for: StaffDocumentRequirement = StaffDocumentRequirement.NONE,
        enforcement: StaffDocumentEnforcement = StaffDocumentEnforcement.WARN,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "StaffDocumentType":
        now = clock.now()
        doc_type = cls(
            id=id,
            organization_id=organization_id,
            name=name,
            alert_lead_days=alert_lead_days,
            is_archived=False,
            created_at=now,
            updated_at=now,
            required_for=required_for,
            enforcement=enforcement,
        )
        doc_type._saved(created=True, actor_id=actor_id)
        return doc_type

    def update(
        self,
        *,
        name: str,
        alert_lead_days: tuple[int, ...],
        is_archived: bool,
        clock: Clock,
        actor_id: str | None = None,
        required_for: StaffDocumentRequirement | None = None,
        enforcement: StaffDocumentEnforcement | None = None,
    ) -> None:
        """`required_for`/`enforcement` left as `None` keep their current value."""
        name = _require_text(name, field="Document type", max_length=_DOCUMENT_TYPE_NAME_MAX_LENGTH)
        lead = _normalise_lead_days(alert_lead_days)
        required_for = self.required_for if required_for is None else required_for
        enforcement = self.enforcement if enforcement is None else enforcement
        new = (name, lead, is_archived, required_for, enforcement)
        if new == (self.name, self.alert_lead_days, self.is_archived, self.required_for, self.enforcement):
            return
        self.name, self.alert_lead_days, self.is_archived, self.required_for, self.enforcement = new
        self.updated_at = clock.now()
        self._saved(created=False, actor_id=actor_id)

    def applies_to(self, *, is_driver: bool) -> bool:
        """ADR-0058 §1: is this type required of that person? An archived type requires nothing."""
        if self.is_archived:
            return False
        if self.required_for is StaffDocumentRequirement.ALL_STAFF:
            return True
        return self.required_for is StaffDocumentRequirement.DRIVERS and is_driver

    def _saved(self, *, created: bool, actor_id: str | None) -> None:
        self._record(
            transport_ops_events.staff_document_type_saved(
                type_id=str(self.id),
                organization_id=str(self.organization_id),
                alert_lead_days=list(self.alert_lead_days),
                is_archived=self.is_archived,
                required_for=self.required_for.value,
                enforcement=self.enforcement.value,
                created=created,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


class StaffDocument(_AggregateRoot):
    """One credential a staff member holds (ADR-0051 §2): metadata only — never a file or a
    scan. Status is computed from the dates on every read. A renewal is a new document; the old
    one points at it (`replaced_by_id`) and drops out of every alert."""

    _EDITABLE = ("number", "issued_on", "expires_on", "notes")

    def __init__(
        self,
        *,
        id: StaffDocumentId,
        organization_id: OrganizationId,
        staff_id: TransportStaffId,
        type_id: StaffDocumentTypeId,
        number: str | None,
        issued_on: date | None,
        expires_on: date | None,
        notes: str | None,
        replaced_by_id: StaffDocumentId | None,
        alerted_threshold_days: int | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        if issued_on is not None and expires_on is not None and expires_on < issued_on:
            raise DomainError("A document cannot expire before it was issued")
        _validate_notes(notes)
        self.id = id
        self.organization_id = organization_id
        self.staff_id = staff_id
        self.type_id = type_id
        self.number = _optional_text(number, field="Document number", max_length=_DOCUMENT_NUMBER_MAX_LENGTH)
        self.issued_on = issued_on
        self.expires_on = expires_on
        self.notes = notes
        self.replaced_by_id = replaced_by_id
        self.alerted_threshold_days = alerted_threshold_days
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, StaffDocument) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def record(
        cls,
        *,
        id: StaffDocumentId,
        organization_id: OrganizationId,
        staff_id: TransportStaffId,
        type_id: StaffDocumentTypeId,
        number: str | None,
        issued_on: date | None,
        expires_on: date | None,
        notes: str | None,
        replaces_id: StaffDocumentId | None,
        clock: Clock,
        actor_id: str | None = None,
    ) -> "StaffDocument":
        now = clock.now()
        document = cls(
            id=id,
            organization_id=organization_id,
            staff_id=staff_id,
            type_id=type_id,
            number=number,
            issued_on=issued_on,
            expires_on=expires_on,
            notes=notes,
            replaced_by_id=None,
            alerted_threshold_days=None,
            created_at=now,
            updated_at=now,
        )
        document._record(
            transport_ops_events.staff_document_recorded(
                document_id=str(id),
                organization_id=str(organization_id),
                staff_id=str(staff_id),
                type_id=str(type_id),
                expires_on=expires_on.isoformat() if expires_on else None,
                replaces_id=str(replaces_id) if replaces_id else None,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return document

    def update(self, *, clock: Clock, actor_id: str | None = None, **values: object) -> None:
        unknown = set(values) - set(self._EDITABLE)
        if unknown:
            raise DomainError(f"Unknown document field(s): {sorted(unknown)}")
        merged = {field: values.get(field, getattr(self, field)) for field in self._EDITABLE}
        candidate = StaffDocument(
            id=self.id,
            organization_id=self.organization_id,
            staff_id=self.staff_id,
            type_id=self.type_id,
            replaced_by_id=self.replaced_by_id,
            alerted_threshold_days=self.alerted_threshold_days,
            created_at=self.created_at,
            updated_at=self.updated_at,
            **merged,
        )
        changed = [f for f in self._EDITABLE if getattr(candidate, f) != getattr(self, f)]
        if not changed:
            return
        for field in changed:
            setattr(self, field, getattr(candidate, field))
        if "expires_on" in changed:
            # A corrected expiry date starts its alerts again from scratch.
            self.alerted_threshold_days = None
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.staff_document_updated(
                document_id=str(self.id),
                organization_id=str(self.organization_id),
                changed_fields=changed,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def mark_replaced(self, by: StaffDocumentId, *, clock: Clock, actor_id: str | None = None) -> None:
        if self.replaced_by_id is not None:
            raise ConflictError("This document has already been renewed")
        self.replaced_by_id = by
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.staff_document_updated(
                document_id=str(self.id),
                organization_id=str(self.organization_id),
                changed_fields=["replaced_by_id"],
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def days_left(self, today: date) -> int | None:
        return None if self.expires_on is None else (self.expires_on - today).days

    def status(self, today: date, lead_days: tuple[int, ...]) -> StaffDocumentStatus:
        if self.replaced_by_id is not None:
            return StaffDocumentStatus.SUPERSEDED
        left = self.days_left(today)
        if left is None:
            return StaffDocumentStatus.NO_EXPIRY
        if left < 0:
            return StaffDocumentStatus.EXPIRED
        if left <= max(lead_days, default=0):
            return StaffDocumentStatus.EXPIRING
        return StaffDocumentStatus.VALID

    def due_alert_threshold(self, today: date, lead_days: tuple[int, ...]) -> int | None:
        """The alert this document is due, if any (ADR-0051 §3). Thresholds are the type's lead
        days plus 0 ("expires today or has expired"). The smallest threshold crossed is due
        when it is smaller than the last one sent, so each is sent exactly once and a document
        found already expired sends one alert, not a burst."""
        if self.replaced_by_id is not None:
            return None
        left = self.days_left(today)
        if left is None:
            return None
        crossed = [t for t in set(lead_days) | {0} if left <= t]
        if not crossed:
            return None
        smallest = min(crossed)
        if self.alerted_threshold_days is not None and smallest >= self.alerted_threshold_days:
            return None
        return smallest

    def mark_alerted(self, threshold_days: int, *, clock: Clock) -> None:
        self.alerted_threshold_days = threshold_days
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.staff_document_expiry_alerted(
                document_id=str(self.id),
                organization_id=str(self.organization_id),
                threshold_days=threshold_days,
                occurred_at=self.updated_at,
            )
        )


# ============================================================================================
# ADR-0052/0053: timetable, closed days, unavailability and cover
# ============================================================================================

_CANCEL_REASON_MAX_LENGTH = 255
_CLOSURE_LABEL_MAX_LENGTH = 120


def _normalise_weekdays(weekdays: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    values = tuple(sorted({int(day) for day in weekdays}))
    if not values:
        raise DomainError("Choose at least one weekday")
    if any(day < 1 or day > 7 for day in values):
        raise DomainError("Weekdays are 1 (Monday) to 7 (Sunday)")
    return values


def _check_period(starts_on: date, ends_on: date | None, *, what: str) -> None:
    if ends_on is not None and ends_on < starts_on:
        raise DomainError(f"{what} cannot end before it starts")


class RouteTimetableEntry(_AggregateRoot):
    """ADR-0052 §1: one regular run — this bus, on this route, in this period, on these
    weekdays, driven by default by this driver. Trips are generated from it; editing it never
    rewrites a trip already generated."""

    _EDITABLE = (
        "route_id",
        "vehicle_id",
        "trip_type",
        "weekdays",
        "planned_departure",
        "default_driver_id",
        "valid_from",
        "valid_until",
        "is_active",
    )

    def __init__(
        self,
        *,
        id: RouteTimetableEntryId,
        organization_id: OrganizationId,
        route_id: RouteId,
        vehicle_id: VehicleId,
        trip_type: TripType,
        weekdays: tuple[int, ...],
        planned_departure: time | None,
        default_driver_id: DriverId,
        valid_from: date,
        valid_until: date | None,
        is_active: bool,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _check_period(valid_from, valid_until, what="A timetable entry")
        self.id = id
        self.organization_id = organization_id
        self.route_id = route_id
        self.vehicle_id = vehicle_id
        self.trip_type = trip_type
        self.weekdays = _normalise_weekdays(weekdays)
        self.planned_departure = planned_departure
        self.default_driver_id = default_driver_id
        self.valid_from = valid_from
        self.valid_until = valid_until
        self.is_active = is_active
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RouteTimetableEntry) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def create(cls, *, id: RouteTimetableEntryId, organization_id: OrganizationId, clock: Clock,
               actor_id: str | None = None, **values: object) -> "RouteTimetableEntry":
        now = clock.now()
        entry = cls(id=id, organization_id=organization_id, created_at=now, updated_at=now,
                    **{"is_active": True, **values})  # type: ignore[arg-type]
        entry._saved(created=True, actor_id=actor_id)
        return entry

    def update(self, *, clock: Clock, actor_id: str | None = None, **values: object) -> None:
        unknown = set(values) - set(self._EDITABLE)
        if unknown:
            raise DomainError(f"Unknown timetable field(s): {sorted(unknown)}")
        merged = {field: values.get(field, getattr(self, field)) for field in self._EDITABLE}
        candidate = RouteTimetableEntry(
            id=self.id,
            organization_id=self.organization_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            **merged,  # type: ignore[arg-type]
        )
        changed = [f for f in self._EDITABLE if getattr(candidate, f) != getattr(self, f)]
        if not changed:
            return
        for field in changed:
            setattr(self, field, getattr(candidate, field))
        self.updated_at = clock.now()
        self._saved(created=False, actor_id=actor_id)

    def runs_on(self, day: date) -> bool:
        return (
            self.is_active
            and day.isoweekday() in self.weekdays
            and self.valid_from <= day
            and (self.valid_until is None or day <= self.valid_until)
        )

    def clashes_with(self, other: "RouteTimetableEntry") -> bool:
        """Same bus, same period, a shared weekday and overlapping validity (ADR-0052 §1)."""
        if other.id == self.id or not (self.is_active and other.is_active):
            return False
        if other.vehicle_id != self.vehicle_id or other.trip_type is not self.trip_type:
            return False
        if not set(self.weekdays) & set(other.weekdays):
            return False
        mine_end = self.valid_until or date.max
        theirs_end = other.valid_until or date.max
        return self.valid_from <= theirs_end and other.valid_from <= mine_end

    def _saved(self, *, created: bool, actor_id: str | None) -> None:
        self._record(
            transport_ops_events.route_timetable_entry_saved(
                entry_id=str(self.id),
                organization_id=str(self.organization_id),
                route_id=str(self.route_id),
                vehicle_id=str(self.vehicle_id),
                trip_type=self.trip_type.value,
                weekdays=list(self.weekdays),
                is_active=self.is_active,
                created=created,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


class OperatingClosure(_AggregateRoot):
    """ADR-0052 §2: days the organization runs no transport. Withdrawn, never deleted."""

    def __init__(
        self,
        *,
        id: OperatingClosureId,
        organization_id: OrganizationId,
        starts_on: date,
        ends_on: date,
        label: str,
        withdrawn_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _check_period(starts_on, ends_on, what="A closure")
        self.id = id
        self.organization_id = organization_id
        self.starts_on = starts_on
        self.ends_on = ends_on
        self.label = _require_text(label, field="Closure label", max_length=_CLOSURE_LABEL_MAX_LENGTH)
        self.withdrawn_at = withdrawn_at
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def record(cls, *, id: OperatingClosureId, organization_id: OrganizationId, starts_on: date,
               ends_on: date, label: str, clock: Clock, actor_id: str | None = None) -> "OperatingClosure":
        now = clock.now()
        closure = cls(id=id, organization_id=organization_id, starts_on=starts_on, ends_on=ends_on,
                      label=label, withdrawn_at=None, created_at=now, updated_at=now)
        closure._saved(withdrawn=False, actor_id=actor_id)
        return closure

    def covers(self, day: date) -> bool:
        return self.withdrawn_at is None and self.starts_on <= day <= self.ends_on

    def withdraw(self, *, clock: Clock, actor_id: str | None = None) -> bool:
        if self.withdrawn_at is not None:
            return False
        self.withdrawn_at = self.updated_at = clock.now()
        self._saved(withdrawn=True, actor_id=actor_id)
        return True

    def _saved(self, *, withdrawn: bool, actor_id: str | None) -> None:
        self._record(
            transport_ops_events.operating_closure_saved(
                closure_id=str(self.id),
                organization_id=str(self.organization_id),
                starts_on=self.starts_on.isoformat(),
                ends_on=self.ends_on.isoformat(),
                withdrawn=withdrawn,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


class StaffUnavailability(_AggregateRoot):
    """ADR-0053 §1: "this person cannot work from X to Y" — an operational fact entered by the
    Org Admin. Not leave management: no request, approval or balance. The note is private."""

    def __init__(
        self,
        *,
        id: StaffUnavailabilityId,
        organization_id: OrganizationId,
        staff_id: TransportStaffId,
        starts_on: date,
        ends_on: date,
        reason: UnavailabilityReason,
        note: str | None,
        withdrawn_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _check_period(starts_on, ends_on, what="An unavailability")
        _validate_notes(note)
        self.id = id
        self.organization_id = organization_id
        self.staff_id = staff_id
        self.starts_on = starts_on
        self.ends_on = ends_on
        self.reason = reason
        self.note = note
        self.withdrawn_at = withdrawn_at
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def record(cls, *, id: StaffUnavailabilityId, organization_id: OrganizationId,
               staff_id: TransportStaffId, starts_on: date, ends_on: date,
               reason: UnavailabilityReason, note: str | None, clock: Clock,
               actor_id: str | None = None) -> "StaffUnavailability":
        now = clock.now()
        item = cls(id=id, organization_id=organization_id, staff_id=staff_id, starts_on=starts_on,
                   ends_on=ends_on, reason=reason, note=note, withdrawn_at=None, created_at=now,
                   updated_at=now)
        item._saved(withdrawn=False, actor_id=actor_id)
        return item

    @property
    def is_withdrawn(self) -> bool:
        return self.withdrawn_at is not None

    def covers(self, day: date) -> bool:
        return not self.is_withdrawn and self.starts_on <= day <= self.ends_on

    def withdraw(self, *, clock: Clock, actor_id: str | None = None) -> bool:
        if self.is_withdrawn:
            return False
        self.withdrawn_at = self.updated_at = clock.now()
        self._saved(withdrawn=True, actor_id=actor_id)
        return True

    def _saved(self, *, withdrawn: bool, actor_id: str | None) -> None:
        self._record(
            transport_ops_events.staff_unavailability_saved(
                unavailability_id=str(self.id),
                organization_id=str(self.organization_id),
                staff_id=str(self.staff_id),
                starts_on=self.starts_on.isoformat(),
                ends_on=self.ends_on.isoformat(),
                reason=self.reason.value,
                withdrawn=withdrawn,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )


class StaffCover(_AggregateRoot):
    """ADR-0053 §2: who stands in for an unavailable person, on which bus, for which days. The
    substitute's temporary crew assignment (ADR-0050) is the history row; this links it to the
    unavailability it answers."""

    def __init__(
        self,
        *,
        id: StaffCoverId,
        organization_id: OrganizationId,
        unavailability_id: StaffUnavailabilityId,
        absent_staff_id: TransportStaffId,
        substitute_staff_id: TransportStaffId,
        vehicle_id: VehicleId,
        starts_on: date,
        ends_on: date,
        assignment_id: VehicleStaffAssignmentId | None,
        withdrawn_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        _check_period(starts_on, ends_on, what="A cover")
        if substitute_staff_id == absent_staff_id:
            raise DomainError("Someone cannot cover for themselves")
        self.id = id
        self.organization_id = organization_id
        self.unavailability_id = unavailability_id
        self.absent_staff_id = absent_staff_id
        self.substitute_staff_id = substitute_staff_id
        self.vehicle_id = vehicle_id
        self.starts_on = starts_on
        self.ends_on = ends_on
        self.assignment_id = assignment_id
        self.withdrawn_at = withdrawn_at
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def create(cls, *, id: StaffCoverId, organization_id: OrganizationId,
               unavailability: StaffUnavailability, substitute_staff_id: TransportStaffId,
               vehicle_id: VehicleId, starts_on: date, ends_on: date,
               assignment_id: VehicleStaffAssignmentId | None, clock: Clock,
               actor_id: str | None = None) -> "StaffCover":
        if unavailability.is_withdrawn:
            raise DomainError("This unavailability has been withdrawn")
        if starts_on < unavailability.starts_on or ends_on > unavailability.ends_on:
            raise DomainError("A cover must fall within the unavailability it covers")
        now = clock.now()
        cover = cls(id=id, organization_id=organization_id, unavailability_id=unavailability.id,
                    absent_staff_id=unavailability.staff_id, substitute_staff_id=substitute_staff_id,
                    vehicle_id=vehicle_id, starts_on=starts_on, ends_on=ends_on,
                    assignment_id=assignment_id, withdrawn_at=None, created_at=now, updated_at=now)
        cover._saved(withdrawn=False, actor_id=actor_id)
        return cover

    @property
    def is_withdrawn(self) -> bool:
        return self.withdrawn_at is not None

    def covers(self, day: date) -> bool:
        return not self.is_withdrawn and self.starts_on <= day <= self.ends_on

    def withdraw(self, *, clock: Clock, actor_id: str | None = None) -> bool:
        if self.is_withdrawn:
            return False
        self.withdrawn_at = self.updated_at = clock.now()
        self._saved(withdrawn=True, actor_id=actor_id)
        return True

    def _saved(self, *, withdrawn: bool, actor_id: str | None) -> None:
        self._record(
            transport_ops_events.staff_cover_saved(
                cover_id=str(self.id),
                organization_id=str(self.organization_id),
                unavailability_id=str(self.unavailability_id),
                substitute_staff_id=str(self.substitute_staff_id),
                vehicle_id=str(self.vehicle_id),
                starts_on=self.starts_on.isoformat(),
                ends_on=self.ends_on.isoformat(),
                withdrawn=withdrawn,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )



# ============================================================================================
# ADR-0056: the incident log
# ============================================================================================

_INCIDENT_TITLE_MAX_LENGTH = 200
_INCIDENT_TEXT_MAX_LENGTH = 4000

#: Allowed status moves. `closed` is final; a resolved incident can be reopened for more work.
_INCIDENT_TRANSITIONS: dict[IncidentStatus, frozenset[IncidentStatus]] = {
    IncidentStatus.OPEN: frozenset({IncidentStatus.INVESTIGATING, IncidentStatus.RESOLVED, IncidentStatus.CLOSED}),
    IncidentStatus.INVESTIGATING: frozenset({IncidentStatus.RESOLVED, IncidentStatus.CLOSED}),
    IncidentStatus.RESOLVED: frozenset({IncidentStatus.INVESTIGATING, IncidentStatus.CLOSED}),
    IncidentStatus.CLOSED: frozenset(),
}


def _incident_text(value: str | None, field: str) -> str | None:
    value = (value or "").strip() or None
    if value is not None and len(value) > _INCIDENT_TEXT_MAX_LENGTH:
        raise DomainError(f"{field} must be at most {_INCIDENT_TEXT_MAX_LENGTH} characters")
    return value


class Incident(_AggregateRoot):
    """An operational incident (ADR-0056): what happened, where, to whom, and how it was handled.
    Closed, never deleted; an entry made by mistake is closed as `recorded_in_error`. The people
    involved are id lists checked by the service to be in the same organization."""

    _EDITABLE = (
        "category",
        "severity",
        "occurred_at",
        "vehicle_id",
        "trip_id",
        "route_id",
        "title",
        "description",
        "actions_taken",
        "staff_ids",
        "student_ids",
    )

    def __init__(
        self,
        *,
        id: IncidentId,
        organization_id: OrganizationId,
        category: IncidentCategory,
        severity: IncidentSeverity,
        occurred_at: datetime,
        vehicle_id: VehicleId | None,
        trip_id: TripId | None,
        route_id: RouteId | None,
        title: str,
        description: str | None,
        actions_taken: str | None,
        staff_ids: tuple[str, ...],
        student_ids: tuple[str, ...],
        status: IncidentStatus,
        resolution: str | None,
        recorded_in_error: bool,
        source_alert_id: str | None,
        closed_at: datetime | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        super().__init__()
        self.id = id
        self.organization_id = organization_id
        self.category = category
        self.severity = severity
        self.occurred_at = occurred_at
        self.vehicle_id = vehicle_id
        self.trip_id = trip_id
        self.route_id = route_id
        self.title = _require_text(title, field="Title", max_length=_INCIDENT_TITLE_MAX_LENGTH)
        self.description = _incident_text(description, "Description")
        self.actions_taken = _incident_text(actions_taken, "Actions taken")
        self.staff_ids = tuple(dict.fromkeys(staff_ids))
        self.student_ids = tuple(dict.fromkeys(student_ids))
        self.status = status
        self.resolution = _incident_text(resolution, "Resolution")
        self.recorded_in_error = recorded_in_error
        self.source_alert_id = source_alert_id
        self.closed_at = closed_at
        self.created_at = created_at
        self.updated_at = updated_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Incident) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def record(cls, *, id: IncidentId, organization_id: OrganizationId, clock: Clock,
               actor_id: str | None = None, source_alert_id: str | None = None,
               **values: object) -> "Incident":
        now = clock.now()
        incident = cls(
            id=id,
            organization_id=organization_id,
            status=IncidentStatus.OPEN,
            resolution=None,
            recorded_in_error=False,
            source_alert_id=source_alert_id,
            closed_at=None,
            created_at=now,
            updated_at=now,
            **values,  # type: ignore[arg-type]
        )
        incident._record(
            transport_ops_events.incident_recorded(
                incident_id=str(id),
                organization_id=str(organization_id),
                category=incident.category.value,
                severity=incident.severity.value,
                vehicle_id=str(incident.vehicle_id) if incident.vehicle_id else None,
                trip_id=str(incident.trip_id) if incident.trip_id else None,
                source_alert_id=source_alert_id,
                occurred_at=now,
                actor_id=actor_id,
            )
        )
        return incident

    def update(self, *, clock: Clock, actor_id: str | None = None, **values: object) -> None:
        if self.status is IncidentStatus.CLOSED:
            raise RuleViolationError("A closed incident cannot be edited; add a note instead.")
        unknown = set(values) - set(self._EDITABLE)
        if unknown:
            raise DomainError(f"Unknown incident field(s): {sorted(unknown)}")
        candidate = Incident(
            id=self.id,
            organization_id=self.organization_id,
            status=self.status,
            resolution=self.resolution,
            recorded_in_error=self.recorded_in_error,
            source_alert_id=self.source_alert_id,
            closed_at=self.closed_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
            **{f: values.get(f, getattr(self, f)) for f in self._EDITABLE},  # type: ignore[arg-type]
        )
        changed = [f for f in self._EDITABLE if getattr(candidate, f) != getattr(self, f)]
        if not changed:
            return
        for field in changed:
            setattr(self, field, getattr(candidate, field))
        self.updated_at = clock.now()
        self._record(
            transport_ops_events.incident_updated(
                incident_id=str(self.id),
                organization_id=str(self.organization_id),
                changed_fields=changed,
                occurred_at=self.updated_at,
                actor_id=actor_id,
            )
        )

    def change_status(
        self,
        status: IncidentStatus,
        *,
        resolution: str | None = None,
        recorded_in_error: bool = False,
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        if status is self.status:
            return
        if status not in _INCIDENT_TRANSITIONS[self.status]:
            raise RuleViolationError(f"An incident cannot go from {self.status.value} to {status.value}.")
        resolution = _incident_text(resolution, "Resolution")
        if status is IncidentStatus.CLOSED and resolution is None and self.resolution is None:
            raise DomainError("Closing an incident needs a resolution note.")
        if recorded_in_error and status is not IncidentStatus.CLOSED:
            raise DomainError("Only a closed incident can be marked as recorded in error.")
        previous = self.status
        now = clock.now()
        self.status = status
        if resolution is not None:
            self.resolution = resolution
        self.recorded_in_error = recorded_in_error
        self.closed_at = now if status is IncidentStatus.CLOSED else None
        self.updated_at = now
        self._record(
            transport_ops_events.incident_status_changed(
                incident_id=str(self.id),
                organization_id=str(self.organization_id),
                status=status.value,
                previous_status=previous.value,
                recorded_in_error=recorded_in_error,
                occurred_at=now,
                actor_id=actor_id,
            )
        )


class IncidentNote(_AggregateRoot):
    """One timeline entry on an incident (ADR-0056 §2): append-only, never edited."""

    def __init__(
        self,
        *,
        id: IncidentNoteId,
        organization_id: OrganizationId,
        incident_id: IncidentId,
        kind: IncidentNoteKind,
        body: str,
        author_id: str | None,
        created_at: datetime,
    ) -> None:
        super().__init__()
        body = (body or "").strip()
        if not body:
            raise DomainError("A note needs some text")
        if len(body) > _INCIDENT_TEXT_MAX_LENGTH:
            raise DomainError(f"A note must be at most {_INCIDENT_TEXT_MAX_LENGTH} characters")
        self.id = id
        self.organization_id = organization_id
        self.incident_id = incident_id
        self.kind = kind
        self.body = body
        self.author_id = author_id
        self.created_at = created_at

    @classmethod
    def add(cls, *, id: IncidentNoteId, incident: Incident, kind: IncidentNoteKind, body: str,
            clock: Clock, actor_id: str | None = None) -> "IncidentNote":
        note = cls(id=id, organization_id=incident.organization_id, incident_id=incident.id,
                   kind=kind, body=body, author_id=actor_id, created_at=clock.now())
        note._record(
            transport_ops_events.incident_note_added(
                note_id=str(id),
                organization_id=str(incident.organization_id),
                incident_id=str(incident.id),
                kind=kind.value,
                occurred_at=note.created_at,
                actor_id=actor_id,
            )
        )
        return note
