"""Fleet & Device application services (Backend LLD §4.1/§4.3). Thin, orchestration-only
handlers — business rules stay inside the `Vehicle`/`Device`/`DeviceAssignment` aggregates
(`modules/fleet_device/domain`); these services only: resolve/validate pre-conditions, load
aggregates via the repositories bound to `FleetDeviceUnitOfWork`, invoke domain behavior,
record the resulting `DomainEvent`s, commit, and return a DTO — the exact skeleton the LLD's
§4.3 "transaction & event ordering" steps describe, identical to `iam`/`organization`'s
services.

Split into two services by natural API grouping (API Contracts rule #2: `/vehicles` +
`/devices`, both routed to this module) — the same reasoning `organization.application.
services` gives. Assignment use-cases live on `DeviceApplicationService`, matching the LLD
§4.2 skeleton's `DeviceAppService: handle(AssignDeviceToVehicle) / handle(ReassignDevice)`.

**`ChangeVehicleDriver` is deliberately not implemented here.** The LLD §4.2 skeleton lists it
under `DeviceAppService` with the note "NEVER touches device binding (Phase-2 §19)" — but
Phase 2 §19.1 states driver assignment "lives entirely in Transport Operations and is
expressed through trips", and this module owns no driver/trip aggregate to change. The
skeleton line illustrates the decoupling principle (a driver change is a no-op *for this
module*); the actual use-case belongs to `transport_ops` (a later phase). Implementing it
here would require a cross-module reach into trips — forbidden — so it is recorded rather
than built.
"""

from __future__ import annotations

from dataclasses import replace

from raad.core.errors.exceptions import NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import OffsetPage
from raad.core.time.clock import Clock
from raad.core.logging.setup import get_logger
from raad.modules.fleet_device.application.commands import (
    ActivateDeviceCommand,
    ActivateVehicleCommand,
    AllocateDeviceInventoryItemCommand,
    AssignDeviceToVehicleCommand,
    DeactivateVehicleCommand,
    MarkVehicleUnderMaintenanceCommand,
    ReactivateDeviceCommand,
    ReassignDeviceCommand,
    ReceiveDeviceInventoryItemCommand,
    RecordDeviceSeenCommand,
    RegisterCameraCommand,
    RegisterDeviceCommand,
    RegisterVehicleCommand,
    RetireDeviceCommand,
    SuspendDeviceCommand,
    UnassignDeviceCommand,
)
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.queries import (
    DeviceAssignmentDTO,
    DeviceDTO,
    DeviceInventoryItemDTO,
    DeviceStatsDTO,
    GetDeviceByIdQuery,
    GetVehicleByIdQuery,
    ListDevicesQuery,
    ListVehiclesQuery,
    TrackingStatusDTO,
    VehicleDTO,
    VehicleStatsDTO,
    assignment_to_dto,
    device_to_dto,
    inventory_item_to_dto,
    vehicle_to_dto,
)
from raad.modules.fleet_device.application.validators import (
    ensure_device_has_no_active_assignment,
    ensure_iccid_available,
    ensure_imei_available,
    ensure_inventory_iccid_available,
    ensure_inventory_imei_available,
    ensure_inventory_item_allocatable,
    ensure_inventory_serial_number_available,
    ensure_plate_no_available,
    ensure_same_organization,
    ensure_serial_number_available,
    ensure_terminal_id_available,
    ensure_vehicle_exists,
    ensure_vehicle_has_no_active_device,
)
from raad.modules.fleet_device.domain import events as fleet_events
from raad.modules.fleet_device.domain.entities import (
    Device,
    DeviceAssignment,
    DeviceInventoryItem,
    Vehicle,
)
from raad.modules.fleet_device.domain.value_objects import (
    AssignmentId,
    CameraId,
    DeviceId,
    Iccid,
    Imei,
    InventoryItemId,
    Msisdn,
    OrganizationId,
    SerialNumber,
    TerminalId,
    VehicleId,
)

logger = get_logger("raad.fleet_device.application")


