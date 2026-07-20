"""SQLAlchemy repository implementations for `fleet_device` (Backend LLD §7, §8; Database
Design §5). Compose `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM ↔ domain conversion goes through `mappers.py` — repositories never return
an ORM model, only the domain aggregates `modules/fleet_device/domain/repositories.py`
declares (§7.1's "aggregate-in/aggregate-out" rule).

**The identity-map problem this file solves** — identical to `iam`/`organization`'s own
docstrings: because `get()`/`get_by_*()`/`active_for_*()` return plain domain objects (not the
tracked ORM rows), a handler that mutates one in place (`device.retire(...)`,
`assignment.close(...)`) never touches SQLAlchemy's dirty-tracking. Per the established
pattern, the application layer never re-calls `add()` after such a mutation, so each
repository keeps a `{id: (domain_object, orm_row)}` map of everything it has returned or
added, and `flush_tracked_changes()` re-projects every tracked domain object onto its row via
the mapper immediately before commit — called by `SqlAlchemyFleetDeviceUnitOfWork.commit()`,
below.

**Tenant-scoping note (pre-existing gap, consistent with every module so far):** repository
queries do not yet apply the automatic tenant filter — `core.tenancy`'s `ScopeResolver` is
still pending (see `interfaces/http/deps.get_scope`). For `get_by_plate_no` this means the
per-tenant uniqueness pre-check (`ux_vehicles__org_plate` is composite) currently checks
plate uniqueness *globally*: a same-plate vehicle in another tenant would be rejected at the
validator even though the DB constraint would allow it — a conservative false-conflict, never
data corruption. When tenant scoping lands (one place, per Backend LLD §7.3), this lookup
inherits it automatically.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.domain.entities import (
    Device,
    DeviceAssignment,
    Vehicle,
)
from raad.modules.fleet_device.domain.repositories import (
    DeviceAssignmentRepository,
    DeviceRepository,
    VehicleRepository,
)
from raad.modules.fleet_device.domain.value_objects import (
    AssignmentId,
    DeviceId,
    TerminalId,
    VehicleId,
)
from raad.modules.fleet_device.infra.mappers import (
    assignment_to_model,
    device_to_model,
    model_to_assignment,
    model_to_device,
    model_to_vehicle,
    vehicle_to_model,
)
from raad.modules.fleet_device.infra.models import (
    DeviceAssignmentModel,
    DeviceModel,
    VehicleModel,
)


class SqlAlchemyVehicleRepository(
    SqlAlchemyRepositoryBase[VehicleModel], VehicleRepository
):
    model = VehicleModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Vehicle, VehicleModel]] = {}

    async def get(self, vehicle_id: VehicleId) -> Vehicle | None:
        row = await self.get_by_id(str(vehicle_id))
        return self._track(row)

    async def get_by_plate_no(self, plate_no: str) -> Vehicle | None:
        statement = select(VehicleModel).where(
            VehicleModel.plate_no == plate_no, VehicleModel.deleted_at.is_(None)
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, vehicle: Vehicle) -> None:
        model = vehicle_to_model(vehicle)
        super().add(model)
        self._tracked[str(vehicle.id)] = (vehicle, model)

    async def list_all(self) -> list[Vehicle]:
        """Unrestricted `TenantRegionScope` — not yet scope-filtered, the same system-wide,
        already-flagged gap every other module's own `list_all()` carries."""
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [self._track(row) for row in rows]  # type: ignore[misc]

    def flush_tracked_changes(self) -> None:
        for vehicle, model in self._tracked.values():
            vehicle_to_model(vehicle, existing=model)

    def _track(self, row: VehicleModel | None) -> Vehicle | None:
        if row is None:
            return None
        vehicle = model_to_vehicle(row)
        self._tracked[row.id] = (vehicle, row)
        return vehicle


