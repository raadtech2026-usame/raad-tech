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

**Tenant-scoping (ADR-0021):** every repository below is constructed with the caller's resolved
`TenantRegionScope` (`SqlAlchemyFleetDeviceUnitOfWork.__aenter__`, set from `api/deps.
get_fleet_device_uow`'s `Depends(get_scope)`) — `get_by_id`/`list_page`/`list_all` all apply it
automatically via the base class. `get_by_plate_no` is a separate, explicit `AsyncSession`
query (not `get_by_id`) and is deliberately left untouched by this ADR: it already queries
`plate_no` globally, unscoped, and `ensure_plate_no_available`'s own error message ("already
exists in this organization") suggests the *intent* was a per-org uniqueness check matching
`ux_vehicles__org_plate`'s actual composite (org, plate) constraint — i.e. this looks like a
pre-existing, separate correctness gap (an overly-conservative false-conflict across
organizations, never a data leak) worth flagging, not silently fixed here: ADR-0021 is about
one org reading/writing another's data, not about this validator's over-strict rejection
behavior, and changing it would be a validation-behavior change outside that scope.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import FilterField, SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.domain.entities import (
    Device,
    DeviceAssignment,
    DeviceInventoryItem,
    Vehicle,
)
from raad.modules.fleet_device.domain.repositories import (
    DeviceAssignmentRepository,
    DeviceInventoryRepository,
    DeviceRepository,
    VehicleRepository,
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
from raad.modules.fleet_device.infra.mappers import (
    assignment_to_model,
    device_to_model,
    inventory_item_to_model,
    model_to_assignment,
    model_to_device,
    model_to_inventory_item,
    model_to_vehicle,
    vehicle_to_model,
)
from raad.modules.fleet_device.infra.models import (
    DeviceAssignmentModel,
    DeviceInventoryModel,
    DeviceModel,
    VehicleModel,
)


class SqlAlchemyVehicleRepository(
    SqlAlchemyRepositoryBase[VehicleModel], VehicleRepository
):
    model = VehicleModel

    #: Whitelist for `GET /vehicles` (§8) — limited to columns already on `VehicleResponse`.
    filterable_fields = {
        "organization_id": FilterField(column="organization_id"),
        "status": FilterField(column="status"),
    }
    sortable_fields = {
        "plate_no": "plate_no",
        "status": "status",
        "created_at": "created_at",
        "updated_at": "updated_at",
    }
    searchable_fields = ("plate_no", "label")

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
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
        """ADR-0021: scope-filtered via `self._scope` (bound at construction by
        `SqlAlchemyFleetDeviceUnitOfWork.__aenter__`)."""
        rows = await self.list_scoped()
        return [self._track(row) for row in rows]  # type: ignore[misc]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Vehicle]:
        """ADR-0021: scope-filtered via `self._scope`, same posture as `list_all` above."""
        raw_page = await super().list_page(
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

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

    #: Whitelist for `GET /devices` (§8) — limited to columns already on `DeviceResponse`.
    #: `sim_msisdn` is deliberately excluded — PII, masked in logs (`application/queries.py`'s
    #: own docstring) — never filterable/sortable/searchable.
    filterable_fields = {
        "organization_id": FilterField(column="organization_id"),
        "lifecycle_state": FilterField(column="lifecycle_state"),
    }
    sortable_fields = {
        "terminal_id": "terminal_id",
        "lifecycle_state": "lifecycle_state",
        "created_at": "created_at",
        "updated_at": "updated_at",
    }
    searchable_fields = ("terminal_id", "model", "vendor")

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
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

    async def get_by_imei(self, imei: Imei) -> Device | None:
        statement = select(DeviceModel).where(
            DeviceModel.imei == str(imei), DeviceModel.deleted_at.is_(None)
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    async def get_by_iccid(self, iccid: Iccid) -> Device | None:
        statement = select(DeviceModel).where(
            DeviceModel.iccid == str(iccid), DeviceModel.deleted_at.is_(None)
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    async def get_by_serial_number(self, serial_number: SerialNumber) -> Device | None:
        statement = select(DeviceModel).where(
            DeviceModel.serial_number == str(serial_number),
            DeviceModel.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, device: Device) -> None:
        model = device_to_model(device)
        super().add(model)
        self._tracked[str(device.id)] = (device, model)

    async def list_all(self) -> list[Device]:
        """ADR-0021: scope-filtered via `self._scope`, same posture as
        `SqlAlchemyVehicleRepository.list_all` above."""
        rows = await self.list_scoped()
        return [self._track(row) for row in rows]  # type: ignore[misc]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Device]:
        """ADR-0021: scope-filtered via `self._scope`, same posture as `list_all` above."""
        raw_page = await super().list_page(
            page_request,
            sort=sort,
            filters=filters,
            search=search,
        )
        return OffsetPage(
            data=[self._track(row) for row in raw_page.data],  # type: ignore[misc]
            total=raw_page.total,
            page=raw_page.page,
            page_size=raw_page.page_size,
        )

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

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
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


class SqlAlchemyDeviceInventoryRepository(
    SqlAlchemyRepositoryBase[DeviceInventoryModel], DeviceInventoryRepository
):
    """ADR-0018 §1. `DeviceInventoryModel` has no `organization_id` column, so
    `SqlAlchemyRepositoryBase._apply_scope` naturally falls through to unrestricted for every
    caller regardless of `self._scope` — the platform-scoped posture the ADR wants, with no
    override needed here. No `filterable_fields`/`sortable_fields`/`searchable_fields` and no
    `list_page`/`list_all` override — no route needs list/filter/sort this phase."""

    model = DeviceInventoryModel

    def __init__(
        self, session: AsyncSession, *, scope: TenantRegionScope | None = None
    ) -> None:
        super().__init__(session, scope=scope)
        self._tracked: dict[str, tuple[DeviceInventoryItem, DeviceInventoryModel]] = {}

    async def get(self, inventory_item_id: InventoryItemId) -> DeviceInventoryItem | None:
        row = await self.get_by_id(str(inventory_item_id))
        return self._track(row)

    async def get_by_serial_number(
        self, serial_number: SerialNumber
    ) -> DeviceInventoryItem | None:
        statement = select(DeviceInventoryModel).where(
            DeviceInventoryModel.serial_number == str(serial_number),
            DeviceInventoryModel.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    async def get_by_imei(self, imei: Imei) -> DeviceInventoryItem | None:
        statement = select(DeviceInventoryModel).where(
            DeviceInventoryModel.imei == str(imei), DeviceInventoryModel.deleted_at.is_(None)
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    async def get_by_iccid(self, iccid: Iccid) -> DeviceInventoryItem | None:
        statement = select(DeviceInventoryModel).where(
            DeviceInventoryModel.iccid == str(iccid),
            DeviceInventoryModel.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, item: DeviceInventoryItem) -> None:
        model = inventory_item_to_model(item)
        super().add(model)
        self._tracked[str(item.id)] = (item, model)

    def flush_tracked_changes(self) -> None:
        for item, model in self._tracked.values():
            inventory_item_to_model(item, existing=model)

    def _track(self, row: DeviceInventoryModel | None) -> DeviceInventoryItem | None:
        if row is None:
            return None
        item = model_to_inventory_item(row)
        self._tracked[row.id] = (item, row)
        return item


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
    device_inventory: SqlAlchemyDeviceInventoryRepository

    async def __aenter__(self) -> "SqlAlchemyFleetDeviceUnitOfWork":
        await super().__aenter__()
        self.vehicles = SqlAlchemyVehicleRepository(self.session, scope=self.scope)
        self.devices = SqlAlchemyDeviceRepository(self.session, scope=self.scope)
        self.device_assignments = SqlAlchemyDeviceAssignmentRepository(
            self.session, scope=self.scope
        )
        self.device_inventory = SqlAlchemyDeviceInventoryRepository(
            self.session, scope=self.scope
        )
        return self

    async def commit(self) -> None:
        self.vehicles.flush_tracked_changes()
        self.devices.flush_tracked_changes()
        self.device_assignments.flush_tracked_changes()
        self.device_inventory.flush_tracked_changes()
        await super().commit()
