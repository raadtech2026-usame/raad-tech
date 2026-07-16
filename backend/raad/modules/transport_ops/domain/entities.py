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
"""

from __future__ import annotations

from raad.core.errors.exceptions import DomainError
from raad.core.events.base import DomainEvent
from raad.core.time.clock import Clock
from raad.modules.transport_ops.domain import events as transport_ops_events
from raad.modules.transport_ops.domain.value_objects import (
    OrganizationId,
    StudentId,
    StudentStatus,
)

_FULL_NAME_MAX_LENGTH = 200  # Database Design §6.2: full_name VARCHAR(200)
_EXTERNAL_REF_MAX_LENGTH = 64  # Database Design §6.2: external_ref VARCHAR(64)


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
        if not full_name:
            raise DomainError("Student full_name must not be empty")
        if len(full_name) > _FULL_NAME_MAX_LENGTH:
            raise DomainError(
                f"Student full_name must be at most {_FULL_NAME_MAX_LENGTH} characters: "
                f"{len(full_name)}"
            )
        if external_ref is not None and len(external_ref) > _EXTERNAL_REF_MAX_LENGTH:
            raise DomainError(
                f"Student external_ref must be at most {_EXTERNAL_REF_MAX_LENGTH} "
                f"characters: {len(external_ref)}"
            )
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
