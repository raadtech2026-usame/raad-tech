"""Domain-only tests for `fleet_device`'s `Vehicle`/`Device`/`Camera`/`DeviceAssignment`
aggregates. Stdlib `unittest` — no `pytest`, matching established precedent. Covers:
value-object validation, `Vehicle`/`Device`/`DeviceAssignment` invariants, the Device
lifecycle state machine's *illegal* transitions (Phase 2 §19.2 — a scope explicitly called out
by this phase's own task list), camera channel-uniqueness (intra-aggregate), and domain-event
emission.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from raad.core.errors.exceptions import ConflictError, DomainError, RuleViolationError
from raad.core.time.clock import Clock
from raad.modules.fleet_device.domain.entities import Device, DeviceAssignment, Vehicle
from raad.modules.fleet_device.domain.value_objects import (
    AssignmentId,
    CameraId,
    CameraPosition,
    DeviceId,
    DeviceLifecycleState,
    Msisdn,
    OrganizationId,
    TerminalId,
    VehicleId,
    VehicleStatus,
)

VALID_VEHICLE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MC"
VALID_DEVICE_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MD"
VALID_ORG_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3ME"
VALID_ASSIGNMENT_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MF"
VALID_CAMERA_ULID = "01J8Z3K9G6X8YV5T4N2R7QW3MG"


class FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


# --- Value objects ----------------------------------------------------------------------


class TerminalIdTests(unittest.TestCase):
    def test_rejects_empty(self) -> None:
        with self.assertRaises(DomainError):
            TerminalId("")

    def test_rejects_over_max_length(self) -> None:
        with self.assertRaises(DomainError):
            TerminalId("x" * 65)

    def test_accepts_valid_terminal_id(self) -> None:
        self.assertEqual(str(TerminalId("TERM-001")), "TERM-001")


class MsisdnTests(unittest.TestCase):
    def test_rejects_empty(self) -> None:
        with self.assertRaises(DomainError):
            Msisdn("")

    def test_masked_hides_all_but_last_four_digits(self) -> None:
        msisdn = Msisdn("+252700000000")
        self.assertTrue(msisdn.masked().endswith("0000"))
        self.assertNotIn("252700", msisdn.masked())

    def test_str_returns_full_value(self) -> None:
        msisdn = Msisdn("+252700000000")
        self.assertEqual(str(msisdn), "+252700000000")

    def test_repr_never_leaks_full_number(self) -> None:
        msisdn = Msisdn("+252700000000")
        self.assertNotIn("252700", repr(msisdn))


# --- Vehicle -----------------------------------------------------------------------------


class VehicleInvariantTests(unittest.TestCase):
    def test_rejects_empty_plate_no(self) -> None:
        with self.assertRaises(DomainError):
            Vehicle(
                id=VehicleId(VALID_VEHICLE_ULID),
                organization_id=OrganizationId(VALID_ORG_ULID),
                plate_no="",
                label=None,
                capacity=None,
                status=VehicleStatus.ACTIVE,
            )


class VehicleStatusTransitionTests(unittest.TestCase):
    def make_vehicle(self, status: VehicleStatus = VehicleStatus.ACTIVE) -> Vehicle:
        return Vehicle(
            id=VehicleId(VALID_VEHICLE_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            plate_no="ABC-123",
            label=None,
            capacity=None,
            status=status,
        )

    def test_register_starts_active_and_records_event(self) -> None:
        vehicle = Vehicle.register(
            id=VehicleId(VALID_VEHICLE_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            plate_no="ABC-123",
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(vehicle.status, VehicleStatus.ACTIVE)
        self.assertEqual(
            vehicle.pull_domain_events()[0].event_type, "VehicleRegistered"
        )

    def test_mark_under_maintenance_and_back_to_active(self) -> None:
        vehicle = self.make_vehicle(status=VehicleStatus.ACTIVE)
        vehicle.mark_under_maintenance(
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        )
        self.assertEqual(vehicle.status, VehicleStatus.MAINTENANCE)
        vehicle.activate(clock=FixedClock(datetime(2026, 1, 2, tzinfo=timezone.utc)))
        self.assertEqual(vehicle.status, VehicleStatus.ACTIVE)

    def test_deactivate_already_inactive_is_idempotent_no_op(self) -> None:
        vehicle = self.make_vehicle(status=VehicleStatus.INACTIVE)
        vehicle.deactivate(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(vehicle.pull_domain_events(), [])


# --- Device lifecycle state machine (Phase 2 §19.2) ---------------------------------------


class DeviceLifecycleTests(unittest.TestCase):
    def make_device(
        self, lifecycle_state: DeviceLifecycleState = DeviceLifecycleState.REGISTERED
    ) -> Device:
        return Device(
            id=DeviceId(VALID_DEVICE_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            terminal_id=TerminalId("TERM-001"),
            model=None,
            vendor=None,
            sim_msisdn=None,
            lifecycle_state=lifecycle_state,
            auth_key_hash=None,
            last_seen_at=None,
        )

    def test_register_starts_in_registered_state(self) -> None:
        device = Device.register(
            id=DeviceId(VALID_DEVICE_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            terminal_id=TerminalId("TERM-001"),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(device.lifecycle_state, DeviceLifecycleState.REGISTERED)

    def test_registered_to_activated_is_legal(self) -> None:
        device = self.make_device(DeviceLifecycleState.REGISTERED)
        device.activate(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(device.lifecycle_state, DeviceLifecycleState.ACTIVATED)

    def test_activate_already_activated_is_idempotent_no_op(self) -> None:
        device = self.make_device(DeviceLifecycleState.ACTIVATED)
        device.activate(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(device.pull_domain_events(), [])

    def test_suspend_from_assigned_is_illegal(self) -> None:
        """Regression: Phase 2 §19.2 draws Suspended reachable only from Activated, not
        Assigned - an assigned device must be unassigned first."""
        device = self.make_device(DeviceLifecycleState.ASSIGNED)
        with self.assertRaises(RuleViolationError):
            device.suspend(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))

    def test_suspend_from_registered_is_illegal(self) -> None:
        device = self.make_device(DeviceLifecycleState.REGISTERED)
        with self.assertRaises(RuleViolationError):
            device.suspend(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))

    def test_activated_to_suspended_to_activated_round_trip(self) -> None:
        device = self.make_device(DeviceLifecycleState.ACTIVATED)
        device.suspend(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(device.lifecycle_state, DeviceLifecycleState.SUSPENDED)
        device.reactivate(clock=FixedClock(datetime(2026, 1, 2, tzinfo=timezone.utc)))
        self.assertEqual(device.lifecycle_state, DeviceLifecycleState.ACTIVATED)

    def test_reactivate_from_registered_is_illegal(self) -> None:
        device = self.make_device(DeviceLifecycleState.REGISTERED)
        with self.assertRaises(RuleViolationError):
            device.reactivate(
                clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
            )

    def test_retire_from_registered_is_illegal(self) -> None:
        """Regression: Phase 2 §19.2 draws Retired reachable only from Assigned/Unassigned
        (i.e. Activated), not directly from Registered or Suspended."""
        device = self.make_device(DeviceLifecycleState.REGISTERED)
        with self.assertRaises(RuleViolationError):
            device.retire(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))

    def test_retire_from_suspended_is_illegal(self) -> None:
        device = self.make_device(DeviceLifecycleState.SUSPENDED)
        with self.assertRaises(RuleViolationError):
            device.retire(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))

    def test_retire_from_activated_is_legal_and_terminal(self) -> None:
        device = self.make_device(DeviceLifecycleState.ACTIVATED)
        device.retire(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(device.lifecycle_state, DeviceLifecycleState.RETIRED)

    def test_retire_from_assigned_is_legal(self) -> None:
        device = self.make_device(DeviceLifecycleState.ASSIGNED)
        device.retire(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(device.lifecycle_state, DeviceLifecycleState.RETIRED)

    def test_retire_already_retired_is_idempotent_no_op(self) -> None:
        device = self.make_device(DeviceLifecycleState.RETIRED)
        device.retire(clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(device.pull_domain_events(), [])

    def test_mark_assigned_requires_activated_state(self) -> None:
        device = self.make_device(DeviceLifecycleState.REGISTERED)
        with self.assertRaises(RuleViolationError):
            device.mark_assigned()

    def test_mark_assigned_from_activated_succeeds(self) -> None:
        device = self.make_device(DeviceLifecycleState.ACTIVATED)
        device.mark_assigned()
        self.assertEqual(device.lifecycle_state, DeviceLifecycleState.ASSIGNED)

    def test_mark_assigned_emits_no_event(self) -> None:
        """Regression: the assignment fact is emitted once, by DeviceAssignment.open - not
        duplicated here."""
        device = self.make_device(DeviceLifecycleState.ACTIVATED)
        device.mark_assigned()
        self.assertEqual(device.pull_domain_events(), [])

    def test_mark_unassigned_requires_assigned_state(self) -> None:
        device = self.make_device(DeviceLifecycleState.ACTIVATED)
        with self.assertRaises(RuleViolationError):
            device.mark_unassigned()


class CameraRegistrationTests(unittest.TestCase):
    def make_activated_device(self) -> Device:
        return Device(
            id=DeviceId(VALID_DEVICE_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            terminal_id=TerminalId("TERM-001"),
            model=None,
            vendor=None,
            sim_msisdn=None,
            lifecycle_state=DeviceLifecycleState.ACTIVATED,
            auth_key_hash=None,
            last_seen_at=None,
        )

    def test_register_camera_on_free_channel_succeeds(self) -> None:
        device = self.make_activated_device()
        camera = device.register_camera(
            id=CameraId(VALID_CAMERA_ULID),
            channel_no=1,
            position=CameraPosition.ROAD_FACING,
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertIn(camera, device.cameras)
        self.assertEqual(device.pull_domain_events()[0].event_type, "CameraRegistered")

    def test_register_camera_on_occupied_channel_raises_conflict(self) -> None:
        """Regression: Database Design §5.3's ux_cameras__device_channel - one camera per
        channel per device, an intra-aggregate invariant enforced without I/O."""
        device = self.make_activated_device()
        device.register_camera(
            id=CameraId(VALID_CAMERA_ULID),
            channel_no=1,
            position=CameraPosition.ROAD_FACING,
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        with self.assertRaises(ConflictError):
            device.register_camera(
                id=CameraId("01J8Z3K9G6X8YV5T4N2R7QW3MH"),
                channel_no=1,
                position=CameraPosition.IN_CABIN,
                clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
            )
        self.assertEqual(len(device.cameras), 1)

    def test_register_cameras_on_different_channels_both_succeed(self) -> None:
        device = self.make_activated_device()
        device.register_camera(
            id=CameraId(VALID_CAMERA_ULID),
            channel_no=1,
            position=CameraPosition.ROAD_FACING,
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        device.register_camera(
            id=CameraId("01J8Z3K9G6X8YV5T4N2R7QW3MH"),
            channel_no=2,
            position=CameraPosition.IN_CABIN,
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertEqual(len(device.cameras), 2)

    def test_cameras_property_is_read_only_tuple(self) -> None:
        device = self.make_activated_device()
        self.assertIsInstance(device.cameras, tuple)


# --- DeviceAssignment ----------------------------------------------------------------------


class DeviceAssignmentTests(unittest.TestCase):
    def test_open_creates_active_assignment_and_records_event(self) -> None:
        assignment = DeviceAssignment.open(
            id=AssignmentId(VALID_ASSIGNMENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            device_id=DeviceId(VALID_DEVICE_ULID),
            vehicle_id=VehicleId(VALID_VEHICLE_ULID),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertTrue(assignment.is_active)
        self.assertIsNone(assignment.unassigned_at)
        self.assertEqual(
            assignment.pull_domain_events()[0].event_type, "DeviceAssignedToVehicle"
        )

    def test_close_sets_unassigned_at_and_is_active_becomes_false(self) -> None:
        assignment = DeviceAssignment.open(
            id=AssignmentId(VALID_ASSIGNMENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            device_id=DeviceId(VALID_DEVICE_ULID),
            vehicle_id=VehicleId(VALID_VEHICLE_ULID),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        assignment.pull_domain_events()
        assignment.close(clock=FixedClock(datetime(2026, 1, 2, tzinfo=timezone.utc)))
        self.assertFalse(assignment.is_active)
        self.assertIsNotNone(assignment.unassigned_at)
        self.assertEqual(
            assignment.pull_domain_events()[0].event_type, "DeviceUnassignedFromVehicle"
        )

    def test_close_already_closed_assignment_is_idempotent_no_op(self) -> None:
        """Regression: reassignment retries must be safe - closing twice must not overwrite
        the original unassigned_at or emit a second event."""
        assignment = DeviceAssignment.open(
            id=AssignmentId(VALID_ASSIGNMENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            device_id=DeviceId(VALID_DEVICE_ULID),
            vehicle_id=VehicleId(VALID_VEHICLE_ULID),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        first_close_time = datetime(2026, 1, 2, tzinfo=timezone.utc)
        assignment.close(clock=FixedClock(first_close_time))
        assignment.pull_domain_events()
        assignment.close(clock=FixedClock(datetime(2026, 1, 5, tzinfo=timezone.utc)))
        self.assertEqual(assignment.unassigned_at, first_close_time)
        self.assertEqual(assignment.pull_domain_events(), [])

    def test_driver_is_deliberately_absent_from_assignment(self) -> None:
        """Regression: device != driver (Phase 2 §19.1) - DeviceAssignment must carry no
        driver-related attribute."""
        assignment = DeviceAssignment.open(
            id=AssignmentId(VALID_ASSIGNMENT_ULID),
            organization_id=OrganizationId(VALID_ORG_ULID),
            device_id=DeviceId(VALID_DEVICE_ULID),
            vehicle_id=VehicleId(VALID_VEHICLE_ULID),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        )
        self.assertFalse(hasattr(assignment, "driver_id"))
        self.assertFalse(hasattr(assignment, "driver"))


if __name__ == "__main__":
    unittest.main()
