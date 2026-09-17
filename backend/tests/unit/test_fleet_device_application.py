"""Application-layer tests for `fleet_device`'s `VehicleApplicationService`/
`DeviceApplicationService`. Stdlib `unittest` — no `pytest`, matching established precedent.
In-memory fake `FleetDeviceUnitOfWork`/repositories, including a faithful `active_for_device`/
`active_for_vehicle` implementation so the safety-critical one-active-binding invariant is
exercised the same way the real repository guard is (`.claude/rules/testing.md` #3).

Covers: duplicate plate/terminal-id rejection, the full assign -> unassign -> reassign
lifecycle, and (its own dedicated focus) the one-active-assignment-per-vehicle /
one-active-vehicle-per-device invariants.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from raad.core.errors.exceptions import ConflictError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.pagination import (
    FilterCondition,
    OffsetPage,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.fleet_device.application.commands import (
    ActivateDeviceCommand,
    ActivateVehicleCommand,
    AllocateDeviceInventoryItemCommand,
    AssignDeviceToVehicleCommand,
    MarkVehicleUnderMaintenanceCommand,
    ReassignDeviceCommand,
    ReceiveDeviceInventoryItemCommand,
    RecordAudioCapabilityCommand,
    RecordDeviceSeenCommand,
    RegisterCameraCommand,
    RegisterDeviceCommand,
    RegisterVehicleCommand,
    RetireDeviceCommand,
    SuspendDeviceCommand,
    UnassignDeviceCommand,
    UpdateCameraCommand,
    UpdateDeviceDetailsCommand,
)
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.queries import (
    GetDeviceByIdQuery,
    GetVehicleByIdQuery,
    ListDevicesQuery,
    ListVehiclesQuery,
)
from raad.modules.fleet_device.application.services import (
    DeviceApplicationService,
    DeviceInventoryApplicationService,
    VehicleApplicationService,
)
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
    OnlineDeviceAssignment,
    VehicleRepository,
)
from raad.modules.fleet_device.domain.value_objects import (
    AssignmentId,
    AudioCapability,
    CameraPosition,
    DeviceId,
    InventoryItemId,
    TerminalId,
    VehicleId,
)

VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
NON_EXISTENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ZZ"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class SequentialIdGenerator(IdGenerator):
    _PREFIX = "01J8Z3K9G6X8YV5T4N2R"

    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._PREFIX}{self._counter:06d}"


def _field_text(item: object, field_name: str) -> str:
    value = getattr(item, field_name)
    value = getattr(value, "value", value)
    return "" if value is None else str(value)


def _matches_filter(item: object, condition: FilterCondition) -> bool:
    text = _field_text(item, condition.field)
    if condition.op == "eq":
        return text == condition.value
    if condition.op == "in":
        return text in {part.strip() for part in condition.value.split(",")}
    if condition.op == "gte":
        return text >= condition.value
    if condition.op == "lte":
        return text <= condition.value
    if condition.op == "gt":
        return text > condition.value
    if condition.op == "lt":
        return text < condition.value
    return True


def _paginate_in_memory(
    items: list,
    page_request: OffsetPageRequest,
    *,
    sort: list[SortSpec],
    filters: list[FilterCondition],
    search: str | None,
    search_field: str = "plate_no",
) -> OffsetPage:
    """Shared in-memory equivalent of `SqlAlchemyRepositoryBase.list_page` (`core/db/
    repository.py`), for fake repositories that can't run real SQL — duplicated per module's
    own test file rather than a shared test helper, mirroring `test_organization_application.
    py`'s own established "duplicated per module" precedent."""
    for condition in filters:
        items = [item for item in items if _matches_filter(item, condition)]
    if search:
        items = [
            item
            for item in items
            if search.lower() in _field_text(item, search_field).lower()
        ]
    for spec in reversed(sort):
        items = sorted(
            items, key=lambda item: _field_text(item, spec.field), reverse=spec.descending
        )
    if not sort:
        items = sorted(items, key=lambda item: str(item.id))
    total = len(items)
    start = page_request.offset
    end = start + page_request.page_size
    return OffsetPage(
        data=items[start:end], total=total, page=page_request.page, page_size=page_request.page_size
    )


class InMemoryVehicleRepository(VehicleRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Vehicle] = {}

    async def get(self, vehicle_id: VehicleId) -> Vehicle | None:
        return self.by_id.get(str(vehicle_id))

    async def get_by_plate_no(self, plate_no: str) -> Vehicle | None:
        for vehicle in self.by_id.values():
            if vehicle.plate_no == plate_no:
                return vehicle
        return None

    def add(self, vehicle: Vehicle) -> None:
        self.by_id[str(vehicle.id)] = vehicle

    async def list_all(self) -> list[Vehicle]:
        return list(self.by_id.values())

    async def list_by_ids(self, vehicle_ids: list[VehicleId]) -> list[Vehicle]:
        wanted = {str(v) for v in vehicle_ids}
        return [v for v in self.by_id.values() if str(v.id) in wanted]

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Vehicle]:
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
            search_field="plate_no",
        )

    async def count_total(self) -> int:
        return len(self.by_id)


class InMemoryDeviceRepository(DeviceRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, Device] = {}

    async def get(self, device_id: DeviceId) -> Device | None:
        return self.by_id.get(str(device_id))

    async def get_by_terminal_id(self, terminal_id: TerminalId) -> Device | None:
        for device in self.by_id.values():
            if str(device.terminal_id) == str(terminal_id):
                return device
        return None

    async def get_by_imei(self, imei) -> Device | None:
        for device in self.by_id.values():
            if device.imei is not None and str(device.imei) == str(imei):
                return device
        return None

    async def get_by_iccid(self, iccid) -> Device | None:
        for device in self.by_id.values():
            if device.iccid is not None and str(device.iccid) == str(iccid):
                return device
        return None

    async def get_by_serial_number(self, serial_number) -> Device | None:
        for device in self.by_id.values():
            if (
                device.serial_number is not None
                and str(device.serial_number) == str(serial_number)
            ):
                return device
        return None

    def add(self, device: Device) -> None:
        self.by_id[str(device.id)] = device

    async def list_all(self) -> list[Device]:
        return list(self.by_id.values())

    async def list_page(
        self,
        page_request: OffsetPageRequest,
        *,
        sort: list[SortSpec],
        filters: list[FilterCondition],
        search: str | None,
    ) -> OffsetPage[Device]:
        return _paginate_in_memory(
            list(self.by_id.values()),
            page_request,
            sort=sort,
            filters=filters,
            search=search,
            search_field="terminal_id",
        )

    async def count_total(self) -> int:
        return len(self.by_id)

    async def count_online(self) -> int:
        return sum(1 for device in self.by_id.values() if device.is_online)

    async def list_online_with_active_assignment(self) -> list[OnlineDeviceAssignment]:
        """Not exercised by anything in this file (a dedicated fake in
        `test_fleet_device_application_online.py` covers the real join behavior) — empty is the
        correct, honest default: no test here ever seeds a `device_assignments`-equivalent on
        this repository."""
        return []

    async def list_due_for_av_attributes_discovery(
        self, *, requested_before: datetime, limit: int
    ) -> list[DeviceId]:
        """Mirrors the SQL pre-filter's own conditions and ordering (never-requested first, then
        oldest request) — the real one is exercised against Postgres in
        `tests/integration/test_fleet_device_repository.py`."""
        due = [
            device
            for device in self.by_id.values()
            if device.is_online
            and not device.cameras
            and device.audio_capability is None
            and (
                device.av_attributes_requested_at is None
                or device.av_attributes_requested_at < requested_before
            )
        ]
        due.sort(
            key=lambda device: (
                device.av_attributes_requested_at is not None,
                device.av_attributes_requested_at or requested_before,
            )
        )
        return [device.id for device in due[:limit]]


