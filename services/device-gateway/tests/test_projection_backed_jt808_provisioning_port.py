"""`ProjectionBackedJt808ProvisioningPort` tests — the real (non-interim) JT808 identity/
provisioning port, backed directly by a `DeviceRegistryProjection` instance. Mirrors
`test_projection_backed_provisioning_port.py` (the LSZ equivalent) exactly, plus the JT808-
specific rejection paths (retired, activated-but-unassigned) that file's own suite doesn't need
to enumerate separately.

**Does not test `verify_auth_code`'s real semantics** — it has none yet, deliberately: JT808
Technical Design, the primary JT/T 808-2013 spec's own text, and Backend LLD describe three
different, mutually exclusive auth-code mechanisms, and the repository does not contain enough
authoritative information to pick one (see `provisioning_port.py`'s own class-level docstring).
The one test here for `verify_auth_code` documents that deliberate, fail-closed gap — it is not a
placeholder for future real coverage of a *guessed* mechanism.
"""

import unittest

from src.registry.device_registry_projection import DeviceRegistryProjection
from src.vendors.jt808.handlers.provisioning_port import (
    ProjectionBackedJt808ProvisioningPort,
    RegistrationResult,
)


def _provisionable_projection() -> DeviceRegistryProjection:
    projection = DeviceRegistryProjection()
    projection.apply_event(
        event_type="DeviceRegistered",
        aggregate_id="device-1",
        org_id="org-1",
        payload={"terminal_id": "013800138000", "serial_number": "00007"},
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


class ProjectionBackedJt808ProvisioningPortTests(unittest.IsolatedAsyncioTestCase):
    async def test_provisionable_device_authorizes_successfully(self) -> None:
        port = ProjectionBackedJt808ProvisioningPort(_provisionable_projection())
        result = await port.authorize_registration(
            terminal_phone="013800138000", request=None
        )
        self.assertEqual(result.result, RegistrationResult.SUCCESS)
        self.assertEqual(result.device_id, "device-1")
        self.assertEqual(result.vehicle_id, "vehicle-1")
        self.assertEqual(result.organization_id, "org-1")

    async def test_success_never_fabricates_an_auth_code(self) -> None:
        """The deliberate authentication blocker — see module/class docstring. `auth_code` must
        stay `None` here, never a guessed value, until the supplier's JT808 documentation
        resolves which of the three documented mechanisms RAAD's terminals actually use."""
        port = ProjectionBackedJt808ProvisioningPort(_provisionable_projection())
        result = await port.authorize_registration(
            terminal_phone="013800138000", request=None
        )
        self.assertIsNone(result.auth_code)

    async def test_unknown_terminal_id_is_rejected(self) -> None:
        port = ProjectionBackedJt808ProvisioningPort(_provisionable_projection())
        result = await port.authorize_registration(
            terminal_phone="never-seen", request=None
        )
        self.assertEqual(result.result, RegistrationResult.TERMINAL_NOT_FOUND)
        self.assertIsNone(result.device_id)
        self.assertIsNone(result.vehicle_id)
        self.assertIsNone(result.organization_id)

    async def test_registered_but_not_activated_device_is_rejected(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id="device-1",
            org_id="org-1",
            payload={"terminal_id": "013800138000", "serial_number": "00007"},
        )
        port = ProjectionBackedJt808ProvisioningPort(projection)
        result = await port.authorize_registration(
            terminal_phone="013800138000", request=None
        )
        self.assertEqual(result.result, RegistrationResult.TERMINAL_NOT_FOUND)

    async def test_activated_but_unassigned_device_is_rejected(self) -> None:
        """Active, but never assigned to a vehicle — `is_provisionable` requires both."""
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id="device-1",
            org_id="org-1",
            payload={"terminal_id": "013800138000", "serial_number": "00007"},
        )
        projection.apply_event(
            event_type="DeviceActivated", aggregate_id="device-1", org_id="org-1", payload={}
        )
        port = ProjectionBackedJt808ProvisioningPort(projection)
        result = await port.authorize_registration(
            terminal_phone="013800138000", request=None
        )
        self.assertEqual(result.result, RegistrationResult.TERMINAL_NOT_FOUND)

    async def test_suspended_device_is_rejected(self) -> None:
        projection = _provisionable_projection()
        projection.apply_event(
            event_type="DeviceSuspended", aggregate_id="device-1", org_id="org-1", payload={}
        )
        port = ProjectionBackedJt808ProvisioningPort(projection)
        result = await port.authorize_registration(
            terminal_phone="013800138000", request=None
        )
        self.assertEqual(result.result, RegistrationResult.TERMINAL_NOT_FOUND)

    async def test_retired_device_is_rejected(self) -> None:
        projection = _provisionable_projection()
        projection.apply_event(
            event_type="DeviceRetired", aggregate_id="device-1", org_id="org-1", payload={}
        )
        port = ProjectionBackedJt808ProvisioningPort(projection)
        result = await port.authorize_registration(
            terminal_phone="013800138000", request=None
        )
        self.assertEqual(result.result, RegistrationResult.TERMINAL_NOT_FOUND)

    async def test_terminal_id_resolves_to_the_correct_organization_and_vehicle(self) -> None:
        """Two distinct provisioned devices, two distinct terminal_ids -- each must resolve to
        its own organization/vehicle, never the other's."""
        projection = DeviceRegistryProjection()
        for n, (device_id, terminal_id, org_id, vehicle_id) in enumerate(
            [
                ("device-A", "013800000001", "org-A", "vehicle-A"),
                ("device-B", "013800000002", "org-B", "vehicle-B"),
            ]
        ):
            projection.apply_event(
                event_type="DeviceRegistered",
                aggregate_id=device_id,
                org_id=org_id,
                payload={"terminal_id": terminal_id, "serial_number": f"SN-{n}"},
            )
            projection.apply_event(
                event_type="DeviceActivated", aggregate_id=device_id, org_id=org_id, payload={}
            )
            projection.apply_event(
                event_type="DeviceAssignedToVehicle",
                aggregate_id=f"assignment-{n}",
                org_id=org_id,
                payload={"device_id": device_id, "vehicle_id": vehicle_id},
            )

        port = ProjectionBackedJt808ProvisioningPort(projection)

        result_a = await port.authorize_registration(
            terminal_phone="013800000001", request=None
        )
        self.assertEqual(result_a.organization_id, "org-A")
        self.assertEqual(result_a.vehicle_id, "vehicle-A")

        result_b = await port.authorize_registration(
            terminal_phone="013800000002", request=None
        )
        self.assertEqual(result_b.organization_id, "org-B")
        self.assertEqual(result_b.vehicle_id, "vehicle-B")

    async def test_verify_auth_code_is_deliberately_unresolved_and_always_fails_closed(
        self,
    ) -> None:
        """Not a bug, not a placeholder for guessed logic — see class docstring. Must stay
        fail-closed until the supplier's JT808 documentation resolves the auth-code mechanism."""
        port = ProjectionBackedJt808ProvisioningPort(_provisionable_projection())
        result = await port.verify_auth_code(
            terminal_phone="013800138000", auth_code="ANYTHING"
        )
        self.assertFalse(result.is_valid)


if __name__ == "__main__":
    unittest.main()
