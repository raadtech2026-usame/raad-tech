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
from datetime import datetime, timezone

from raad.core.errors.exceptions import ConflictError, NotFoundError
from raad.core.ids.generator import IdGenerator
from raad.core.tenancy.principal import Principal, Role
from raad.core.time.clock import Clock
from raad.modules.fleet_device.application.commands import (
    ActivateDeviceCommand,
    ActivateVehicleCommand,
    AssignDeviceToVehicleCommand,
    ReassignDeviceCommand,
    RegisterCameraCommand,
    RegisterDeviceCommand,
    RegisterVehicleCommand,
    RetireDeviceCommand,
    SuspendDeviceCommand,
    UnassignDeviceCommand,
)
from raad.modules.fleet_device.application.ports import FleetDeviceUnitOfWork
from raad.modules.fleet_device.application.queries import GetDeviceByIdQuery
from raad.modules.fleet_device.application.services import (
    DeviceApplicationService,
    VehicleApplicationService,
)
from raad.modules.fleet_device.domain.entities import Device, DeviceAssignment, Vehicle
from raad.modules.fleet_device.domain.repositories import (
    DeviceAssignmentRepository,
    DeviceRepository,
    VehicleRepository,
)
from raad.modules.fleet_device.domain.value_objects import (
    AssignmentId,
    CameraPosition,
    DeviceId,
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

    def add(self, device: Device) -> None:
        self.by_id[str(device.id)] = device

    async def list_all(self) -> list[Device]:
        return list(self.by_id.values())


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


class FakeFleetDeviceUnitOfWork(FleetDeviceUnitOfWork):
    def __init__(
        self,
        vehicles: InMemoryVehicleRepository,
        devices: InMemoryDeviceRepository,
        device_assignments: InMemoryDeviceAssignmentRepository,
    ) -> None:
        self.vehicles = vehicles
        self.devices = devices
        self.device_assignments = device_assignments
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


async def _register_vehicle(vehicle_service, uow, plate_no="ABC-123") -> str:
    dto = await vehicle_service.register_vehicle(
        RegisterVehicleCommand(
            organization_id=VALID_ORG_ULID,
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
    device_service, uow, terminal_id="TERM-001"
) -> str:
    dto = await device_service.register_device(
        RegisterDeviceCommand(
            organization_id=VALID_ORG_ULID,
            terminal_id=terminal_id,
            model=None,
            vendor=None,
            sim_msisdn=None,
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


if __name__ == "__main__":
    unittest.main()