class SqlAlchemyDeviceRepository(
    SqlAlchemyRepositoryBase[DeviceModel], DeviceRepository
):
    """Camera child rows ride the `DeviceModel.cameras` relationship (selectin-eager), so a
    tracked `Device` re-projection (`flush_tracked_changes` → `device_to_model`) also syncs
    camera rows — new cameras registered on the aggregate become new `CameraModel` rows via
    the relationship's cascade."""

    model = DeviceModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Device, DeviceModel]] = {}

    async def get(self, device_id: DeviceId) -> Device | None:
        row = await self.get_by_id(str(device_id))
        return self._track(row)

    async def get_by_terminal_id(self, terminal_id: TerminalId) -> Device | None:
        statement = select(DeviceModel).where(
            DeviceModel.terminal_id == str(terminal_id),
            DeviceModel.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, device: Device) -> None:
        model = device_to_model(device)
        super().add(model)
        self._tracked[str(device.id)] = (device, model)

    async def list_all(self) -> list[Device]:
        """Unrestricted `TenantRegionScope` — same posture as `SqlAlchemyVehicleRepository.
        list_all` above."""
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [self._track(row) for row in rows]  # type: ignore[misc]

    def flush_tracked_changes(self) -> None:
        for device, model in self._tracked.values():
            device_to_model(device, existing=model)

    def _track(self, row: DeviceModel | None) -> Device | None:
        if row is None:
            return None
        device = model_to_device(row)
        self._tracked[row.id] = (device, row)
        return device


class SqlAlchemyDeviceAssignmentRepository(
    SqlAlchemyRepositoryBase[DeviceAssignmentModel], DeviceAssignmentRepository
):
    """`device_assignments` has no `deleted_at` (Database Design §5.4 — history rows are
    never soft-deleted), so no soft-delete filter appears here; `SqlAlchemyRepositoryBase.
    get_by_id` already skips that filter for models without the column."""

    model = DeviceAssignmentModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[DeviceAssignment, DeviceAssignmentModel]] = {}

    async def get(self, assignment_id: AssignmentId) -> DeviceAssignment | None:
        row = await self.get_by_id(str(assignment_id))
        return self._track(row)

    async def active_for_device(self, device_id: DeviceId) -> DeviceAssignment | None:
        statement = select(DeviceAssignmentModel).where(
            DeviceAssignmentModel.device_id == str(device_id),
            DeviceAssignmentModel.unassigned_at.is_(None),
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    async def active_for_vehicle(
        self, vehicle_id: VehicleId
    ) -> DeviceAssignment | None:
        statement = select(DeviceAssignmentModel).where(
            DeviceAssignmentModel.vehicle_id == str(vehicle_id),
            DeviceAssignmentModel.unassigned_at.is_(None),
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, assignment: DeviceAssignment) -> None:
        model = assignment_to_model(assignment)
        super().add(model)
        self._tracked[str(assignment.id)] = (assignment, model)

    def flush_tracked_changes(self) -> None:
        for assignment, model in self._tracked.values():
            assignment_to_model(assignment, existing=model)

    def _track(self, row: DeviceAssignmentModel | None) -> DeviceAssignment | None:
        if row is None:
            return None
        assignment = model_to_assignment(row)
        self._tracked[row.id] = (assignment, row)
        return assignment


class SqlAlchemyFleetDeviceUnitOfWork(SqlAlchemyUnitOfWork, FleetDeviceUnitOfWork):
    """Concrete `FleetDeviceUnitOfWork` (Backend LLD §8.2/§6.2). Constructs `fleet_device`'s
    three repositories once the session is open, and re-syncs every tracked aggregate's
    in-place mutations onto its ORM row (`flush_tracked_changes`, above) immediately before
    delegating to `SqlAlchemyUnitOfWork.commit()` — which still owns the actual outbox-write
    + session-commit behavior, preserved exactly (§8.3), via `super().commit()`. Identical
    shape to `SqlAlchemyIamUnitOfWork`/`SqlAlchemyOrganizationUnitOfWork`.
    """

    vehicles: SqlAlchemyVehicleRepository
    devices: SqlAlchemyDeviceRepository
    device_assignments: SqlAlchemyDeviceAssignmentRepository

    async def __aenter__(self) -> "SqlAlchemyFleetDeviceUnitOfWork":
        await super().__aenter__()
        self.vehicles = SqlAlchemyVehicleRepository(self.session)
        self.devices = SqlAlchemyDeviceRepository(self.session)
        self.device_assignments = SqlAlchemyDeviceAssignmentRepository(self.session)
        return self

    async def commit(self) -> None:
        self.vehicles.flush_tracked_changes()
        self.devices.flush_tracked_changes()
        self.device_assignments.flush_tracked_changes()
        await super().commit()
