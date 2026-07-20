"""Repository interfaces for the `fleet_device` module (Backend LLD §5.1/§7.1/§7.2).
Framework-free — no SQLAlchemy/FastAPI/Pydantic; interfaces only, implemented in
`infra/repositories.py` in a later phase.

Deliberately **not** extending `core.db.repository`'s `Repository`/`TenantScopedRepository`,
for the same reason `iam.domain.repositories` and `organization.domain.repositories` don't:
that module co-locates a SQLAlchemy-dependent concrete class in the same file, so importing
anything from it would force this domain layer's import graph to require SQLAlchemy
(forbidden by LLD §5.3 / `.claude/rules/backend.md` #2). Tenant scoping is injected
automatically at the infra layer (`.claude/rules/backend.md` #4) — no method here takes an
`organization_id` filter parameter.

`DeviceAssignmentRepository`'s `active_for_device`/`active_for_vehicle` are verbatim from the
LLD §7.2 contract skeleton — they back the application-layer guard for the "one active
binding per device & per vehicle" invariant (LLD §5.2; Database Design §5.4).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.modules.fleet_device.domain.entities import (
    Device,
    DeviceAssignment,
    Vehicle,
)
from raad.modules.fleet_device.domain.value_objects import (
    AssignmentId,
    DeviceId,
    TerminalId,
    VehicleId,
)


class VehicleRepository(ABC):
    @abstractmethod
    async def get(self, vehicle_id: VehicleId) -> Vehicle | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_plate_no(self, plate_no: str) -> Vehicle | None:
        """Backs the per-tenant plate uniqueness pre-check (Database Design §5.1:
        `ux_vehicles__org_plate (organization_id, plate_no)`); tenant scoping is implicit
        (`.claude/rules/backend.md` #4), so the lookup is within the active tenant."""
        raise NotImplementedError

    @abstractmethod
    def add(self, vehicle: Vehicle) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository
        (LLD §7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Vehicle]:
        """Backs `GET /vehicles` (API Contracts §4.2) — Backend Stabilization phase addition.
        Previously deferred (`api/routers.py`'s own module docstring: "no listing use-case...
        needs `effective_org_scope` — still pending") specifically because `ScopeResolver`
        didn't exist yet; ADR-0005 resolves that blocker. Not itself scope-filtered yet — the
        same system-wide, already-flagged gap every other `list_all()` in this codebase
        carries."""
        raise NotImplementedError


class DeviceRepository(ABC):
    @abstractmethod
    async def get(self, device_id: DeviceId) -> Device | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_terminal_id(self, terminal_id: TerminalId) -> Device | None:
        """Backs the global terminal-id uniqueness pre-check (Database Design §5.2:
        `terminal_id` is a global `UX` — "JT808 terminal/SIM identifier (global unique)").
        """
        raise NotImplementedError

    @abstractmethod
    def add(self, device: Device) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Device]:
        """Backs `GET /devices` (API Contracts §4.2) — same Backend Stabilization phase
        addition and same unscoped-`list_all` posture as `VehicleRepository.list_all` above."""
        raise NotImplementedError


class DeviceAssignmentRepository(ABC):
    @abstractmethod
    async def get(self, assignment_id: AssignmentId) -> DeviceAssignment | None:
        raise NotImplementedError

    @abstractmethod
    async def active_for_device(self, device_id: DeviceId) -> DeviceAssignment | None:
        """LLD §7.2 verbatim — the currently active (`unassigned_at IS NULL`) binding for a
        device, or None."""
        raise NotImplementedError

    @abstractmethod
    async def active_for_vehicle(
        self, vehicle_id: VehicleId
    ) -> DeviceAssignment | None:
        """LLD §7.2 verbatim — the currently active binding for a vehicle, or None. Backs
        the one-active-device-per-vehicle guard (safety-critical invariant,
        `.claude/rules/testing.md` #3)."""
        raise NotImplementedError

    @abstractmethod
    def add(self, assignment: DeviceAssignment) -> None:
        raise NotImplementedError
