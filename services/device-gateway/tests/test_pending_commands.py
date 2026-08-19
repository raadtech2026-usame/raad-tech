"""`PendingCommandTracker` tests (`commands/pending_commands.py`) — correlation-ID bookkeeping
per `jt808.md` #6, including the bounded-timeout sweep (ADR-0024 §16)."""

import time
import unittest

from src.vendors.jt808.commands.pending_commands import PendingCommandTracker


class PendingCommandTrackerTests(unittest.TestCase):
    def test_register_then_resolve_returns_the_same_command(self) -> None:
        tracker = PendingCommandTracker()
        tracker.register(
            terminal_id="T1",
            message_id=0x9101,
            serial_no=5,
            correlation_id="corr-1",
            device_id="device-1",
            vehicle_id="vehicle-1",
            organization_id="org-1",
            timeout_seconds=30.0,
        )

        resolved = tracker.resolve(terminal_id="T1", message_id=0x9101, serial_no=5)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.correlation_id, "corr-1")
        self.assertEqual(resolved.device_id, "device-1")
        self.assertEqual(len(tracker), 0)  # resolve() pops the entry

    def test_resolve_returns_none_for_unknown_triple(self) -> None:
        tracker = PendingCommandTracker()
        self.assertIsNone(
            tracker.resolve(terminal_id="unknown", message_id=0x9101, serial_no=1)
        )

    def test_different_message_ids_on_the_same_terminal_do_not_collide(self) -> None:
        tracker = PendingCommandTracker()
        tracker.register(
            terminal_id="T1",
            message_id=0x9101,
            serial_no=1,
            correlation_id="live",
            device_id=None,
            vehicle_id=None,
            organization_id=None,
            timeout_seconds=30.0,
        )
        tracker.register(
            terminal_id="T1",
            message_id=0x9201,
            serial_no=1,
            correlation_id="playback",
            device_id=None,
            vehicle_id=None,
            organization_id=None,
            timeout_seconds=30.0,
        )

        self.assertEqual(
            tracker.resolve(terminal_id="T1", message_id=0x9101, serial_no=1).correlation_id,
            "live",
        )
        self.assertEqual(
            tracker.resolve(terminal_id="T1", message_id=0x9201, serial_no=1).correlation_id,
            "playback",
        )

    def test_sweep_expired_removes_and_returns_only_timed_out_entries(self) -> None:
        tracker = PendingCommandTracker()
        tracker.register(
            terminal_id="T1",
            message_id=0x9101,
            serial_no=1,
            correlation_id="expires-fast",
            device_id=None,
            vehicle_id=None,
            organization_id=None,
            timeout_seconds=0.01,
        )
        tracker.register(
            terminal_id="T2",
            message_id=0x9101,
            serial_no=1,
            correlation_id="stays-pending",
            device_id=None,
            vehicle_id=None,
            organization_id=None,
            timeout_seconds=60.0,
        )

        time.sleep(0.05)
        expired = tracker.sweep_expired()

        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0].correlation_id, "expires-fast")
        self.assertEqual(len(tracker), 1)  # the still-pending entry survives
        self.assertIsNotNone(
            tracker.resolve(terminal_id="T2", message_id=0x9101, serial_no=1)
        )

    def test_sweep_expired_is_a_no_op_when_nothing_has_timed_out(self) -> None:
        tracker = PendingCommandTracker()
        tracker.register(
            terminal_id="T1",
            message_id=0x9101,
            serial_no=1,
            correlation_id="fresh",
            device_id=None,
            vehicle_id=None,
            organization_id=None,
            timeout_seconds=60.0,
        )
        self.assertEqual(tracker.sweep_expired(), [])
        self.assertEqual(len(tracker), 1)

    def test_resolve_by_terminal_and_message_ignores_serial_no(self) -> None:
        # ADR-0030: 0x1003 carries no serial-number echo, so this lookup matches on
        # (terminal_id, message_id) alone, regardless of whatever serial_no register() used.
        tracker = PendingCommandTracker()
        tracker.register(
            terminal_id="T1",
            message_id=0x9003,
            serial_no=42,
            correlation_id="corr-1",
            device_id="device-1",
            vehicle_id=None,
            organization_id=None,
            timeout_seconds=30.0,
        )

        resolved = tracker.resolve_by_terminal_and_message(
            terminal_id="T1", message_id=0x9003
        )

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.correlation_id, "corr-1")
        self.assertEqual(len(tracker), 0)  # pops the entry, same as resolve()

    def test_resolve_by_terminal_and_message_returns_none_when_nothing_pending(self) -> None:
        tracker = PendingCommandTracker()
        self.assertIsNone(
            tracker.resolve_by_terminal_and_message(terminal_id="T1", message_id=0x9003)
        )

    def test_resolve_by_terminal_and_message_does_not_match_a_different_message_id(
        self,
    ) -> None:
        tracker = PendingCommandTracker()
        tracker.register(
            terminal_id="T1",
            message_id=0x9205,
            serial_no=1,
            correlation_id="wrong-family",
            device_id=None,
            vehicle_id=None,
            organization_id=None,
            timeout_seconds=30.0,
        )

        self.assertIsNone(
            tracker.resolve_by_terminal_and_message(terminal_id="T1", message_id=0x9003)
        )
        self.assertEqual(len(tracker), 1)  # untouched


if __name__ == "__main__":
    unittest.main()
