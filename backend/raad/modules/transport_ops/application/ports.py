"""Outbound ports the `transport_ops` application layer depends on (Backend LLD §4.2).
`UnitOfWork` is the existing core abstraction (`core.db.unit_of_work`), extended here with
`transport_ops`'s own repositories — exactly the pattern that module's own docstring
anticipates, and exactly what `organization.application.ports.OrganizationUnitOfWork` already
does. `Clock`/`IdGenerator` are likewise existing core ports, used as constructor dependencies
by the application service (`services.py`) — never redefined here.

`core.db.unit_of_work` co-locates the abstract `UnitOfWork` with its concrete
`SqlAlchemyUnitOfWork` implementation in the same file, so importing the interface transitively
requires SQLAlchemy to be installed. Accepted deliberately here for the same reason
`organization.application.ports` accepts it: SQLAlchemy is an already-approved project
dependency (Phase 4.4), this application layer's own code never references it directly, and the
LLD's own `application/ports.py` contract skeleton (§4.2) explicitly expects `interface
UnitOfWork` to be referenced from exactly this file. This is *not* the forbidden "implement
SQLAlchemy" this phase's own scope excludes — no SQLAlchemy type, session, or query appears
anywhere in this module's `application/` code.

No bespoke read-only port (the `tracking.application.ports.LatestPositionPort` shape) is needed
this phase — every Student read (`GetStudentByIdQuery`/`ListStudentsQuery`) is fully served by
`StudentRepository` through the `TransportOpsUnitOfWork` below; there is no non-repository-backed
data source like `tracking`'s Redis latest-position cache for `Student`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from raad.core.db.unit_of_work import UnitOfWork
from raad.core.tenancy.principal import Principal, Role
from raad.modules.transport_ops.domain.repositories import (
    IncidentNoteRepository,
    IncidentRepository,
    DriverRepository,
    ParentRepository,
    RouteRepository,
    StudentAssignmentRepository,
    StudentParentRepository,
    StudentRepository,
    OperatingClosureRepository,
    RouteTimetableEntryRepository,
    StaffCoverRepository,
    StaffUnavailabilityRepository,
    StaffDocumentRepository,
    StaffDocumentTypeRepository,
    TransportStaffRepository,
    TransportStaffRoleRepository,
    TripRepository,
    VehicleStaffAssignmentRepository,
)


class TransportOpsUnitOfWork(UnitOfWork):
    """Bundles this module's repositories onto one transaction boundary (LLD §8.2 contract
    skeleton style — plain attributes, matching `OrganizationUnitOfWork`'s own style, which
    already bundles two repositories — `organizations`/`regions` — onto one UoW; `Parent`
    (Phase 10.6) joins `Student` here the same way, not a second UnitOfWork; `student_parents`
    (Phase 10.7) joins the same way again, a third repository on the one transaction boundary;
    `drivers` (Phase 10.8) joins the same way again, a fourth; `routes` (Phase 11) joins the
    same way again, a fifth — no separate `stops` repository, `Stop` being a `Route`-owned
    child entity (`domain/repositories.py`'s Phase 11 addition); `trips` (Phase 12) joins the
    same way again, a sixth; `student_assignments` (Phase 13) joins the same way again, a
    seventh.
    The concrete implementation is `infra.repositories.SqlAlchemyTransportOpsUnitOfWork`.
    """

    students: StudentRepository
    parents: ParentRepository
    student_parents: StudentParentRepository
    drivers: DriverRepository
    routes: RouteRepository
    trips: TripRepository
    student_assignments: StudentAssignmentRepository
    #: ADR-0049/0050/0051: bus crew people, their titles, assignments and documents.
    staff_roles: TransportStaffRoleRepository
    staff: TransportStaffRepository
    staff_assignments: VehicleStaffAssignmentRepository
    staff_document_types: StaffDocumentTypeRepository
    staff_documents: StaffDocumentRepository
    #: ADR-0052/0053: the weekly plan, closed days, unavailability and cover.
    timetable: RouteTimetableEntryRepository
    closures: OperatingClosureRepository
    unavailability: StaffUnavailabilityRepository
    covers: StaffCoverRepository
    #: ADR-0056: the incident log and its timeline.
    incidents: IncidentRepository
    incident_notes: IncidentNoteRepository


class UserProvisioningPort(ABC):
    """ADR-0003 (accepted): creates the login-capable `iam.User` a `Parent`/`Driver`
    registration depends on (Database Design §6.3/§6.1 both make `user_id` a required,
    already-valid input) — via `iam`'s own public application-service surface, never its
    repository/ORM layer. Owned by this module (the consuming module), satisfied by
    `infra.adapters.IamUserProvisioningAdapter`, matching every other outbound port in this
    codebase's own "interface defined by the consumer, implemented by the provider" shape.

    Returns a `(user_id, temporary_password)` pair — the plaintext temporary password is
    surfaced to the caller (an Org Admin registering a Parent/Driver) exactly once, in the same
    response, for hand-off; it is never persisted or retrievable again afterward."""

    @abstractmethod
    async def create_user_with_temporary_password(
        self,
        *,
        organization_id: str,
        role: Role,
        email: str | None,
        phone: str | None,
        full_name: str,
        actor: Principal,
    ) -> tuple[str, str]:
        raise NotImplementedError



class VehicleDirectoryPort(ABC):
    """ADR-0050 §1: which organization owns a bus. Buses belong to `fleet_device`, which this
    module may not read directly (`.claude/rules/backend.md` #3), so crew assignment asks
    through this port; the adapter lives in the composition root (`core/di/`)."""

    @abstractmethod
    async def organization_of_vehicle(self, vehicle_id: str) -> str | None:
        """The owning organization's id, or `None` when no such bus exists."""
        raise NotImplementedError


@dataclass(frozen=True)
class VehicleSummary:
    """What a parent or a driver may know about a bus: its plate and its label."""

    id: str
    plate_no: str
    label: str | None


class VehicleSummaryPort(ABC):
    """ADR-0061: plate and label for buses named on trips. Same reason as `VehicleDirectoryPort`:
    buses belong to `fleet_device`; the adapter lives in the composition root."""

    @abstractmethod
    async def summaries(
        self, vehicle_ids: list[str], *, organization_id: str
    ) -> dict[str, VehicleSummary]:
        """Keyed by id. A bus that does not exist or belongs to another organization is absent."""
        raise NotImplementedError
