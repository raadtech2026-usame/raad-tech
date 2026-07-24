"""`DeviceRegistryProjection` tests — event application order, both identity indexes
(terminal_id/serial_number), the activation/assignment join condition, and safe handling of
events referencing a device this projection has never seen `DeviceRegistered` for.
"""

import unittest

from src.registry.device_registry_projection import DeviceRegistryProjection

ORG = "org-1"
DEVICE = "device-1"


class DeviceRegistryProjectionTests(unittest.TestCase):
    def test_registered_device_is_not_yet_provisionable(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        record = projection.lookup_by_serial_number("00007")
        self.assertIsNotNone(record)
        self.assertFalse(record.is_provisionable)  # not active, no vehicle yet

    def test_lookup_by_terminal_id_and_serial_number_both_resolve(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        self.assertIs(
            projection.lookup_by_terminal_id("TERM-1"),
            projection.lookup_by_serial_number("00007"),
        )

    def test_activated_and_assigned_device_is_provisionable(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        projection.apply_event(
            event_type="DeviceActivated", aggregate_id=DEVICE, org_id=ORG, payload={}
        )
        projection.apply_event(
            event_type="DeviceAssignedToVehicle",
            aggregate_id="assignment-1",
            org_id=ORG,
            payload={"device_id": DEVICE, "vehicle_id": "vehicle-1"},
        )
        record = projection.lookup_by_serial_number("00007")
        self.assertTrue(record.is_provisionable)
        self.assertEqual(record.vehicle_id, "vehicle-1")

    def test_suspended_device_is_no_longer_provisionable(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        projection.apply_event(
            event_type="DeviceActivated", aggregate_id=DEVICE, org_id=ORG, payload={}
        )
        projection.apply_event(
            event_type="DeviceAssignedToVehicle",
            aggregate_id="assignment-1",
            org_id=ORG,
            payload={"device_id": DEVICE, "vehicle_id": "vehicle-1"},
        )
        projection.apply_event(
            event_type="DeviceSuspended", aggregate_id=DEVICE, org_id=ORG, payload={}
        )
        self.assertFalse(projection.lookup_by_serial_number("00007").is_provisionable)

    def test_unassigned_device_is_no_longer_provisionable(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        projection.apply_event(
            event_type="DeviceActivated", aggregate_id=DEVICE, org_id=ORG, payload={}
        )
        projection.apply_event(
            event_type="DeviceAssignedToVehicle",
            aggregate_id="assignment-1",
            org_id=ORG,
            payload={"device_id": DEVICE, "vehicle_id": "vehicle-1"},
        )
        projection.apply_event(
            event_type="DeviceUnassignedFromVehicle",
            aggregate_id="assignment-1",
            org_id=ORG,
            payload={"device_id": DEVICE, "vehicle_id": "vehicle-1"},
        )
        record = projection.lookup_by_serial_number("00007")
        self.assertIsNone(record.vehicle_id)
        self.assertFalse(record.is_provisionable)

    def test_reassigned_device_updates_vehicle_id_via_aggregate_id(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        projection.apply_event(
            event_type="DeviceActivated", aggregate_id=DEVICE, org_id=ORG, payload={}
        )
        projection.apply_event(
            event_type="DeviceReassigned",
            aggregate_id=DEVICE,  # DeviceReassigned's aggregate_id IS the device_id
            org_id=ORG,
            payload={"old_vehicle_id": "vehicle-1", "new_vehicle_id": "vehicle-2"},
        )
        self.assertEqual(
            projection.lookup_by_serial_number("00007").vehicle_id, "vehicle-2"
        )

    def test_event_for_unknown_device_is_safely_ignored(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceActivated",
            aggregate_id="never-registered",
            org_id=ORG,
            payload={},
        )  # must not raise
        self.assertEqual(len(projection), 0)

    def test_unknown_identity_lookup_returns_none(self) -> None:
        projection = DeviceRegistryProjection()
        self.assertIsNone(projection.lookup_by_terminal_id("nope"))
        self.assertIsNone(projection.lookup_by_serial_number("nope"))

    def test_reactivate_after_suspend_restores_provisionability(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        projection.apply_event(
            event_type="DeviceAssignedToVehicle",
            aggregate_id="assignment-1",
            org_id=ORG,
            payload={"device_id": DEVICE, "vehicle_id": "vehicle-1"},
        )
        projection.apply_event(
            event_type="DeviceActivated", aggregate_id=DEVICE, org_id=ORG, payload={}
        )
        projection.apply_event(
            event_type="DeviceSuspended", aggregate_id=DEVICE, org_id=ORG, payload={}
        )
        projection.apply_event(
            event_type="DeviceReactivated", aggregate_id=DEVICE, org_id=ORG, payload={}
        )
        self.assertTrue(projection.lookup_by_serial_number("00007").is_provisionable)


if __name__ == "__main__":
    unittest.main()
