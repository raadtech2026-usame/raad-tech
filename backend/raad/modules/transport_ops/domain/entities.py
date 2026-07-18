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
"""

from __future__ import annotations

from raad.core.errors.exceptions import ConflictError, DomainError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain import events as transport_ops_events
from raad.modules.transport_ops.domain.value_objects import (
    DriverId,
    DriverStatus,
    OrganizationId,
    ParentId,
    ParentStatus,
    PhoneNumber,
    RouteId,
    RouteStatus,
    StopId,
    StudentId,
    StudentStatus,
    UserId,
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
    ) -> None:
        super().__init__()
        _validate_full_name(full_name)
        _validate_external_ref(external_ref)
        self.id = id
        self.organization_id = organization_id
        self.full_name = full_name
        self.external_ref = external_ref
        self.status = status

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
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Student":
        """Factory for a newly-enrolled student. No `pending`/`invited` status exists in the
        approved enum (Database Design §6.2: `active,disabled,graduated,transferred` only), so
        an enrolled student starts `active` — the same reasoning `organization.domain.entities.
        Organization.register` gives for its own status enum."""
        student = cls(
            id=id,
            organization_id=organization_id,
            full_name=full_name,
            external_ref=external_ref,
            status=StudentStatus.ACTIVE,
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
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Phase 10.2 addition — see module docstring's addendum. Idempotent: a call that
        changes neither field is a no-op, the same "no event for no real change" precedent
        every status-change method above already follows."""
        _validate_full_name(full_name)
        _validate_external_ref(external_ref)
        if full_name == self.full_name and external_ref == self.external_ref:
            return
        self.full_name = full_name
        self.external_ref = external_ref
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
    ) -> None:
        super().__init__()
        _validate_parent_full_name(full_name)
        self.id = id
        self.organization_id = organization_id
        self.user_id = user_id
        self.full_name = full_name
        self.phone = phone
        self.status = status

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
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Parent":
        """Factory for a newly-registered parent profile. No `pending`/`invited` status exists
        in the (undocumented-values) status enum — see `value_objects.py`'s `ParentStatus`
        docstring — so a registered parent starts `active`, the same reasoning
        `Student.enroll`/`Organization.register` give for their own status enums."""
        parent = cls(
            id=id,
            organization_id=organization_id,
            user_id=user_id,
            full_name=full_name,
            phone=phone,
            status=ParentStatus.ACTIVE,
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
        clock: Clock,
        actor_id: str | None = None,
    ) -> None:
        """Idempotent: a call that changes neither field is a no-op, the same "no event for no
        real change" precedent `Student.update_details` already establishes."""
        _validate_parent_full_name(full_name)
        if full_name == self.full_name and phone == self.phone:
            return
        self.full_name = full_name
        self.phone = phone
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
        self._record(
            transport_ops_events.parent_disabled(
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
    ) -> None:
        super().__init__()
        _validate_license_no(license_no)
        self.id = id
        self.organization_id = organization_id
        self.user_id = user_id
        self.license_no = license_no
        self.status = status

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
        clock: Clock,
        actor_id: str | None = None,
    ) -> "Driver":
        """Factory for a newly-registered driver profile. No `pending`/`invited` status exists
        in the (undocumented-values) status enum — see `value_objects.py`'s `DriverStatus`
        docstring — so a registered driver starts `active`, the same reasoning `Parent.register`
        gives for its own status enum."""
        driver = cls(
            id=id,
            organization_id=organization_id,
            user_id=user_id,
            license_no=license_no,
            status=DriverStatus.ACTIVE,
        )
        driver._record(
            transport_ops_events.driver_registered(
                driver_id=str(id),
                organization_id=str(organization_id),
                user_id=str(user_id),
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
        stops: list[Stop] | None = None,
    ) -> None:
        super().__init__()
        _validate_route_name(name)
        self.id = id
        self.organization_id = organization_id
        self.name = name
        self.status = status
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
        route = cls(
            id=id,
            organization_id=organization_id,
            name=name,
            status=RouteStatus.ACTIVE,
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
