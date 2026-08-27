"""DeviceSessionRegistry tests (Phase 9.2): registry consistency, the single-active-session
identity guard, and concurrent `add_exclusive` behavior.

**P0 #2 fix (device-gateway session-durability audit, 2026-08-25):** every method is now
`async def` (implementing `DeviceSessionRegistryPort`, matching `RedisDeviceSessionRegistry`'s
interface) — `get`/`remove_if_current`/`find_by_connection_id`/`all` are `await`ed below, and
`count()` replaces the old `len(registry)`.
"""

import asyncio
import unittest

from src.session.device_session import DeviceSession
from src.session.device_session_registry import DeviceSessionRegistry


class DeviceSessionRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_exclusive_first_time_returns_none(self) -> None:
        registry = DeviceSessionRegistry()
        session = DeviceSession(terminal_id="TERM-1", connection_id="conn-1")
        previous = await registry.add_exclusive(session)
        self.assertIsNone(previous)
        self.assertIs(await registry.get("TERM-1"), session)

    async def test_add_exclusive_returns_and_replaces_previous(self) -> None:
        registry = DeviceSessionRegistry()
        first = DeviceSession(terminal_id="TERM-1", connection_id="conn-1")
        second = DeviceSession(terminal_id="TERM-1", connection_id="conn-2")

        await registry.add_exclusive(first)
        previous = await registry.add_exclusive(second)

        self.assertIs(previous, first)
        self.assertIs(await registry.get("TERM-1"), second)
        self.assertEqual(await registry.count(), 1)  # never two sessions for one terminal_id

    async def test_remove_if_current_removes_matching_session(self) -> None:
        registry = DeviceSessionRegistry()
        session = DeviceSession(terminal_id="TERM-1", connection_id="conn-1")
        await registry.add_exclusive(session)

        await registry.remove_if_current("TERM-1", session)

        self.assertIsNone(await registry.get("TERM-1"))

    async def test_remove_if_current_ignores_stale_session(self) -> None:
        """The exact race `add_exclusive`'s docstring describes: a stale reference to a
        session that has already been superseded must not be able to delete the session that
        replaced it."""
        registry = DeviceSessionRegistry()
        old_session = DeviceSession(terminal_id="TERM-1", connection_id="conn-1")
        new_session = DeviceSession(terminal_id="TERM-1", connection_id="conn-2")

        await registry.add_exclusive(old_session)
        await registry.add_exclusive(new_session)  # supersedes old_session

        # Something still holding the stale `old_session` reference tries to remove it.
        await registry.remove_if_current("TERM-1", old_session)

        # The current (new) session must be untouched.
        self.assertIs(await registry.get("TERM-1"), new_session)
        self.assertEqual(await registry.count(), 1)

    async def test_remove_if_current_unknown_terminal_is_a_noop(self) -> None:
        registry = DeviceSessionRegistry()
        session = DeviceSession(terminal_id="TERM-1", connection_id="conn-1")
        await registry.remove_if_current("does-not-exist", session)  # must not raise

    async def test_find_by_connection_id(self) -> None:
        registry = DeviceSessionRegistry()
        session = DeviceSession(terminal_id="TERM-1", connection_id="conn-1")
        await registry.add_exclusive(session)

        self.assertIs(await registry.find_by_connection_id("conn-1"), session)
        self.assertIsNone(await registry.find_by_connection_id("no-such-connection"))

    async def test_all_returns_every_session(self) -> None:
        registry = DeviceSessionRegistry()
        await registry.add_exclusive(DeviceSession(terminal_id="A", connection_id="c1"))
        await registry.add_exclusive(DeviceSession(terminal_id="B", connection_id="c2"))
        ids = {s.terminal_id for s in await registry.all()}
        self.assertEqual(ids, {"A", "B"})

    async def test_concurrent_add_exclusive_same_terminal_is_serialized(self) -> None:
        """Both calls must complete without corrupting the registry: exactly one session ends
        up registered, and exactly one of the two calls observes the other as `previous`.
        """
        registry = DeviceSessionRegistry()
        first = DeviceSession(terminal_id="TERM-RACE", connection_id="conn-a")
        second = DeviceSession(terminal_id="TERM-RACE", connection_id="conn-b")

        results = await asyncio.gather(
            registry.add_exclusive(first), registry.add_exclusive(second)
        )

        self.assertEqual(await registry.count(), 1)
        # Exactly one of the two results is None (whichever ran first); the other is the
        # session that ran first (whichever it was).
        self.assertEqual(sorted(r is None for r in results), [False, True])
        winner = await registry.get("TERM-RACE")
        self.assertIn(winner, (first, second))

    async def test_save_is_a_documented_noop(self) -> None:
        """Unlike `RedisDeviceSessionRegistry.save()`, this is a no-op: mutating an in-memory
        `DeviceSession` already mutates what `get()` returns (same object reference). `save()`
        exists only so `DeviceSessionManager` can call it unconditionally, regardless of which
        registry backs it."""
        registry = DeviceSessionRegistry()
        session = DeviceSession(terminal_id="TERM-1", connection_id="conn-1")
        await registry.add_exclusive(session)

        session.touch()
        await registry.save(session)  # must not raise, must not change anything observable

        self.assertIs(await registry.get("TERM-1"), session)


if __name__ == "__main__":
    unittest.main()
