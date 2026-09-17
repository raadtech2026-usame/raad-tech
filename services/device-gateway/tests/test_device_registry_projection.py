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

    def test_terminal_id_changed_reindexes_lookup_and_removes_stale_key(self) -> None:
        """The regression test for the actual production bug this feature fixes: before
        `DeviceTerminalIdChanged` existed, nothing ever re-indexed
        `_device_id_by_terminal_id` for an already-registered device, so a corrected terminal
        ID (however it was corrected) was permanently unresolvable by real JT/T 808 traffic."""
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "000000000014482607571"},
        )
        projection.apply_event(
            event_type="DeviceTerminalIdChanged",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={
                "old_terminal_id": "000000000014482607571",
                "new_terminal_id": "00000000014482607571",
            },
        )
        # The corrected value now resolves...
        record = projection.lookup_by_terminal_id("00000000014482607571")
        self.assertIsNotNone(record)
        self.assertEqual(record.device_id, DEVICE)
        # ...and the stale value no longer does, so the device is never resolvable under two
        # terminal IDs at once.
        self.assertIsNone(projection.lookup_by_terminal_id("000000000014482607571"))
        self.assertEqual(record.terminal_id, "00000000014482607571")

    def test_terminal_id_changed_for_unknown_device_is_safely_ignored(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceTerminalIdChanged",
            aggregate_id="never-registered",
            org_id=ORG,
            payload={"old_terminal_id": "A", "new_terminal_id": "B"},
        )  # must not raise
        self.assertEqual(len(projection), 0)

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

    def test_auth_code_issued_event_appends_auth_key_hash_on_existing_record(self) -> None:
        """P0 #2 fix: `DeviceAuthCodeIssued` (published by `TerminalRegistrationHandler` on every
        successful `0x0100`, `aggregate_id=device_id`) must now be applied by this projection, the
        same as every other device-lifecycle event — this is what lets `replay_from_start` recover
        previously-minted `auth_key_hashes` after a device-gateway restart."""
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        projection.apply_event(
            event_type="DeviceAuthCodeIssued",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"auth_key_hash": "pbkdf2_sha256$10000$salt$hash"},
        )
        record = projection.lookup_by_terminal_id("TERM-1")
        self.assertEqual(record.auth_key_hashes, ["pbkdf2_sha256$10000$salt$hash"])

    def test_auth_code_issued_event_for_unknown_device_is_safely_ignored(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceAuthCodeIssued",
            aggregate_id="never-registered",
            org_id=ORG,
            payload={"auth_key_hash": "pbkdf2_sha256$10000$salt$hash"},
        )  # must not raise
        self.assertEqual(len(projection), 0)

    def test_auth_code_issued_event_keeps_multiple_pending_hashes_bounded(self) -> None:
        """Production fix, 2026-09-15: a terminal that re-registers several times before ever
        completing `0x0102` must keep more than just the single most-recent hash pending — see
        `DeviceRecord.auth_key_hashes`'s own docstring for the live incident this closes — but
        the list is still bounded, oldest evicted first, not unbounded growth."""
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        for n in range(10):
            projection.apply_event(
                event_type="DeviceAuthCodeIssued",
                aggregate_id=DEVICE,
                org_id=ORG,
                payload={"auth_key_hash": f"hash-{n}"},
            )
        record = projection.lookup_by_terminal_id("TERM-1")
        self.assertEqual(len(record.auth_key_hashes), 8)
        # Oldest two (hash-0, hash-1) evicted; the most recent eight remain, in order.
        self.assertEqual(
            record.auth_key_hashes,
            ["hash-2", "hash-3", "hash-4", "hash-5", "hash-6", "hash-7", "hash-8", "hash-9"],
        )

    def test_repeated_auth_code_issued_event_is_stored_once(self) -> None:
        """This process reads its own `DeviceAuthCodeIssued` events back off `raad:events`, and a
        restart replays them again. Before the 2026-09-17 fix each mint was stored twice, so
        eight overlapping registrations could evict a code after only four."""
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        record = projection.lookup_by_terminal_id("TERM-1")
        record.add_auth_key_hash("hash-live")
        for _ in range(3):
            projection.apply_event(
                event_type="DeviceAuthCodeIssued",
                aggregate_id=DEVICE,
                org_id=ORG,
                payload={"auth_key_hash": "hash-live"},
            )
        self.assertEqual(record.auth_key_hashes, ["hash-live"])

    def test_mark_auth_key_hash_used_moves_it_to_the_most_recently_used_end(self) -> None:
        projection = DeviceRegistryProjection()
        projection.apply_event(
            event_type="DeviceRegistered",
            aggregate_id=DEVICE,
            org_id=ORG,
            payload={"terminal_id": "TERM-1", "serial_number": "00007"},
        )
        record = projection.lookup_by_terminal_id("TERM-1")
        for n in range(3):
            record.add_auth_key_hash(f"hash-{n}")

        record.mark_auth_key_hash_used("hash-0")
        record.mark_auth_key_hash_used("not-held")  # unknown hash: no-op, never inserted

        self.assertEqual(record.auth_key_hashes, ["hash-1", "hash-2", "hash-0"])

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
