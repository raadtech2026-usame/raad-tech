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
"""

from __future__ import annotations

from raad.core.errors.exceptions import DomainError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain import events as transport_ops_events
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    ParentId,
    ParentStatus,
    PhoneNumber,
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
