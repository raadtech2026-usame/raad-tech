"""`ProjectionBackedMdvrProvisioningPort` tests — the real (non-interim) LSZ provisioning port,
backed directly by a `DeviceRegistryProjection` instance."""

import unittest

from src.registry.device_registry_projection import DeviceRegistryProjection
from src.vendors.lsz.handlers.provisioning_port import (
    MdvrRegistrationResult,
    ProjectionBackedMdvrProvisioningPort,
)


def _provisionable_projection() -> DeviceRegistryProjection:
    projection = DeviceRegistryProjection()
    projection.apply_event(
        event_type="DeviceRegistered",
        aggregate_id="device-1",
        org_id="org-1",
        payload={"terminal_id": "TERM-1", "serial_number": "00007"},
    )
    projection.apply_event(
        event_type="DeviceActivated", aggregate_id="device-1", org_id="org-1", payload={}
    )
    projection.apply_event(
        event_type="DeviceAssignedToVehicle",
        aggregate_id="assignment-1",
        org_id="org-1",
        payload={"device_id": "device-1", "vehicle_id": "vehicle-1"},
    )
    return projection


class ProjectionBackedMdvrProvisioningPortTests(unittest.IsolatedAsyncioTestCase):
    async def test_provisionable_device_authorizes_successfully(self) -> None:
        port = ProjectionBackedMdvrProvisioningPort(_provisionable_projection())
        result = await port.authorize_registration(device_serial_number="00007")
        self.assertEqual(result.result, MdvrRegistrationResult.SUCCESS)
        self.assertEqual(result.device_id, "device-1")
        self.assertEqual(result.vehicle_id, "vehicle-1")
        self.assertEqual(result.organization_id, "org-1")

    async def test_unknown_serial_number_is_rejected(self) -> None:
        port = ProjectionBackedMdvrProvisioningPort(_provisionable_projection())
        result = await port.authorize_registration(device_serial_number="never-seen")
        self.assertEqual(result.result, MdvrRegistrationResult.UNKNOWN_DEVICE)

    async def test_registered_but_not_activated_device_is_rejected(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id="device-1",
            org_id="org-1",
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        port = ProjectionBackedMdvrProvisioningPort(projection)
        result = await port.authorize_registration(device_serial_number="00007")
        self.assertEqual(result.result, MdvrRegistrationResult.UNKNOWN_DEVICE)

    async def test_suspended_device_is_rejected(self) -> None:
        projection = _provisionable_projection()
        projection.apply_event(
            event_type="DeviceSuspended", aggregate_id="device-1", org_id="org-1", payload={}
        )
        port = ProjectionBackedMdvrProvisioningPort(projection)
        result = await port.authorize_registration(device_serial_number="00007")
        self.assertEqual(result.result, MdvrRegistrationResult.UNKNOWN_DEVICE)


if __name__ == "__main__":
    unittest.main()
