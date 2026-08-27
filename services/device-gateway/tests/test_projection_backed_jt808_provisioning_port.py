"""`ProjectionBackedJt808ProvisioningPort` tests — the real (non-interim) JT808 identity/
provisioning port, backed directly by a `DeviceRegistryProjection` instance. Mirrors
`test_projection_backed_provisioning_port.py` (the LSZ equivalent) exactly, plus the JT808-
specific rejection paths (retired, activated-but-unassigned) that file's own suite doesn't need
to enumerate separately.

**`verify_auth_code`'s real semantics are now resolved and tested (ADR-0025 §3)** — the earlier
three-way conflict (JT808 Technical Design, the primary JT/T 808 spec, Backend LLD) is resolved
in favor of the platform-issued/echoed-back model: `authorize_registration` mints and hashes a
fresh code on every `SUCCESS`, `verify_auth_code` checks a presented code against that hash. This
suite covers the full mint -> verify round trip, a wrong code failing closed, and a terminal that
was never registered through this port (no `auth_key_hash` minted yet) also failing closed.
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

    async def test_success_mints_a_fresh_auth_code_and_its_hash(self) -> None:
        """ADR-0025 §3: a successful registration mints a plaintext code (for the `0x8100` wire
        response) and its hash (`RegistrationAuthorization.auth_key_hash`, for the
        `DeviceAuthCodeIssued` event) — never `None` for either on `SUCCESS`."""
        port = ProjectionBackedJt808ProvisioningPort(_provisionable_projection())
        result = await port.authorize_registration(
            terminal_phone="013800138000", request=None
        )
        self.assertIsNotNone(result.auth_code)
        self.assertIsNotNone(result.auth_key_hash)
        self.assertNotEqual(result.auth_code, result.auth_key_hash)

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

    async def test_verify_auth_code_with_the_correct_minted_code_succeeds(self) -> None:
        """ADR-0025 §3's full mint -> verify round trip: the plaintext code
        `authorize_registration` returned is exactly what a real terminal echoes back on
        `0x0102`, and it must verify successfully against the hash minted moments before."""
        port = ProjectionBackedJt808ProvisioningPort(_provisionable_projection())
        registration = await port.authorize_registration(
            terminal_phone="013800138000", request=None
        )

        result = await port.verify_auth_code(
            terminal_phone="013800138000", auth_code=registration.auth_code
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.device_id, "device-1")
        self.assertEqual(result.vehicle_id, "vehicle-1")
        self.assertEqual(result.organization_id, "org-1")

    async def test_verify_auth_code_with_the_wrong_code_fails_closed(self) -> None:
        port = ProjectionBackedJt808ProvisioningPort(_provisionable_projection())
        await port.authorize_registration(terminal_phone="013800138000", request=None)

        result = await port.verify_auth_code(
            terminal_phone="013800138000", auth_code="WRONG-CODE"
        )

        self.assertFalse(result.is_valid)

    async def test_verify_auth_code_before_any_registration_fails_closed(self) -> None:
        """A terminal never seen by `authorize_registration` has no `auth_key_hash` minted yet —
        must fail closed, not raise."""
        port = ProjectionBackedJt808ProvisioningPort(_provisionable_projection())
        result = await port.verify_auth_code(
            terminal_phone="013800138000", auth_code="ANYTHING"
        )
        self.assertFalse(result.is_valid)

    async def test_verify_auth_code_for_unknown_terminal_fails_closed(self) -> None:
        port = ProjectionBackedJt808ProvisioningPort(_provisionable_projection())
        result = await port.verify_auth_code(
            terminal_phone="never-seen", auth_code="ANYTHING"
        )
        self.assertFalse(result.is_valid)

    async def test_verify_auth_code_succeeds_after_projection_replay_simulating_a_restart(
        self,
    ) -> None:
        """P0 #2 regression test: before this fix, `auth_key_hash` was never fed by a broker
        event, so a device-gateway restart between a device's `0x0100` and its next `0x0102`
        (an *ordinary* reconnect, which does not resend `0x0100` -- see this port's own
        docstring) always failed authentication, unrecoverable short of a factory reset. This
        reproduces that restart by minting a code against one projection/port pair, then
        replaying the resulting `DeviceAuthCodeIssued` event (exactly as
        `RedisDeviceRegistryConsumer.replay_from_start` would on a fresh process) onto a second,
        independent projection/port pair standing in for the restarted process, and verifying
        against a *third*, freshly-constructed port bound to that second projection -- proving
        the hash is recoverable from the projection alone, not from any port-instance state."""
        pre_restart_port = ProjectionBackedJt808ProvisioningPort(_provisionable_projection())
        registration = await pre_restart_port.authorize_registration(
            terminal_phone="013800138000", request=None
        )
        self.assertEqual(registration.result, RegistrationResult.SUCCESS)

        # The restarted process: a brand-new projection, rebuilt the same way
        # `replay_from_start` rebuilds every other field -- by re-applying the device's
        # lifecycle events plus the `DeviceAuthCodeIssued` event this registration just caused.
        post_restart_projection = _provisionable_projection()
        post_restart_projection.apply_event(
            event_type="DeviceAuthCodeIssued",
            aggregate_id=registration.device_id,
            org_id="org-1",
            payload={"auth_key_hash": registration.auth_key_hash},
        )

        post_restart_port = ProjectionBackedJt808ProvisioningPort(post_restart_projection)
        result = await post_restart_port.verify_auth_code(
            terminal_phone="013800138000", auth_code=registration.auth_code
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.device_id, "device-1")


if __name__ == "__main__":
    unittest.main()
