"""Subpackage reassembly tests (Phase 9.3; JT/T 808-2013 §4.4.3 Table 3)."""

import unittest

from src.protocol.exceptions import ReassemblyOverflowError
from src.protocol.reassembly import MessageReassembler


class MessageReassemblerTests(unittest.TestCase):
    def test_incomplete_returns_none(self) -> None:
        r = MessageReassembler()
        result = r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=3,
            package_sequence=1,
            body=b"a",
        )
        self.assertIsNone(result)
        self.assertEqual(len(r), 1)

    def test_complete_in_order_reassembles(self) -> None:
        r = MessageReassembler()
        r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=3,
            package_sequence=1,
            body=b"aa",
        )
        r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=3,
            package_sequence=2,
            body=b"bb",
        )
        result = r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=3,
            package_sequence=3,
            body=b"cc",
        )
        self.assertEqual(result, b"aabbcc")
        self.assertEqual(len(r), 0)  # cleaned up once complete

    def test_complete_out_of_order_reassembles_in_sequence_order(self) -> None:
        r = MessageReassembler()
        r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=3,
            package_sequence=3,
            body=b"cc",
        )
        r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=3,
            package_sequence=1,
            body=b"aa",
        )
        result = r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=3,
            package_sequence=2,
            body=b"bb",
        )
        self.assertEqual(
            result, b"aabbcc"
        )  # ordered by package_sequence, not arrival order

    def test_duplicate_package_sequence_overwrites(self) -> None:
        r = MessageReassembler()
        r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=2,
            package_sequence=1,
            body=b"aa",
        )
        r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=2,
            package_sequence=1,
            body=b"AA",
        )
        result = r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=2,
            package_sequence=2,
            body=b"bb",
        )
        self.assertEqual(result, b"AAbb")

    def test_distinct_terminals_do_not_interfere(self) -> None:
        r = MessageReassembler()
        r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=2,
            package_sequence=1,
            body=b"a",
        )
        r.add_part(
            terminal_id="T2",
            message_id=0x0200,
            total_packages=2,
            package_sequence=1,
            body=b"x",
        )
        self.assertEqual(len(r), 2)

    def test_changed_total_packages_replaces_pending(self) -> None:
        r = MessageReassembler()
        r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=5,
            package_sequence=1,
            body=b"old",
        )
        # A fresh submission with a different total_packages replaces the stale one.
        result = r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=2,
            package_sequence=1,
            body=b"new",
        )
        self.assertIsNone(result)
        result = r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=2,
            package_sequence=2,
            body=b"!!",
        )
        self.assertEqual(result, b"new!!")

    def test_overflow_raises(self) -> None:
        r = MessageReassembler(max_pending=2)
        r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=2,
            package_sequence=1,
            body=b"a",
        )
        r.add_part(
            terminal_id="T2",
            message_id=0x0200,
            total_packages=2,
            package_sequence=1,
            body=b"a",
        )
        with self.assertRaises(ReassemblyOverflowError):
            r.add_part(
                terminal_id="T3",
                message_id=0x0200,
                total_packages=2,
                package_sequence=1,
                body=b"a",
            )

    def test_sweep_expired_evicts_stale_entries(self) -> None:
        r = MessageReassembler()
        r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=3,
            package_sequence=1,
            body=b"a",
        )
        # A negative timeout guarantees "already expired" regardless of how little real time
        # elapsed between add_part() and sweep_expired() - avoids flaking on coarse timer
        # resolution (the same class of issue fixed in Phase 9.1/9.2's tests).
        evicted = r.sweep_expired(timeout_seconds=-1.0)
        self.assertEqual(evicted, [("T1", 0x0200)])
        self.assertEqual(len(r), 0)

    def test_sweep_does_not_evict_fresh_entries(self) -> None:
        r = MessageReassembler()
        r.add_part(
            terminal_id="T1",
            message_id=0x0200,
            total_packages=3,
            package_sequence=1,
            body=b"a",
        )
        evicted = r.sweep_expired(timeout_seconds=1000.0)
        self.assertEqual(evicted, [])
        self.assertEqual(len(r), 1)


if __name__ == "__main__":
    unittest.main()