class InMemoryDeviceAssignmentRepository(DeviceAssignmentRepository):
    """Faithfully implements active_for_device/active_for_vehicle over all stored
    assignments - the same query shape the real SQLAlchemy repository (and the DB's partial
    unique indexes) enforce, so this fake actually exercises the invariant rather than
    assuming it away."""

    def __init__(self) -> None:
        self.by_id: dict[str, DeviceAssignment] = {}

    async def get(self, assignment_id: AssignmentId) -> DeviceAssignment | None:
        return self.by_id.get(str(assignment_id))

    async def active_for_device(self, device_id: DeviceId) -> DeviceAssignment | None:
        for assignment in self.by_id.values():
            if str(assignment.device_id) == str(device_id) and assignment.is_active:
                return assignment
        return None

    async def active_for_vehicle(
        self, vehicle_id: VehicleId
    ) -> DeviceAssignment | None:
        for assignment in self.by_id.values():
            if str(assignment.vehicle_id) == str(vehicle_id) and assignment.is_active:
                return assignment
        return None

    def add(self, assignment: DeviceAssignment) -> None:
        self.by_id[str(assignment.id)] = assignment


class InMemoryDeviceInventoryRepository(DeviceInventoryRepository):
    def __init__(self) -> None:
        self.by_id: dict[str, DeviceInventoryItem] = {}

    async def get(self, inventory_item_id: InventoryItemId) -> DeviceInventoryItem | None:
        return self.by_id.get(str(inventory_item_id))

    async def get_by_serial_number(self, serial_number) -> DeviceInventoryItem | None:
        for item in self.by_id.values():
            if str(item.serial_number) == str(serial_number):
                return item
        return None

    async def get_by_imei(self, imei) -> DeviceInventoryItem | None:
        for item in self.by_id.values():
            if item.imei is not None and str(item.imei) == str(imei):
                return item
        return None

    async def get_by_iccid(self, iccid) -> DeviceInventoryItem | None:
        for item in self.by_id.values():
            if item.iccid is not None and str(item.iccid) == str(iccid):
                return item
        return None

    def add(self, item: DeviceInventoryItem) -> None:
        self.by_id[str(item.id)] = item


class FakeFleetDeviceUnitOfWork(FleetDeviceUnitOfWork):
    def __init__(
        self,
        vehicles: InMemoryVehicleRepository,
        devices: InMemoryDeviceRepository,
        device_assignments: InMemoryDeviceAssignmentRepository,
        device_inventory: InMemoryDeviceInventoryRepository | None = None,
    ) -> None:
        self.vehicles = vehicles
        self.devices = devices
        self.device_assignments = device_assignments
        self.device_inventory = device_inventory or InMemoryDeviceInventoryRepository()
        self.recorded_events = []
        self.commit_count = 0
        self.rollback_count = 0

    def record_events(self, events) -> None:
        self.recorded_events.extend(events)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def make_actor() -> Principal:
    return Principal(user_id="admin-1", role=Role.ORG_ADMIN, org_id=VALID_ORG_ULID)


def make_services() -> (
    tuple[
        VehicleApplicationService, DeviceApplicationService, FakeFleetDeviceUnitOfWork
    ]
):
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    id_generator = SequentialIdGenerator()
    vehicle_service = VehicleApplicationService(clock=clock, id_generator=id_generator)
    device_service = DeviceApplicationService(clock=clock, id_generator=id_generator)
    uow = FakeFleetDeviceUnitOfWork(
        InMemoryVehicleRepository(),
        InMemoryDeviceRepository(),
        InMemoryDeviceAssignmentRepository(),
    )
    return vehicle_service, device_service, uow


def make_inventory_service() -> tuple[
    DeviceInventoryApplicationService, FakeFleetDeviceUnitOfWork
]:
    """ADR-0018: a separate fixture from `make_services()` (35 existing call sites there stay
    untouched) — `allocate_device_inventory_item` needs both `uow.device_inventory` and
    `uow.devices` on the same fake UoW, exactly like the real `SqlAlchemyFleetDeviceUnitOfWork`
    bundles both."""
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    id_generator = SequentialIdGenerator()
    service = DeviceInventoryApplicationService(clock=clock, id_generator=id_generator)
    uow = FakeFleetDeviceUnitOfWork(
        InMemoryVehicleRepository(),
        InMemoryDeviceRepository(),
        InMemoryDeviceAssignmentRepository(),
        InMemoryDeviceInventoryRepository(),
    )
    return service, uow


async def _register_vehicle(
    vehicle_service, uow, plate_no="ABC-123", organization_id=VALID_ORG_ULID
) -> str:
    dto = await vehicle_service.register_vehicle(
        RegisterVehicleCommand(
            organization_id=organization_id,
            plate_no=plate_no,
            label=None,
            capacity=None,
            actor=make_actor(),
        ),
        uow=uow,
    )
    uow.recorded_events.clear()
    return dto.id


async def _register_activated_device(
    device_service, uow, terminal_id="TERM-001", organization_id=VALID_ORG_ULID
) -> str:
    dto = await device_service.register_device(
        RegisterDeviceCommand(
            organization_id=organization_id,
            terminal_id=terminal_id,
            model=None,
            vendor=None,
            sim_msisdn=None,
            imei=None,
            iccid=None,
            serial_number=None,
            actor=make_actor(),
        ),
        uow=uow,
    )
    await device_service.activate_device(
        ActivateDeviceCommand(device_id=dto.id, actor=make_actor()), uow=uow
    )
    uow.recorded_events.clear()
    return dto.id


class RegisterVehicleTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_plate_no_is_rejected(self) -> None:
        """Regression: Database Design §5.1's ux_vehicles__org_plate."""
        vehicle_service, _device_service, uow = make_services()
        await _register_vehicle(vehicle_service, uow, plate_no="ABC-123")
        with self.assertRaises(ConflictError):
            await vehicle_service.register_vehicle(
                RegisterVehicleCommand(
                    organization_id=VALID_ORG_ULID,
                    plate_no="ABC-123",
                    label=None,
                    capacity=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.vehicles.by_id), 1)

    async def test_different_plate_numbers_both_succeed(self) -> None:
        vehicle_service, _device_service, uow = make_services()
        await _register_vehicle(vehicle_service, uow, plate_no="ABC-123")
        await _register_vehicle(vehicle_service, uow, plate_no="XYZ-999")
        self.assertEqual(len(uow.vehicles.by_id), 2)


class RegisterDeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_terminal_id_is_rejected(self) -> None:
        """Regression: Database Design §5.2's global terminal_id uniqueness."""
        _vehicle_service, device_service, uow = make_services()
        await device_service.register_device(
            RegisterDeviceCommand(
                organization_id=VALID_ORG_ULID,
                terminal_id="TERM-001",
                model=None,
                vendor=None,
                sim_msisdn=None,
                imei=None,
                iccid=None,
                serial_number=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await device_service.register_device(
                RegisterDeviceCommand(
                    organization_id=VALID_ORG_ULID,
                    terminal_id="TERM-001",
                    model=None,
                    vendor=None,
                    sim_msisdn=None,
                    imei=None,
                    iccid=None,
                    serial_number=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.devices.by_id), 1)

    async def test_duplicate_imei_is_rejected(self) -> None:
        """Regression: Device Domain Overhaul's `ux_devices__imei`."""
        _vehicle_service, device_service, uow = make_services()
        await device_service.register_device(
            RegisterDeviceCommand(
                organization_id=VALID_ORG_ULID,
                terminal_id="TERM-IMEI-A",
                model=None,
                vendor=None,
                sim_msisdn=None,
                imei="352389088459231",
                iccid=None,
                serial_number=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await device_service.register_device(
                RegisterDeviceCommand(
                    organization_id=VALID_ORG_ULID,
                    terminal_id="TERM-IMEI-B",
                    model=None,
                    vendor=None,
                    sim_msisdn=None,
                    imei="352389088459231",
                    iccid=None,
                    serial_number=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.devices.by_id), 1)

    async def test_duplicate_iccid_is_rejected(self) -> None:
        """Regression: Device Domain Overhaul's `ux_devices__iccid`."""
        _vehicle_service, device_service, uow = make_services()
        await device_service.register_device(
            RegisterDeviceCommand(
                organization_id=VALID_ORG_ULID,
                terminal_id="TERM-ICCID-A",
                model=None,
                vendor=None,
                sim_msisdn=None,
                imei=None,
                iccid="8944500XXXXXXXXXXXX",
                serial_number=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await device_service.register_device(
                RegisterDeviceCommand(
                    organization_id=VALID_ORG_ULID,
                    terminal_id="TERM-ICCID-B",
                    model=None,
                    vendor=None,
                    sim_msisdn=None,
                    imei=None,
                    iccid="8944500XXXXXXXXXXXX",
                    serial_number=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.devices.by_id), 1)

    async def test_duplicate_serial_number_is_rejected(self) -> None:
        """Regression: Device Domain Overhaul's `ux_devices__serial_number`."""
        _vehicle_service, device_service, uow = make_services()
        await device_service.register_device(
            RegisterDeviceCommand(
                organization_id=VALID_ORG_ULID,
                terminal_id="TERM-SN-A",
                model=None,
                vendor=None,
                sim_msisdn=None,
                imei=None,
                iccid=None,
                serial_number="SN-0042",
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await device_service.register_device(
                RegisterDeviceCommand(
                    organization_id=VALID_ORG_ULID,
                    terminal_id="TERM-SN-B",
                    model=None,
                    vendor=None,
                    sim_msisdn=None,
                    imei=None,
                    iccid=None,
                    serial_number="SN-0042",
                    actor=make_actor(),
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.devices.by_id), 1)


class CameraRegistrationApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_camera_via_application_service(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        dto = await device_service.register_camera(
            RegisterCameraCommand(
                device_id=device_id,
                channel_no=1,
                position=CameraPosition.ROAD_FACING,
                label=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(len(dto.cameras), 1)

    async def test_duplicate_channel_via_application_service_raises_conflict(
        self,
    ) -> None:
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        await device_service.register_camera(
            RegisterCameraCommand(
                device_id=device_id,
                channel_no=1,
                position=CameraPosition.ROAD_FACING,
                label=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await device_service.register_camera(
                RegisterCameraCommand(
                    device_id=device_id,
                    channel_no=1,
                    position=CameraPosition.IN_CABIN,
                    label=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_update_camera_via_application_service_persists_new_role(self) -> None:
        """ADR-0032: an Org Admin/RAAD-staff correction of a discovered channel's
        auto-assigned role/label. No HTTP route exposes this yet (mirrors
        `RegisterCameraCommand`'s own no-route posture, `api/routers.py`'s module docstring) -
        this proves the application-layer capability itself round-trips correctly."""
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        registered = await device_service.register_camera(
            RegisterCameraCommand(
                device_id=device_id,
                channel_no=1,
                position=CameraPosition.OTHER,
                label="Channel 1",
                actor=make_actor(),
            ),
            uow=uow,
        )
        camera_id = registered.cameras[0].id

        dto = await device_service.update_camera(
            UpdateCameraCommand(
                device_id=device_id,
                camera_id=camera_id,
                position=CameraPosition.DRIVER_FACING,
                label="Driver Monitor",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(dto.cameras[0].position, CameraPosition.DRIVER_FACING.value)
        self.assertEqual(dto.cameras[0].label, "Driver Monitor")


class DeviceAssignmentLifecycleTests(unittest.IsolatedAsyncioTestCase):
    """The flagship safety-critical invariant: one active assignment per device AND per
    vehicle (`.claude/rules/testing.md` #3), exercised end-to-end through the application
    service against a faithful in-memory repository."""

    async def test_assign_device_to_vehicle_succeeds_and_marks_device_assigned(
        self,
    ) -> None:
        vehicle_service, device_service, uow = make_services()
        vehicle_id = await _register_vehicle(vehicle_service, uow)
        device_id = await _register_activated_device(device_service, uow)

        dto = await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=vehicle_id, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertTrue(dto.is_active)
        self.assertEqual(uow.devices.by_id[device_id].lifecycle_state.value, "assigned")

    async def test_assigning_an_already_assigned_device_is_rejected(self) -> None:
        """Regression: one active binding per DEVICE - a device already bound to vehicle A
        cannot also be bound to vehicle B without unassigning first."""
        vehicle_service, device_service, uow = make_services()
        vehicle_a = await _register_vehicle(vehicle_service, uow, plate_no="VEH-A")
        vehicle_b = await _register_vehicle(vehicle_service, uow, plate_no="VEH-B")
        device_id = await _register_activated_device(device_service, uow)

        await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=vehicle_a, actor=make_actor()
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await device_service.assign_device_to_vehicle(
                AssignDeviceToVehicleCommand(
                    device_id=device_id, vehicle_id=vehicle_b, actor=make_actor()
                ),
                uow=uow,
            )
        # Only the first assignment exists and is still active.
        active_count = sum(
            1 for a in uow.device_assignments.by_id.values() if a.is_active
        )
        self.assertEqual(active_count, 1)

    async def test_assigning_a_vehicle_that_already_has_an_active_device_is_rejected(
        self,
    ) -> None:
        """Regression: one active device per VEHICLE - the symmetric half of the invariant."""
        vehicle_service, device_service, uow = make_services()
        vehicle_id = await _register_vehicle(vehicle_service, uow)
        device_a = await _register_activated_device(
            device_service, uow, terminal_id="TERM-A"
        )
        device_b = await _register_activated_device(
            device_service, uow, terminal_id="TERM-B"
        )

        await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_a, vehicle_id=vehicle_id, actor=make_actor()
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await device_service.assign_device_to_vehicle(
                AssignDeviceToVehicleCommand(
                    device_id=device_b, vehicle_id=vehicle_id, actor=make_actor()
                ),
                uow=uow,
            )

    async def test_get_vehicle_by_id_embeds_tracking_status_for_assigned_device(
        self,
    ) -> None:
        """Device Domain Overhaul: `GET /vehicles/{id}` is the only device-derived data an Org
        Admin session can reach — no `device_id`/`terminal_id`, only `last_seen_at`."""
        vehicle_service, device_service, uow = make_services()
        vehicle_id = await _register_vehicle(vehicle_service, uow)
        device_id = await _register_activated_device(device_service, uow)
        await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=vehicle_id, actor=make_actor()
            ),
            uow=uow,
        )

        dto = await vehicle_service.get_vehicle_by_id(
            GetVehicleByIdQuery(vehicle_id=vehicle_id), uow=uow
        )
        self.assertIsNotNone(dto.tracking_status)
        self.assertIsNone(dto.tracking_status.last_seen_at)

    async def test_get_vehicle_by_id_tracking_status_is_none_without_an_assigned_device(
        self,
    ) -> None:
        vehicle_service, _device_service, uow = make_services()
        vehicle_id = await _register_vehicle(vehicle_service, uow)

        dto = await vehicle_service.get_vehicle_by_id(
            GetVehicleByIdQuery(vehicle_id=vehicle_id), uow=uow
        )
        self.assertIsNone(dto.tracking_status)

    async def test_unassign_then_reassign_the_same_device_to_a_new_vehicle_succeeds(
        self,
    ) -> None:
        """Regression: after unassigning, both the device and the freed vehicle become
        eligible again - the invariant guards *active* bindings only, not history."""
        vehicle_service, device_service, uow = make_services()
        vehicle_a = await _register_vehicle(vehicle_service, uow, plate_no="VEH-A")
        vehicle_b = await _register_vehicle(vehicle_service, uow, plate_no="VEH-B")
        device_id = await _register_activated_device(device_service, uow)

        await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=vehicle_a, actor=make_actor()
            ),
            uow=uow,
        )
        await device_service.unassign_device(
            UnassignDeviceCommand(device_id=device_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(
            uow.devices.by_id[device_id].lifecycle_state.value, "activated"
        )

        dto = await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=vehicle_b, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(dto.vehicle_id, vehicle_b)

    async def test_unassign_device_with_no_active_assignment_raises_not_found(
        self,
    ) -> None:
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        with self.assertRaises(NotFoundError):
            await device_service.unassign_device(
                UnassignDeviceCommand(device_id=device_id, actor=make_actor()), uow=uow
            )

    async def test_reassign_closes_old_and_opens_new_assignment(self) -> None:
        vehicle_service, device_service, uow = make_services()
        vehicle_a = await _register_vehicle(vehicle_service, uow, plate_no="VEH-A")
        vehicle_b = await _register_vehicle(vehicle_service, uow, plate_no="VEH-B")
        device_id = await _register_activated_device(device_service, uow)

        old_dto = await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=vehicle_a, actor=make_actor()
            ),
            uow=uow,
        )
        new_dto = await device_service.reassign_device(
            ReassignDeviceCommand(
                device_id=device_id, new_vehicle_id=vehicle_b, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertEqual(new_dto.vehicle_id, vehicle_b)
        self.assertFalse(uow.device_assignments.by_id[old_dto.id].is_active)
        self.assertTrue(uow.device_assignments.by_id[new_dto.id].is_active)
        # Device stays 'assigned' throughout (Phase 2 §19.2), not toggled through 'activated'.
        self.assertEqual(uow.devices.by_id[device_id].lifecycle_state.value, "assigned")

    async def test_reassign_emits_device_reassigned_event(self) -> None:
        vehicle_service, device_service, uow = make_services()
        vehicle_a = await _register_vehicle(vehicle_service, uow, plate_no="VEH-A")
        vehicle_b = await _register_vehicle(vehicle_service, uow, plate_no="VEH-B")
        device_id = await _register_activated_device(device_service, uow)
        await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=vehicle_a, actor=make_actor()
            ),
            uow=uow,
        )
        uow.recorded_events.clear()

        await device_service.reassign_device(
            ReassignDeviceCommand(
                device_id=device_id, new_vehicle_id=vehicle_b, actor=make_actor()
            ),
            uow=uow,
        )
        event_types = [event.event_type for event in uow.recorded_events]
        self.assertIn("DeviceReassigned", event_types)

    async def test_reassign_to_a_vehicle_with_an_active_device_is_rejected(
        self,
    ) -> None:
        """Regression: reassignment must still respect one-active-device-per-vehicle for the
        *target* vehicle."""
        vehicle_service, device_service, uow = make_services()
        vehicle_a = await _register_vehicle(vehicle_service, uow, plate_no="VEH-A")
        vehicle_b = await _register_vehicle(vehicle_service, uow, plate_no="VEH-B")
        device_1 = await _register_activated_device(
            device_service, uow, terminal_id="TERM-1"
        )
        device_2 = await _register_activated_device(
            device_service, uow, terminal_id="TERM-2"
        )

        await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_1, vehicle_id=vehicle_a, actor=make_actor()
            ),
            uow=uow,
        )
        await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_2, vehicle_id=vehicle_b, actor=make_actor()
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await device_service.reassign_device(
                ReassignDeviceCommand(
                    device_id=device_1, new_vehicle_id=vehicle_b, actor=make_actor()
                ),
                uow=uow,
            )

    async def test_retire_device_closes_its_active_assignment(self) -> None:
        vehicle_service, device_service, uow = make_services()
        vehicle_id = await _register_vehicle(vehicle_service, uow)
        device_id = await _register_activated_device(device_service, uow)
        await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=vehicle_id, actor=make_actor()
            ),
            uow=uow,
        )

        await device_service.retire_device(
            RetireDeviceCommand(device_id=device_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(uow.devices.by_id[device_id].lifecycle_state.value, "retired")
        active = await uow.device_assignments.active_for_device(DeviceId(device_id))
        self.assertIsNone(active)

    # --- update_device_details (device management fix) -----------------------------------

    async def test_update_device_details_corrects_terminal_id_and_emits_event(self) -> None:
        """The end-to-end regression test for the actual production issue this feature
        exists to fix: a device registered with a mis-padded terminal ID can now be corrected
        through the application layer, and the correction produces a real
        `DeviceTerminalIdChanged` event for `device-gateway`'s registry to consume — not just a
        changed database column."""
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(
            device_service, uow, terminal_id="000000000014482607571"
        )

        updated = await device_service.update_device_details(
            UpdateDeviceDetailsCommand(
                device_id=device_id,
                terminal_id="00000000014482607571",
                model=None,
                vendor=None,
                sim_msisdn=None,
                imei=None,
                iccid=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(updated.terminal_id, "00000000014482607571")
        event_types = [event.event_type for event in uow.recorded_events]
        self.assertIn("DeviceTerminalIdChanged", event_types)
        changed_event = next(
            e for e in uow.recorded_events if e.event_type == "DeviceTerminalIdChanged"
        )
        self.assertEqual(changed_event.payload["old_terminal_id"], "000000000014482607571")
        self.assertEqual(changed_event.payload["new_terminal_id"], "00000000014482607571")

    async def test_update_device_details_rejects_terminal_id_already_used(self) -> None:
        """Duplicate-terminal-id protection (Part 2D) — reusing the exact same validator
        `register_device` already enforces at creation time."""
        _vehicle_service, device_service, uow = make_services()
        await _register_activated_device(device_service, uow, terminal_id="TERM-TAKEN")
        device_id = await _register_activated_device(device_service, uow, terminal_id="TERM-2")

        with self.assertRaises(ConflictError):
            await device_service.update_device_details(
                UpdateDeviceDetailsCommand(
                    device_id=device_id,
                    terminal_id="TERM-TAKEN",
                    model=None,
                    vendor=None,
                    sim_msisdn=None,
                    imei=None,
                    iccid=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_update_device_details_updates_model_and_vendor(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)

        updated = await device_service.update_device_details(
            UpdateDeviceDetailsCommand(
                device_id=device_id,
                terminal_id=None,
                model="LSZ-C5804DG-Q-F",
                vendor="LSZ",
                sim_msisdn=None,
                imei=None,
                iccid=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(updated.model, "LSZ-C5804DG-Q-F")
        self.assertEqual(updated.vendor, "LSZ")
        event_types = [event.event_type for event in uow.recorded_events]
        self.assertIn("DeviceDetailsUpdated", event_types)
        self.assertNotIn("DeviceTerminalIdChanged", event_types)

    async def test_update_device_details_with_unchanged_terminal_id_emits_no_terminal_event(
        self,
    ) -> None:
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow, terminal_id="TERM-1")

        await device_service.update_device_details(
            UpdateDeviceDetailsCommand(
                device_id=device_id,
                terminal_id="TERM-1",
                model="Same model",
                vendor=None,
                sim_msisdn=None,
                imei=None,
                iccid=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        event_types = [event.event_type for event in uow.recorded_events]
        self.assertNotIn("DeviceTerminalIdChanged", event_types)

    async def test_get_device_by_id_includes_camera_list(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        await device_service.register_camera(
            RegisterCameraCommand(
                device_id=device_id,
                channel_no=1,
                position=CameraPosition.OTHER,
                label="dashcam",
                actor=make_actor(),
            ),
            uow=uow,
        )
        dto = await device_service.get_device_by_id(
            GetDeviceByIdQuery(device_id=device_id), uow=uow
        )
        self.assertEqual(len(dto.cameras), 1)
        self.assertEqual(dto.cameras[0].label, "dashcam")


class VehicleDeviceAssignmentQueryTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0027 Change 1: `VehicleApplicationService.get_active_device_assignment_for_vehicle`
    — the reverse direction of `DeviceApplicationService.
    get_active_vehicle_assignment_for_device` (ADR-0026), resolving the vehicle first via the
    existing, already-scoped `_get_vehicle_or_raise` path before ever querying
    `device_assignments`. Cross-organization scope-rejection needs a real, live-scoped
    repository and is proven in `test_fleet_device_repository.py`'s
    `TenantIsolationRepositoryTests` instead — these in-memory fakes carry no scope concept at
    all, so they can only prove the found/none/nonexistent-vehicle shapes."""

    async def test_returns_the_active_assignment(self) -> None:
        vehicle_service, device_service, uow = make_services()
        vehicle_id = await _register_vehicle(vehicle_service, uow)
        device_id = await _register_activated_device(device_service, uow)
        await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=vehicle_id, actor=make_actor()
            ),
            uow=uow,
        )

        dto = await vehicle_service.get_active_device_assignment_for_vehicle(
            vehicle_id, uow=uow
        )

        self.assertIsNotNone(dto)
        self.assertEqual(dto.device_id, device_id)
        self.assertEqual(dto.vehicle_id, vehicle_id)
        self.assertTrue(dto.is_active)

    async def test_returns_none_for_a_vehicle_with_no_active_assignment(self) -> None:
        vehicle_service, _device_service, uow = make_services()
        vehicle_id = await _register_vehicle(vehicle_service, uow)

        dto = await vehicle_service.get_active_device_assignment_for_vehicle(
            vehicle_id, uow=uow
        )

        self.assertIsNone(dto)

    async def test_raises_not_found_for_a_nonexistent_vehicle(self) -> None:
        vehicle_service, _device_service, uow = make_services()

        with self.assertRaises(NotFoundError):
            await vehicle_service.get_active_device_assignment_for_vehicle(
                NON_EXISTENT_ULID, uow=uow
            )

    async def test_returns_none_after_the_device_is_unassigned(self) -> None:
        """The assignment's own closed history row must not be mistaken for an active one."""
        vehicle_service, device_service, uow = make_services()
        vehicle_id = await _register_vehicle(vehicle_service, uow)
        device_id = await _register_activated_device(device_service, uow)
        await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=vehicle_id, actor=make_actor()
            ),
            uow=uow,
        )
        await device_service.unassign_device(
            UnassignDeviceCommand(device_id=device_id, actor=make_actor()), uow=uow
        )

        dto = await vehicle_service.get_active_device_assignment_for_vehicle(
            vehicle_id, uow=uow
        )

        self.assertIsNone(dto)


OTHER_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3OT"


class CrossOrganizationAssignmentTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0021: a device may only ever be assigned to a vehicle in its own organization,
    independent of caller scope (which only proves the caller may act on *each* resource
    individually, not that the two resources agree with each other) — the fix for a confirmed
    finding: `assign_device_to_vehicle`/`reassign_device` previously had no such check at all."""

    async def test_assign_rejects_a_device_and_vehicle_from_different_organizations(
        self,
    ) -> None:
        vehicle_service, device_service, uow = make_services()
        vehicle_id = await _register_vehicle(
            vehicle_service, uow, organization_id=OTHER_ORG_ULID
        )
        device_id = await _register_activated_device(
            device_service, uow, organization_id=VALID_ORG_ULID
        )

        with self.assertRaises(ConflictError):
            await device_service.assign_device_to_vehicle(
                AssignDeviceToVehicleCommand(
                    device_id=device_id, vehicle_id=vehicle_id, actor=make_actor()
                ),
                uow=uow,
            )
        self.assertEqual(len(uow.device_assignments.by_id), 0)
        self.assertEqual(uow.devices.by_id[device_id].lifecycle_state.value, "activated")

    async def test_assign_succeeds_when_device_and_vehicle_share_an_organization(
        self,
    ) -> None:
        """Confirms the new check doesn't reject the ordinary, same-org case."""
        vehicle_service, device_service, uow = make_services()
        vehicle_id = await _register_vehicle(
            vehicle_service, uow, organization_id=VALID_ORG_ULID
        )
        device_id = await _register_activated_device(
            device_service, uow, organization_id=VALID_ORG_ULID
        )

        dto = await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=vehicle_id, actor=make_actor()
            ),
            uow=uow,
        )
        self.assertTrue(dto.is_active)

    async def test_reassign_rejects_a_new_vehicle_from_a_different_organization(
        self,
    ) -> None:
        vehicle_service, device_service, uow = make_services()
        own_vehicle = await _register_vehicle(
            vehicle_service, uow, plate_no="VEH-OWN", organization_id=VALID_ORG_ULID
        )
        other_org_vehicle = await _register_vehicle(
            vehicle_service, uow, plate_no="VEH-OTHER", organization_id=OTHER_ORG_ULID
        )
        device_id = await _register_activated_device(
            device_service, uow, organization_id=VALID_ORG_ULID
        )
        await device_service.assign_device_to_vehicle(
            AssignDeviceToVehicleCommand(
                device_id=device_id, vehicle_id=own_vehicle, actor=make_actor()
            ),
            uow=uow,
        )

        with self.assertRaises(ConflictError):
            await device_service.reassign_device(
                ReassignDeviceCommand(
                    device_id=device_id,
                    new_vehicle_id=other_org_vehicle,
                    actor=make_actor(),
                ),
                uow=uow,
            )
        # The original assignment must still be active - the rejected reassignment must not
        # have closed it.
        active = [a for a in uow.device_assignments.by_id.values() if a.is_active]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].vehicle_id, VehicleId(own_vehicle))


class VehiclePaginationApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_vehicles_paginates_and_reports_total(self) -> None:
        vehicle_service, _device_service, uow = make_services()
        for i in range(3):
            await _register_vehicle(vehicle_service, uow, plate_no=f"PLATE-{i}")

        page = await vehicle_service.list_vehicles(
            ListVehiclesQuery(page_request=OffsetPageRequest(page=1, page_size=2)),
            uow=uow,
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(page.page, 1)
        self.assertEqual(page.page_size, 2)
        self.assertEqual(len(page.data), 2)

        second_page = await vehicle_service.list_vehicles(
            ListVehiclesQuery(page_request=OffsetPageRequest(page=2, page_size=2)),
            uow=uow,
        )
        self.assertEqual(len(second_page.data), 1)

    async def test_list_vehicles_filters_by_status(self) -> None:
        vehicle_service, _device_service, uow = make_services()
        active_id = await _register_vehicle(vehicle_service, uow, plate_no="ACTIVE-1")
        maintenance_id = await _register_vehicle(
            vehicle_service, uow, plate_no="MAINT-1"
        )
        await vehicle_service.mark_vehicle_under_maintenance(
            MarkVehicleUnderMaintenanceCommand(
                vehicle_id=maintenance_id, actor=make_actor()
            ),
            uow=uow,
        )

        page = await vehicle_service.list_vehicles(
            ListVehiclesQuery(
                page_request=OffsetPageRequest(),
                filters=[FilterCondition(field="status", op="eq", value="active")],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].id, active_id)

    async def test_list_vehicles_sorts_descending_by_plate_no(self) -> None:
        vehicle_service, _device_service, uow = make_services()
        for plate_no in ("Alpha", "Beta", "Gamma"):
            await _register_vehicle(vehicle_service, uow, plate_no=plate_no)

        page = await vehicle_service.list_vehicles(
            ListVehiclesQuery(
                page_request=OffsetPageRequest(),
                sort=[SortSpec(field="plate_no", descending=True)],
            ),
            uow=uow,
        )
        self.assertEqual(
            [v.plate_no for v in page.data], ["Gamma", "Beta", "Alpha"]
        )


class DevicePaginationApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_devices_paginates_and_reports_total(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        for i in range(3):
            await device_service.register_device(
                RegisterDeviceCommand(
                    organization_id=VALID_ORG_ULID,
                    terminal_id=f"TERM-{i}",
                    model=None,
                    vendor=None,
                    sim_msisdn=None,
                    imei=None,
                    iccid=None,
                    serial_number=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await device_service.list_devices(
            ListDevicesQuery(page_request=OffsetPageRequest(page=1, page_size=2)),
            uow=uow,
        )
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.data), 2)

        second_page = await device_service.list_devices(
            ListDevicesQuery(page_request=OffsetPageRequest(page=2, page_size=2)),
            uow=uow,
        )
        self.assertEqual(len(second_page.data), 1)

    async def test_list_devices_filters_by_lifecycle_state(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        activated_id = await _register_activated_device(
            device_service, uow, terminal_id="TERM-ACTIVATED"
        )
        await device_service.register_device(
            RegisterDeviceCommand(
                organization_id=VALID_ORG_ULID,
                terminal_id="TERM-REGISTERED",
                model=None,
                vendor=None,
                sim_msisdn=None,
                imei=None,
                iccid=None,
                serial_number=None,
                actor=make_actor(),
            ),
            uow=uow,
        )

        page = await device_service.list_devices(
            ListDevicesQuery(
                page_request=OffsetPageRequest(),
                filters=[
                    FilterCondition(field="lifecycle_state", op="eq", value="activated")
                ],
            ),
            uow=uow,
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.data[0].id, activated_id)

    async def test_list_devices_sorts_descending_by_terminal_id(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        for terminal_id in ("Alpha", "Beta", "Gamma"):
            await device_service.register_device(
                RegisterDeviceCommand(
                    organization_id=VALID_ORG_ULID,
                    terminal_id=terminal_id,
                    model=None,
                    vendor=None,
                    sim_msisdn=None,
                    imei=None,
                    iccid=None,
                    serial_number=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

        page = await device_service.list_devices(
            ListDevicesQuery(
                page_request=OffsetPageRequest(),
                sort=[SortSpec(field="terminal_id", descending=True)],
            ),
            uow=uow,
        )
        self.assertEqual(
            [d.terminal_id for d in page.data], ["Gamma", "Beta", "Alpha"]
        )


class FleetStatsApplicationTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0020: `get_vehicle_stats`/`get_device_stats`, backing `platform_audit.
    PlatformStatsApplicationService`."""

    async def test_get_vehicle_stats_reports_total(self) -> None:
        vehicle_service, _device_service, uow = make_services()
        for i in range(3):
            await _register_vehicle(vehicle_service, uow, plate_no=f"STAT-{i}")

        stats = await vehicle_service.get_vehicle_stats(uow=uow)

        self.assertEqual(stats.total, 3)

    async def test_get_device_stats_splits_online_and_offline(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        online_id = await _register_activated_device(
            device_service, uow, terminal_id="TERM-ONLINE"
        )
        await _register_activated_device(device_service, uow, terminal_id="TERM-OFFLINE")
        await device_service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=online_id,
                seen_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
                is_online=True,
                actor=make_actor(),
            ),
            uow=uow,
        )

        stats = await device_service.get_device_stats(uow=uow)

        self.assertEqual(stats.total, 2)
        self.assertEqual(stats.online, 1)
        self.assertEqual(stats.offline, 1)


class DeviceLifecycleApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_suspend_activated_device(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        dto = await device_service.suspend_device(
            SuspendDeviceCommand(device_id=device_id, actor=make_actor()), uow=uow
        )
        self.assertEqual(dto.lifecycle_state, "suspended")

    async def test_activate_on_missing_device_raises_not_found(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        with self.assertRaises(NotFoundError):
            await device_service.activate_device(
                ActivateDeviceCommand(device_id=NON_EXISTENT_ULID, actor=make_actor()),
                uow=uow,
            )


class RecordDeviceSeenTests(unittest.IsolatedAsyncioTestCase):
    """`docs/architecture/post-f7-production-readiness-roadmap.md` Phase A item A3."""

    async def test_updates_last_seen_at_and_commits(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        seen_at = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)
        commit_count_before = uow.commit_count

        result = await device_service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=device_id, seen_at=seen_at, is_online=True, actor=make_actor()
            ),
            uow=uow,
        )

        # ADR-0030: the first-ever `is_online=True` transition for a device that has never had
        # channel discovery requested returns its own `terminal_id`, the signal
        # `DeviceConnectivityProcessor` uses to publish a `0x9003` discovery request.
        self.assertEqual(result, "TERM-001")
        self.assertEqual(uow.devices.by_id[device_id].last_seen_at, seen_at)
        self.assertTrue(uow.devices.by_id[device_id].is_online)
        self.assertIsNotNone(uow.devices.by_id[device_id].av_attributes_requested_at)
        self.assertEqual(uow.commit_count, commit_count_before + 1)

    async def _online(self, device_service, uow, device_id: str, seen_at: datetime):
        return await device_service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=device_id, seen_at=seen_at, is_online=True, actor=make_actor()
            ),
            uow=uow,
        )

    async def test_reconnect_within_the_retry_interval_does_not_resend_discovery(self) -> None:
        """A flapping connection must not resend `0x9003` on every reconnect."""
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        first_seen = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)

        first = await self._online(device_service, uow, device_id, first_seen)
        second = await self._online(
            device_service, uow, device_id, first_seen + timedelta(minutes=2)
        )

        self.assertEqual(first, "TERM-001")
        self.assertIsNone(second)
        self.assertEqual(uow.devices.by_id[device_id].av_attributes_requested_at, first_seen)

    async def test_reconnect_after_an_unanswered_request_retries_discovery(self) -> None:
        """Regression test for the 2026-09-17 fix. Previously a device whose one `0x9003` was
        lost never got cameras: every later reconnect returned `None` forever."""
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        first_seen = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)
        reconnect = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)

        await self._online(device_service, uow, device_id, first_seen)
        retried = await self._online(device_service, uow, device_id, reconnect)

        self.assertEqual(retried, "TERM-001")
        self.assertEqual(uow.devices.by_id[device_id].av_attributes_requested_at, reconnect)

    async def test_reconnect_after_discovery_was_answered_never_requests_again(self) -> None:
        """Once the terminal has answered (cameras registered), ADR-0030's once-per-device
        behaviour is unchanged — no reconnect ever resends discovery."""
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        await self._online(
            device_service, uow, device_id, datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)
        )
        await device_service.register_camera(
            RegisterCameraCommand(
                device_id=device_id,
                channel_no=1,
                position=CameraPosition.OTHER,
                label="Channel 1",
                actor=make_actor(),
            ),
            uow=uow,
        )

        later = await self._online(
            device_service, uow, device_id, datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)
        )

        self.assertIsNone(later)

    async def test_unknown_device_id_is_a_safe_no_op_not_an_error(self) -> None:
        """A connectivity event for a terminal this backend never registered (stray/
        decommissioned/not-yet-provisioned device) must not raise - unlike every other
        `_or_raise`-backed method on this service."""
        _vehicle_service, device_service, uow = make_services()
        seen_at = datetime(2026, 7, 25, tzinfo=timezone.utc)

        await device_service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=NON_EXISTENT_ULID,
                seen_at=seen_at,
                is_online=True,
                actor=make_actor(),
            ),
            uow=uow,
        )

        self.assertEqual(uow.commit_count, 0)

    async def test_does_not_change_lifecycle_state(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)

        await device_service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=device_id,
                seen_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
                is_online=True,
                actor=make_actor(),
            ),
            uow=uow,
        )

        self.assertEqual(uow.devices.by_id[device_id].lifecycle_state.value, "activated")

    async def test_is_online_false_clears_the_flag(self) -> None:
        """ADR-0020 §3: a `DeviceOffline` event flips `is_online` back off."""
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)

        await device_service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=device_id,
                seen_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
                is_online=True,
                actor=make_actor(),
            ),
            uow=uow,
        )
        await device_service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=device_id,
                seen_at=datetime(2026, 7, 25, 1, tzinfo=timezone.utc),
                is_online=False,
                actor=make_actor(),
            ),
            uow=uow,
        )

        self.assertFalse(uow.devices.by_id[device_id].is_online)

    async def test_get_device_by_id_reflects_is_online(self) -> None:
        """ADR-0027 Change 2: `DeviceDTO.is_online` mirrors `Device.is_online` directly — no
        second source of truth, proven via the same mapper (`device_to_dto`) `GET /devices/{id}`
        uses."""
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)

        before = await device_service.get_device_by_id(
            GetDeviceByIdQuery(device_id=device_id), uow=uow
        )
        self.assertFalse(before.is_online)

        await device_service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=device_id,
                seen_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
                is_online=True,
                actor=make_actor(),
            ),
            uow=uow,
        )

        after = await device_service.get_device_by_id(
            GetDeviceByIdQuery(device_id=device_id), uow=uow
        )
        self.assertTrue(after.is_online)


class ClaimDueAvAttributesDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    """2026-09-17 — the periodic retry for a device that stays connected after its only
    discovery request was lost (`DeviceApplicationService.claim_due_av_attributes_discovery`)."""

    _START = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)

    async def asyncSetUp(self) -> None:
        self.clock = FixedClock(self._START)
        self.device_service = DeviceApplicationService(
            clock=self.clock, id_generator=SequentialIdGenerator()
        )
        self.uow = FakeFleetDeviceUnitOfWork(
            InMemoryVehicleRepository(),
            InMemoryDeviceRepository(),
            InMemoryDeviceAssignmentRepository(),
        )

    async def _online_device(self, terminal_id: str) -> str:
        device_id = await _register_activated_device(
            self.device_service, self.uow, terminal_id=terminal_id
        )
        await self.device_service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=device_id, seen_at=self.clock.now(), is_online=True, actor=make_actor()
            ),
            uow=self.uow,
        )
        return device_id

    async def test_nothing_is_claimed_before_the_retry_interval_passes(self) -> None:
        await self._online_device("TERM-A")  # its first request was just sent on DeviceOnline
        self.clock._now = self._START + timedelta(minutes=9)

        claimed = await self.device_service.claim_due_av_attributes_discovery(uow=self.uow)

        self.assertEqual(claimed, [])

    async def test_a_still_connected_device_with_an_unanswered_request_is_claimed_once(
        self,
    ) -> None:
        device_id = await self._online_device("TERM-A")
        self.clock._now = self._START + timedelta(minutes=11)
        commits_before = self.uow.commit_count

        first = await self.device_service.claim_due_av_attributes_discovery(uow=self.uow)
        second = await self.device_service.claim_due_av_attributes_discovery(uow=self.uow)

        self.assertEqual(first, ["TERM-A"])
        # Claiming recorded the request time, so an immediate re-run (or an overlapping worker)
        # finds nothing — no duplicate 0x9003.
        self.assertEqual(second, [])
        self.assertEqual(
            self.uow.devices.by_id[device_id].av_attributes_requested_at, self.clock.now()
        )
        self.assertEqual(self.uow.commit_count, commits_before + 1)

    async def test_answered_offline_and_recent_devices_are_not_claimed(self) -> None:
        answered = await self._online_device("TERM-ANSWERED")
        await self.device_service.register_camera(
            RegisterCameraCommand(
                device_id=answered,
                channel_no=1,
                position=CameraPosition.OTHER,
                label="Channel 1",
                actor=make_actor(),
            ),
            uow=self.uow,
        )
        offline = await self._online_device("TERM-OFFLINE")
        await self.device_service.record_device_seen(
            RecordDeviceSeenCommand(
                device_id=offline, seen_at=self.clock.now(), is_online=False, actor=make_actor()
            ),
            uow=self.uow,
        )
        await self._online_device("TERM-DUE")
        self.clock._now = self._START + timedelta(minutes=11)
        await self._online_device("TERM-RECENT")  # requested just now, at the new time

        claimed = await self.device_service.claim_due_av_attributes_discovery(uow=self.uow)

        self.assertEqual(claimed, ["TERM-DUE"])

    async def test_limit_bounds_one_run(self) -> None:
        for n in range(3):
            await self._online_device(f"TERM-{n}")
        self.clock._now = self._START + timedelta(minutes=11)

        claimed = await self.device_service.claim_due_av_attributes_discovery(
            uow=self.uow, limit=2
        )

        self.assertEqual(len(claimed), 2)

    async def test_no_due_device_commits_nothing(self) -> None:
        commits_before = self.uow.commit_count
        claimed = await self.device_service.claim_due_av_attributes_discovery(uow=self.uow)
        self.assertEqual(claimed, [])
        self.assertEqual(self.uow.commit_count, commits_before)


class RecordAudioCapabilityTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0033 — the application-layer entry point `events/subscribers.py`'s
    `DeviceAvAttributesReportedProcessor` calls alongside its existing camera-discovery loop."""

    async def test_records_audio_capability_and_commits(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        commit_count_before = uow.commit_count
        capability = AudioCapability(
            codec=6,
            channels=1,
            sample_rate=3,
            sample_bits=1,
            frame_length=320,
            supports_output=True,
            video_codec=2,
        )

        await device_service.record_audio_capability(
            RecordAudioCapabilityCommand(
                device_id=device_id, audio_capability=capability, actor=make_actor()
            ),
            uow=uow,
        )

        self.assertEqual(uow.commit_count, commit_count_before + 1)
        stored = await uow.devices.get(DeviceId(device_id))
        self.assertEqual(stored.audio_capability, capability)

    async def test_device_dto_projects_the_recorded_audio_codec(self) -> None:
        """`device_to_dto` (`application/queries.py`) - the G.711A audio fix's own new consumer
        of `AudioCapability.codec`, exposed on `DeviceDTO` for the first time this phase."""
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)
        await device_service.record_audio_capability(
            RecordAudioCapabilityCommand(
                device_id=device_id,
                audio_capability=AudioCapability(
                    codec=6,
                    channels=1,
                    sample_rate=0,
                    sample_bits=1,
                    frame_length=320,
                    supports_output=True,
                    video_codec=98,
                ),
                actor=make_actor(),
            ),
            uow=uow,
        )

        dto = await device_service.get_device_by_id(
            GetDeviceByIdQuery(device_id=device_id), uow=uow
        )
        self.assertEqual(dto.audio_codec, 6)

    async def test_device_dto_audio_codec_is_none_before_any_report(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        device_id = await _register_activated_device(device_service, uow)

        dto = await device_service.get_device_by_id(
            GetDeviceByIdQuery(device_id=device_id), uow=uow
        )
        self.assertIsNone(dto.audio_codec)

    async def test_unknown_device_id_is_a_no_op(self) -> None:
        _vehicle_service, device_service, uow = make_services()
        commit_count_before = uow.commit_count

        await device_service.record_audio_capability(
            RecordAudioCapabilityCommand(
                device_id=NON_EXISTENT_ULID,
                audio_capability=AudioCapability(
                    codec=6,
                    channels=1,
                    sample_rate=3,
                    sample_bits=1,
                    frame_length=320,
                    supports_output=True,
                    video_codec=2,
                ),
                actor=make_actor(),
            ),
            uow=uow,
        )

        self.assertEqual(uow.commit_count, commit_count_before)


class ReceiveDeviceInventoryItemTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0018 §2: `POST /device-inventory`."""

    async def test_receive_creates_in_stock_item(self) -> None:
        service, uow = make_inventory_service()
        dto = await service.receive_device_inventory_item(
            ReceiveDeviceInventoryItemCommand(
                serial_number="SN-001",
                imei=None,
                iccid=None,
                model="LSZ-C5804DG-Q-F",
                vendor="LSZ",
                actor=make_actor(),
            ),
            uow=uow,
        )
        self.assertEqual(dto.serial_number, "SN-001")
        self.assertEqual(dto.state, "in_stock")
        self.assertEqual(uow.commit_count, 1)

    async def test_duplicate_serial_number_is_rejected(self) -> None:
        service, uow = make_inventory_service()
        await service.receive_device_inventory_item(
            ReceiveDeviceInventoryItemCommand(
                serial_number="SN-001", imei=None, iccid=None, model=None, vendor=None,
                actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await service.receive_device_inventory_item(
                ReceiveDeviceInventoryItemCommand(
                    serial_number="SN-001", imei=None, iccid=None, model=None, vendor=None,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_duplicate_imei_is_rejected(self) -> None:
        service, uow = make_inventory_service()
        await service.receive_device_inventory_item(
            ReceiveDeviceInventoryItemCommand(
                serial_number="SN-001", imei="352389088459231", iccid=None,
                model=None, vendor=None, actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await service.receive_device_inventory_item(
                ReceiveDeviceInventoryItemCommand(
                    serial_number="SN-002", imei="352389088459231", iccid=None,
                    model=None, vendor=None, actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_duplicate_iccid_is_rejected(self) -> None:
        service, uow = make_inventory_service()
        await service.receive_device_inventory_item(
            ReceiveDeviceInventoryItemCommand(
                serial_number="SN-001", imei=None, iccid="8944500XXXXXXXXXXXX",
                model=None, vendor=None, actor=make_actor(),
            ),
            uow=uow,
        )
        with self.assertRaises(ConflictError):
            await service.receive_device_inventory_item(
                ReceiveDeviceInventoryItemCommand(
                    serial_number="SN-002", imei=None, iccid="8944500XXXXXXXXXXXX",
                    model=None, vendor=None, actor=make_actor(),
                ),
                uow=uow,
            )


class AllocateDeviceInventoryItemTests(unittest.IsolatedAsyncioTestCase):
    """ADR-0018 §2: `POST /device-inventory/{id}/allocate`."""

    async def _receive(
        self, service: DeviceInventoryApplicationService, uow: FakeFleetDeviceUnitOfWork,
        *, serial_number: str = "SN-001", imei: str | None = None, iccid: str | None = None,
    ) -> str:
        dto = await service.receive_device_inventory_item(
            ReceiveDeviceInventoryItemCommand(
                serial_number=serial_number, imei=imei, iccid=iccid,
                model="LSZ-C5804DG-Q-F", vendor="LSZ", actor=make_actor(),
            ),
            uow=uow,
        )
        return dto.id

    async def test_allocate_creates_device_row_with_inventory_link(self) -> None:
        service, uow = make_inventory_service()
        item_id = await self._receive(service, uow, serial_number="SN-001")

        device = await service.allocate_device_inventory_item(
            AllocateDeviceInventoryItemCommand(
                inventory_item_id=item_id, organization_id=VALID_ORG_ULID, actor=make_actor()
            ),
            uow=uow,
        )

        self.assertEqual(device.organization_id, VALID_ORG_ULID)
        self.assertEqual(device.inventory_id, item_id)
        self.assertEqual(device.lifecycle_state, "registered")

    async def test_allocate_derives_terminal_id_from_serial_number(self) -> None:
        """Resolved gap (confirmed with user): ADR-0018's request body is {organization_id}
        only, so terminal_id must come from somewhere - the inventory item's own serial_number
        (ADR-0009/0010/0015: the only integrated vendor's actual wire identity)."""
        service, uow = make_inventory_service()
        item_id = await self._receive(service, uow, serial_number="SN-UNIQUE-001")

        device = await service.allocate_device_inventory_item(
            AllocateDeviceInventoryItemCommand(
                inventory_item_id=item_id, organization_id=VALID_ORG_ULID, actor=make_actor()
            ),
            uow=uow,
        )

        self.assertEqual(device.terminal_id, "SN-UNIQUE-001")

    async def test_allocate_copies_imei_iccid_model_vendor_onto_device(self) -> None:
        service, uow = make_inventory_service()
        item_id = await self._receive(
            service, uow, serial_number="SN-001", imei="352389088459231",
            iccid="8944500XXXXXXXXXXXX",
        )

        device = await service.allocate_device_inventory_item(
            AllocateDeviceInventoryItemCommand(
                inventory_item_id=item_id, organization_id=VALID_ORG_ULID, actor=make_actor()
            ),
            uow=uow,
        )

        self.assertEqual(device.imei, "352389088459231")
        self.assertEqual(device.iccid, "8944500XXXXXXXXXXXX")
        self.assertEqual(device.model, "LSZ-C5804DG-Q-F")
        self.assertEqual(device.vendor, "LSZ")

    async def test_allocate_transitions_item_to_allocated(self) -> None:
        service, uow = make_inventory_service()
        item_id = await self._receive(service, uow)

        await service.allocate_device_inventory_item(
            AllocateDeviceInventoryItemCommand(
                inventory_item_id=item_id, organization_id=VALID_ORG_ULID, actor=make_actor()
            ),
            uow=uow,
        )

        self.assertEqual(uow.device_inventory.by_id[item_id].state.value, "allocated")

    async def test_allocate_missing_item_raises_not_found(self) -> None:
        service, uow = make_inventory_service()
        with self.assertRaises(NotFoundError):
            await service.allocate_device_inventory_item(
                AllocateDeviceInventoryItemCommand(
                    inventory_item_id=NON_EXISTENT_ULID,
                    organization_id=VALID_ORG_ULID,
                    actor=make_actor(),
                ),
                uow=uow,
            )

    async def test_allocate_already_allocated_item_raises_conflict_not_duplicate_device(
        self,
    ) -> None:
        """Regression: a double-submit/retry must fail loudly, not silently create a second
        `devices` row for the same physical item (`ensure_inventory_item_allocatable`)."""
        service, uow = make_inventory_service()
        item_id = await self._receive(service, uow)
        await service.allocate_device_inventory_item(
            AllocateDeviceInventoryItemCommand(
                inventory_item_id=item_id, organization_id=VALID_ORG_ULID, actor=make_actor()
            ),
            uow=uow,
        )
        devices_before = len(uow.devices.by_id)

        with self.assertRaises(ConflictError):
            await service.allocate_device_inventory_item(
                AllocateDeviceInventoryItemCommand(
                    inventory_item_id=item_id,
                    organization_id=VALID_ORG_ULID,
                    actor=make_actor(),
                ),
                uow=uow,
            )

        self.assertEqual(len(uow.devices.by_id), devices_before)


if __name__ == "__main__":
    unittest.main()