class VehicleApplicationService:
    """Vehicle lifecycle use-cases: register, activate, deactivate, mark-under-maintenance,
    and the `GetVehicleByIdQuery` read path."""

    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    async def register_vehicle(
        self, command: RegisterVehicleCommand, *, uow: FleetDeviceUnitOfWork
    ) -> VehicleDTO:
        async with uow:
            await ensure_plate_no_available(uow, command.plate_no)

            vehicle = Vehicle.register(
                id=VehicleId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                plate_no=command.plate_no,
                label=command.label,
                capacity=command.capacity,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.vehicles.add(vehicle)
            uow.record_events(vehicle.pull_domain_events())
            await uow.commit()
            return vehicle_to_dto(vehicle)

    async def activate_vehicle(
        self, command: ActivateVehicleCommand, *, uow: FleetDeviceUnitOfWork
    ) -> VehicleDTO:
        async with uow:
            vehicle = await self._get_vehicle_or_raise(uow, command.vehicle_id)
            vehicle.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(vehicle.pull_domain_events())
            await uow.commit()
            return vehicle_to_dto(vehicle)

    async def deactivate_vehicle(
        self, command: DeactivateVehicleCommand, *, uow: FleetDeviceUnitOfWork
    ) -> VehicleDTO:
        async with uow:
            vehicle = await self._get_vehicle_or_raise(uow, command.vehicle_id)
            vehicle.deactivate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(vehicle.pull_domain_events())
            await uow.commit()
            return vehicle_to_dto(vehicle)

    async def mark_vehicle_under_maintenance(
        self, command: MarkVehicleUnderMaintenanceCommand, *, uow: FleetDeviceUnitOfWork
    ) -> VehicleDTO:
        async with uow:
            vehicle = await self._get_vehicle_or_raise(uow, command.vehicle_id)
            vehicle.mark_under_maintenance(
                clock=self._clock, actor_id=command.actor.user_id
            )
            uow.record_events(vehicle.pull_domain_events())
            await uow.commit()
            return vehicle_to_dto(vehicle)

    async def get_vehicle_by_id(
        self, query: GetVehicleByIdQuery, *, uow: FleetDeviceUnitOfWork
    ) -> VehicleDTO:
        """The single-record path only — see `TrackingStatusDTO`'s own docstring for why
        `list_vehicles` deliberately leaves `tracking_status` `None` rather than joining it for
        every row of a page (avoids an N+1 device lookup per page). This is the *only* device-
        derived data an Org Admin session can ever reach (Device Domain Overhaul architecture
        review): a same-module read of this module's own `device_assignments`/`devices` tables
        (not a cross-module reach), never exposing `device_id`/`terminal_id`/any hardware
        identifier — only whether *some* device is actively bound and reporting."""
        async with uow:
            vehicle = await self._get_vehicle_or_raise(uow, query.vehicle_id)
            dto = vehicle_to_dto(vehicle)

            assignment = await uow.device_assignments.active_for_vehicle(vehicle.id)
            if assignment is None:
                return dto

            device = await uow.devices.get(assignment.device_id)
            if device is None:
                return dto

            return replace(
                dto,
                tracking_status=TrackingStatusDTO(last_seen_at=device.last_seen_at),
            )

    async def list_vehicles(
        self, query: ListVehiclesQuery, *, uow: FleetDeviceUnitOfWork
    ) -> OffsetPage[VehicleDTO]:
        """Backs `GET /vehicles`'s paginated/filtered/sorted contract (API Contracts §4.2/§7/
        §8) — pagination/filtering/sorting added under the Tier 2 pagination phase, on top of
        the Backend Stabilization phase's original `list_all`-backed addition (see `domain/
        repositories.py`'s `VehicleRepository.list_all` docstring for why that was previously
        deferred and what unblocked it)."""
        async with uow:
            page = await uow.vehicles.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[vehicle_to_dto(v) for v in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    async def get_vehicle_stats(self, *, uow: FleetDeviceUnitOfWork) -> VehicleStatsDTO:
        """ADR-0020: "Total Vehicles" KPI, backing `platform_audit.PlatformStatsApplicationService`."""
        async with uow:
            total = await uow.vehicles.count_total()
            return VehicleStatsDTO(total=total)

    @staticmethod
    async def _get_vehicle_or_raise(
        uow: FleetDeviceUnitOfWork, vehicle_id: str
    ) -> Vehicle:
        vehicle = await uow.vehicles.get(VehicleId(vehicle_id))
        if vehicle is None:
            raise NotFoundError(f"Vehicle {vehicle_id} not found.")
        return vehicle


class DeviceApplicationService:
    """Device lifecycle + camera + device↔vehicle assignment use-cases (the LLD §4.2
    `DeviceAppService`), and the `GetDeviceByIdQuery` read path."""

    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    # --- Device lifecycle -------------------------------------------------------------

    async def register_device(
        self, command: RegisterDeviceCommand, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceDTO:
        async with uow:
            terminal_id = TerminalId(command.terminal_id)
            await ensure_terminal_id_available(uow, terminal_id)

            imei = Imei(command.imei) if command.imei is not None else None
            if imei is not None:
                await ensure_imei_available(uow, imei)

            iccid = Iccid(command.iccid) if command.iccid is not None else None
            if iccid is not None:
                await ensure_iccid_available(uow, iccid)

            serial_number = (
                SerialNumber(command.serial_number)
                if command.serial_number is not None
                else None
            )
            if serial_number is not None:
                await ensure_serial_number_available(uow, serial_number)

            device = Device.register(
                id=DeviceId(self._id_generator.new_id()),
                organization_id=OrganizationId(command.organization_id),
                terminal_id=terminal_id,
                model=command.model,
                vendor=command.vendor,
                sim_msisdn=(
                    Msisdn(command.sim_msisdn)
                    if command.sim_msisdn is not None
                    else None
                ),
                imei=imei,
                iccid=iccid,
                serial_number=serial_number,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.devices.add(device)
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            return device_to_dto(device)

    async def activate_device(
        self, command: ActivateDeviceCommand, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceDTO:
        async with uow:
            device = await self._get_device_or_raise(uow, command.device_id)
            device.activate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            return device_to_dto(device)

    async def suspend_device(
        self, command: SuspendDeviceCommand, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceDTO:
        async with uow:
            device = await self._get_device_or_raise(uow, command.device_id)
            device.suspend(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            return device_to_dto(device)

    async def reactivate_device(
        self, command: ReactivateDeviceCommand, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceDTO:
        async with uow:
            device = await self._get_device_or_raise(uow, command.device_id)
            device.reactivate(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            return device_to_dto(device)

    async def retire_device(
        self, command: RetireDeviceCommand, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceDTO:
        """Retire, closing any active assignment in the same transaction — the orchestration
        `Device.retire`'s docstring defers here (the aggregate cannot see its assignment
        rows). Phase 2 §19.2 permits `Assigned → Retired` directly, so the device transitions
        once; the assignment row is closed alongside."""
        async with uow:
            device = await self._get_device_or_raise(uow, command.device_id)

            active = await uow.device_assignments.active_for_device(device.id)
            if active is not None:
                active.close(clock=self._clock, actor_id=command.actor.user_id)
                uow.record_events(active.pull_domain_events())

            device.retire(clock=self._clock, actor_id=command.actor.user_id)
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            return device_to_dto(device)

    async def record_device_seen(
        self, command: RecordDeviceSeenCommand, *, uow: FleetDeviceUnitOfWork
    ) -> None:
        """`docs/architecture/post-f7-production-readiness-roadmap.md` Phase A item A3 — the
        application-layer entry point `events/subscribers.py`'s `DeviceOnline`/`DeviceOffline`
        processors call. **No-ops (logs, doesn't raise) for an unknown `device_id`** — unlike
        every other method here, which raises `NotFoundError` for a caller that named a specific
        device it expected to exist, a connectivity event for a terminal this backend never
        registered (a stray, decommissioned, or not-yet-provisioned device still reaching the
        device-gateway) is a real, expected occurrence, not an error. Returns `None`, not a DTO
        — no HTTP route calls this; there is nothing for a caller to do with the result."""
        async with uow:
            device = await uow.devices.get(DeviceId(command.device_id))
            if device is None:
                logger.info(
                    "device_seen_event_for_unknown_device",
                    extra={"device_id": command.device_id},
                )
                return
            device.record_last_seen(command.seen_at, is_online=command.is_online)
            await uow.commit()

    async def register_camera(
        self, command: RegisterCameraCommand, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceDTO:
        async with uow:
            device = await self._get_device_or_raise(uow, command.device_id)
            device.register_camera(
                id=CameraId(self._id_generator.new_id()),
                channel_no=command.channel_no,
                position=command.position,
                label=command.label,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            return device_to_dto(device)

    async def get_device_by_id(
        self, query: GetDeviceByIdQuery, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceDTO:
        async with uow:
            device = await self._get_device_or_raise(uow, query.device_id)
            return device_to_dto(device)

    async def list_devices(
        self, query: ListDevicesQuery, *, uow: FleetDeviceUnitOfWork
    ) -> OffsetPage[DeviceDTO]:
        """Backs `GET /devices`'s paginated/filtered/sorted contract (API Contracts §4.2/§7/
        §8)."""
        async with uow:
            page = await uow.devices.list_page(
                query.page_request,
                sort=query.sort,
                filters=query.filters,
                search=query.search,
            )
            return OffsetPage(
                data=[device_to_dto(d) for d in page.data],
                total=page.total,
                page=page.page,
                page_size=page.page_size,
            )

    async def get_device_stats(self, *, uow: FleetDeviceUnitOfWork) -> DeviceStatsDTO:
        """ADR-0020 §3: "Total/Online/Offline Devices" KPI, backing `platform_audit.
        PlatformStatsApplicationService`."""
        async with uow:
            total = await uow.devices.count_total()
            online = await uow.devices.count_online()
            return DeviceStatsDTO(total=total, online=online, offline=total - online)

    # --- Device ↔ Vehicle assignment ----------------------------------------------------

    async def assign_device_to_vehicle(
        self, command: AssignDeviceToVehicleCommand, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceAssignmentDTO:
        """LLD §4.2 `handle(AssignDeviceToVehicle)`. Both one-active-binding guards run
        before the aggregate work (LLD §5.2's repository-guard placement); the DB's
        generated-column unique indexes (Database Design §5.4) remain the second enforcement
        layer against races."""
        async with uow:
            device = await self._get_device_or_raise(uow, command.device_id)
            vehicle = await ensure_vehicle_exists(uow, VehicleId(command.vehicle_id))
            ensure_same_organization(device, vehicle)
            await ensure_device_has_no_active_assignment(uow, device.id)
            await ensure_vehicle_has_no_active_device(
                uow, VehicleId(command.vehicle_id)
            )

            assignment = DeviceAssignment.open(
                id=AssignmentId(self._id_generator.new_id()),
                organization_id=device.organization_id,
                device_id=device.id,
                vehicle_id=VehicleId(command.vehicle_id),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            device.mark_assigned(clock=self._clock)

            uow.device_assignments.add(assignment)
            uow.record_events(assignment.pull_domain_events())
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            return assignment_to_dto(assignment)

    async def unassign_device(
        self, command: UnassignDeviceCommand, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceAssignmentDTO:
        async with uow:
            device = await self._get_device_or_raise(uow, command.device_id)

            assignment = await uow.device_assignments.active_for_device(device.id)
            if assignment is None:
                raise NotFoundError(
                    f"Device {command.device_id} has no active assignment."
                )

            assignment.close(clock=self._clock, actor_id=command.actor.user_id)
            device.mark_unassigned(clock=self._clock)

            uow.record_events(assignment.pull_domain_events())
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            return assignment_to_dto(assignment)

    async def reassign_device(
        self, command: ReassignDeviceCommand, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceAssignmentDTO:
        """LLD §4.2 `handle(ReassignDevice)`; Phase 2 §19.2's flow verbatim: close the
        current active assignment, open a new one, emit `DeviceReassigned`. The device stays
        `assigned` throughout (§19.2: `Assigned → Reassigned → Assigned` — a transition, not
        a state change)."""
        async with uow:
            device = await self._get_device_or_raise(uow, command.device_id)
            new_vehicle = await ensure_vehicle_exists(
                uow, VehicleId(command.new_vehicle_id)
            )
            ensure_same_organization(device, new_vehicle)

            old_assignment = await uow.device_assignments.active_for_device(device.id)
            if old_assignment is None:
                raise NotFoundError(
                    f"Device {command.device_id} has no active assignment to reassign "
                    "from — use assign instead."
                )
            await ensure_vehicle_has_no_active_device(
                uow, VehicleId(command.new_vehicle_id)
            )

            old_assignment.close(clock=self._clock, actor_id=command.actor.user_id)
            new_assignment = DeviceAssignment.open(
                id=AssignmentId(self._id_generator.new_id()),
                organization_id=device.organization_id,
                device_id=device.id,
                vehicle_id=VehicleId(command.new_vehicle_id),
                clock=self._clock,
                actor_id=command.actor.user_id,
            )

            uow.device_assignments.add(new_assignment)
            uow.record_events(old_assignment.pull_domain_events())
            uow.record_events(new_assignment.pull_domain_events())
            uow.record_events(
                [
                    fleet_events.device_reassigned(
                        device_id=str(device.id),
                        organization_id=str(device.organization_id),
                        old_vehicle_id=str(old_assignment.vehicle_id),
                        new_vehicle_id=command.new_vehicle_id,
                        old_assignment_id=str(old_assignment.id),
                        new_assignment_id=str(new_assignment.id),
                        occurred_at=self._clock.now(),
                        actor_id=command.actor.user_id,
                    )
                ]
            )
            await uow.commit()
            return assignment_to_dto(new_assignment)

    @staticmethod
    async def _get_device_or_raise(
        uow: FleetDeviceUnitOfWork, device_id: str
    ) -> Device:
        device = await uow.devices.get(DeviceId(device_id))
        if device is None:
            raise NotFoundError(f"Device {device_id} not found.")
        return device


class DeviceInventoryApplicationService:
    """ADR-0018 device-inventory use-cases: `receive`/`allocate`. Its own service class
    (not a method bolted onto `DeviceApplicationService`) — `/device-inventory` is a new REST
    resource, matching this module's own "split into two services by natural API grouping"
    precedent (this class's own module docstring, above)."""

    def __init__(self, *, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._id_generator = id_generator

    async def receive_device_inventory_item(
        self, command: ReceiveDeviceInventoryItemCommand, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceInventoryItemDTO:
        async with uow:
            serial_number = SerialNumber(command.serial_number)
            await ensure_inventory_serial_number_available(uow, serial_number)

            imei = Imei(command.imei) if command.imei is not None else None
            if imei is not None:
                await ensure_inventory_imei_available(uow, imei)

            iccid = Iccid(command.iccid) if command.iccid is not None else None
            if iccid is not None:
                await ensure_inventory_iccid_available(uow, iccid)

            item = DeviceInventoryItem.receive(
                id=InventoryItemId(self._id_generator.new_id()),
                serial_number=serial_number,
                imei=imei,
                iccid=iccid,
                model=command.model,
                vendor=command.vendor,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.device_inventory.add(item)
            uow.record_events(item.pull_domain_events())
            await uow.commit()
            return inventory_item_to_dto(item)

    async def allocate_device_inventory_item(
        self, command: AllocateDeviceInventoryItemCommand, *, uow: FleetDeviceUnitOfWork
    ) -> DeviceDTO:
        """ADR-0018 §1: transitions the inventory item to `allocated`, then creates the actual
        `devices` row via the *existing* `Device.register()` factory, in the same transaction —
        "allocation to a tenant creates the `devices` row and links back by `inventory_id`",
        applied exactly.

        **Resolved gap (confirmed with user):** ADR-0018's request body is `{organization_id}`
        only, but `Device.register()` requires a non-empty `terminal_id`. Resolved by reusing
        the inventory item's own `serial_number` as the new device's `terminal_id` — grounded in
        ADR-0009/0010/0015: the only currently-integrated vendor (LSZ) has no real JT808
        terminal_id concept, and `serial_number` is already its wire identity."""
        async with uow:
            item = await self._get_inventory_item_or_raise(uow, command.inventory_item_id)
            ensure_inventory_item_allocatable(item)

            terminal_id = TerminalId(str(item.serial_number))
            await ensure_terminal_id_available(uow, terminal_id)
            if item.imei is not None:
                await ensure_imei_available(uow, item.imei)
            if item.iccid is not None:
                await ensure_iccid_available(uow, item.iccid)
            await ensure_serial_number_available(uow, item.serial_number)

            organization_id = OrganizationId(command.organization_id)
            item.allocate(
                organization_id=organization_id,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )

            device = Device.register(
                id=DeviceId(self._id_generator.new_id()),
                organization_id=organization_id,
                terminal_id=terminal_id,
                model=item.model,
                vendor=item.vendor,
                imei=item.imei,
                iccid=item.iccid,
                serial_number=item.serial_number,
                inventory_id=item.id,
                clock=self._clock,
                actor_id=command.actor.user_id,
            )
            uow.devices.add(device)
            uow.record_events(item.pull_domain_events())
            uow.record_events(device.pull_domain_events())
            await uow.commit()
            return device_to_dto(device)

    @staticmethod
    async def _get_inventory_item_or_raise(
        uow: FleetDeviceUnitOfWork, inventory_item_id: str
    ) -> DeviceInventoryItem:
        item = await uow.device_inventory.get(InventoryItemId(inventory_item_id))
        if item is None:
            raise NotFoundError(f"Device inventory item {inventory_item_id} not found.")
        return item
