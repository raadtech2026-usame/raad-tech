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
from dataclasses import dataclass

from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.modules.fleet_device.domain.entities import (
    Device,
    DeviceAssignment,
    DeviceInventoryItem,
    Vehicle,
)
from raad.modules.fleet_device.domain.value_objects import (
    AssignmentId,
    DeviceId,
    Iccid,
    Imei,
    InventoryItemId,
    SerialNumber,
    TerminalId,
    VehicleId,
)


class VehicleRepository(ABC):
    @abstractmethod
    async def get(self, vehicle_id: VehicleId) -> Vehicle | None:
        raise NotImplementedError

    @abstractmethod
    async def list_by_ids(self, vehicle_ids: list[VehicleId]) -> list[Vehicle]:
        """ADR-0031 (Fleet Overview read model) — a single scoped `WHERE id IN (...)` lookup
        for a caller that already knows exactly which vehicles it needs (e.g. the online set
        `DeviceRepository.list_online_with_active_assignment` resolved), never a fan-out of one
        `get()` call per id. Same `_apply_scope` tenant/region enforcement as every other
        `list_*` method (ADR-0021) — an out-of-scope id in the input list is silently absent
        from the result, not an error, matching this codebase's own cross-tenant-probing-
        avoidance posture."""
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

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Vehicle]:
        """Backs `GET /vehicles`'s paginated/filtered/sorted contract (API Contracts §7/§8)."""
        raise NotImplementedError

    @abstractmethod
    async def count_total(self) -> int:
        """ADR-0020: "Total Vehicles" KPI. Scoped exactly like `list_page`/`list_all` (the
        caller's resolved `TenantRegionScope` — unrestricted for Founder, region-limited for
        Regional Manager, `security.md` #3's "region scoping is a second filter... for RAAD
        staff") — a platform view still shouldn't let a Regional Manager's own request see
        counts outside their assigned scope, matching `admin.audit.read`'s identical existing
        posture (`AuditEntryRepository.list_page` scopes the same way)."""
        raise NotImplementedError


@dataclass(frozen=True)
class OnlineDeviceAssignment:
    """A pure read-model projection (ADR-0031, Fleet Overview) — not a domain entity, the same
    "thin dedicated read shape" precedent `DeviceStatsDTO`/`VehicleStatsDTO` already establish
    for a KPI-only query that has no business behavior of its own. Exactly the three columns
    `tracking`'s new fleet-overview composition needs: which device, its wire identity, and
    which vehicle it's currently bound to."""

    device_id: str
    terminal_id: str
    vehicle_id: str


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
    async def get_by_imei(self, imei: Imei) -> Device | None:
        """Backs the global IMEI uniqueness pre-check (Device Domain Overhaul architecture
        review — `ux_devices__imei`), mirroring `get_by_terminal_id`'s identical shape."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_iccid(self, iccid: Iccid) -> Device | None:
        """Backs the global ICCID uniqueness pre-check (`ux_devices__iccid`)."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_serial_number(self, serial_number: SerialNumber) -> Device | None:
        """Backs the global serial-number uniqueness pre-check (`ux_devices__serial_number`)."""
        raise NotImplementedError

    @abstractmethod
    def add(self, device: Device) -> None:
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[Device]:
        """Backs `GET /devices` (API Contracts §4.2) — same Backend Stabilization phase
        addition and same unscoped-`list_all` posture as `VehicleRepository.list_all` above."""
        raise NotImplementedError

    @abstractmethod
    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Device]:
        """Backs `GET /devices`'s paginated/filtered/sorted contract (API Contracts §7/§8)."""
        raise NotImplementedError

    @abstractmethod
    async def count_total(self) -> int:
        """ADR-0020: "Total Devices" KPI — same scoping posture as `VehicleRepository.
        count_total`."""
        raise NotImplementedError

    @abstractmethod
    async def count_online(self) -> int:
        """ADR-0020 §3: "Online Devices" KPI, backed by the new `is_online` column
        (`DeviceConnectivityProcessor`, `events/subscribers.py`)."""
        raise NotImplementedError

    @abstractmethod
    async def list_online_with_active_assignment(self) -> list[OnlineDeviceAssignment]:
        """ADR-0031 (Fleet Overview read model) — the one query the All Vehicles map mode
        actually needs: every online device that also has an active vehicle binding, in one
        round trip (an online device with no vehicle assignment has nothing to show on a
        vehicle map, so it's excluded here rather than returned for the caller to filter out).
        Joins this module's own `devices`/`device_assignments` tables only — never a
        cross-module read (`.claude/rules/backend.md` #3) — and is scope-filtered exactly like
        every other `list_*` method (ADR-0021). Deliberately returns the thin
        `OnlineDeviceAssignment` projection, not reconstructed `Device` aggregates: this is a
        read-model query with no business behavior to invoke, the same reasoning
        `count_total`/`count_online` above already apply."""
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


class DeviceInventoryRepository(ABC):
    """ADR-0018 §1. No `list_all`/`list_page` — no approved route needs one this phase
    (ADR-0018 §2 documents only the two `POST` routes); adding one now would be surface with
    no caller, the same "don't build ahead of an approved contract" discipline this module's
    own router docstring already states for camera registration."""

    @abstractmethod
    async def get(self, inventory_item_id: InventoryItemId) -> DeviceInventoryItem | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_serial_number(
        self, serial_number: SerialNumber
    ) -> DeviceInventoryItem | None:
        """Backs the global serial-number uniqueness pre-check within `device_inventory`'s own
        table (`ux_device_inventory__serial_number`)."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_imei(self, imei: Imei) -> DeviceInventoryItem | None:
        """Backs the global IMEI uniqueness pre-check within `device_inventory`'s own table."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_iccid(self, iccid: Iccid) -> DeviceInventoryItem | None:
        """Backs the global ICCID uniqueness pre-check within `device_inventory`'s own table."""
        raise NotImplementedError

    @abstractmethod
    def add(self, item: DeviceInventoryItem) -> None:
        raise NotImplementedError
