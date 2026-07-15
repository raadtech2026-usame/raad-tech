"""DeviceSessionManager tests (Phase 9.2): first login, duplicate terminal, reconnect,
disconnect cleanup, heartbeat timeout, concurrent sessions, registry consistency.
"""

import asyncio
import unittest

from src.session.device_session import DeviceConnectivityState
from src.session.device_session_manager import DeviceSessionManager
from src.session.device_session_registry import DeviceSessionRegistry


class RecordingCloser:
    """Fake `close_connection` callback — records calls instead of touching real sockets."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, connection_id: str, reason: str) -> None:
        self.calls.append((connection_id, reason))


def make_manager(closer: RecordingCloser | None = None, **hooks):
    closer = closer or RecordingCloser()
    registry = DeviceSessionRegistry()
    manager = DeviceSessionManager(registry=registry, close_connection=closer, **hooks)
    return manager, registry, closer


class FirstLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_produces_authenticated_session(self) -> None:
        manager, registry, closer = make_manager()
        session = await manager.create(connection_id="conn-1", terminal_id="TERM-1")

        self.assertEqual(session.terminal_id, "TERM-1")
        self.assertEqual(session.connection_id, "conn-1")
        self.assertEqual(session.state, DeviceConnectivityState.AUTHENTICATED)
        self.assertEqual(len(registry), 1)
        self.assertEqual(closer.calls, [])  # no supersede on first login

    async def test_create_passes_through_optional_identity_fields(self) -> None:
        manager, _, _ = make_manager()
        session = await manager.create(
            connection_id="conn-1",
            terminal_id="TERM-1",
            device_id="dev-1",
            vehicle_id="veh-1",
            organization_id="org-1",
        )
        self.assertEqual(session.device_id, "dev-1")
        self.assertEqual(session.vehicle_id, "veh-1")
        self.assertEqual(session.organization_id, "org-1")

    async def test_first_touch_promotes_to_online(self) -> None:
        online_calls = []
        manager, _, _ = make_manager(on_device_online=lambda s: online_calls.append(s))
        session = await manager.create(connection_id="conn-1", terminal_id="TERM-1")

        manager.touch("TERM-1")

        self.assertEqual(session.state, DeviceConnectivityState.ONLINE)
        self.assertEqual(len(online_calls), 1)
        self.assertIs(online_calls[0], session)

    async def test_second_touch_does_not_refire_online(self) -> None:
        online_calls = []
        manager, _, _ = make_manager(on_device_online=lambda s: online_calls.append(s))
        await manager.create(connection_id="conn-1", terminal_id="TERM-1")

        manager.touch("TERM-1")
        manager.touch("TERM-1")
        manager.touch("TERM-1")

        self.assertEqual(len(online_calls), 1)

    async def test_touch_updates_last_seen(self) -> None:
        manager, _, _ = make_manager()
        session = await manager.create(connection_id="conn-1", terminal_id="TERM-1")
        before = session.last_seen_at
        await asyncio.sleep(0.05)
        manager.touch("TERM-1")
        self.assertGreater(session.last_seen_at, before)

    async def test_touch_unknown_terminal_is_a_noop(self) -> None:
        manager, _, _ = make_manager()
        manager.touch("does-not-exist")  # must not raise

    async def test_resolve_returns_session(self) -> None:
        manager, _, _ = make_manager()
        session = await manager.create(connection_id="conn-1", terminal_id="TERM-1")
        self.assertIs(manager.resolve("TERM-1"), session)
        self.assertIsNone(manager.resolve("unknown"))


class DuplicateTerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_connection_supersedes_first(self) -> None:
        superseded_calls = []
        manager, registry, closer = make_manager(
            on_session_superseded=lambda old, new: superseded_calls.append((old, new))
        )
        first = await manager.create(connection_id="conn-1", terminal_id="TERM-1")
        second = await manager.create(connection_id="conn-2", terminal_id="TERM-1")

        # Only the newest session is registered under the terminal_id.
        self.assertIs(registry.get("TERM-1"), second)
        self.assertEqual(len(registry), 1)

        # The old connection was asked to close, with a reason.
        self.assertEqual(closer.calls, [("conn-1", "superseded")])

        # The supersede hook fired with (old, new).
        self.assertEqual(len(superseded_calls), 1)
        self.assertIs(superseded_calls[0][0], first)
        self.assertIs(superseded_calls[0][1], second)

    async def test_reauthenticating_same_connection_is_not_a_supersede(self) -> None:
        manager, registry, closer = make_manager()
        first = await manager.create(connection_id="conn-1", terminal_id="TERM-1")
        second = await manager.create(connection_id="conn-1", terminal_id="TERM-1")

        self.assertEqual(closer.calls, [])  # same connection -> no close requested
        self.assertIs(registry.get("TERM-1"), second)

    async def test_handle_connection_closed_after_supersede_only_affects_new_session(
        self,
    ) -> None:
        """After supersede, the old connection_id is no longer bound to anything in the
        registry (`find_by_connection_id` only ever sees the current session per terminal_id)
        — its belated close notification must be a no-op, not disturb the new session. The
        registry-level identity-guard race itself (`remove_if_current` given a stale session
        object directly) is covered in `test_device_session_registry.py`."""
        manager, registry, closer = make_manager()
        await manager.create(connection_id="conn-1", terminal_id="TERM-1")
        new_session = await manager.create(connection_id="conn-2", terminal_id="TERM-1")

        await manager.handle_connection_closed("conn-1")

        self.assertIs(registry.get("TERM-1"), new_session)
        self.assertEqual(len(registry), 1)
        self.assertEqual(new_session.state, DeviceConnectivityState.AUTHENTICATED)

    async def test_concurrent_create_for_same_terminal_never_double_registers(
        self,
    ) -> None:
        """Two coroutines racing to authenticate the same terminal_id concurrently must still
        leave exactly one session registered — the `asyncio.Lock` in `add_exclusive` closes
        the check-then-act window."""
        manager, registry, closer = make_manager()

        results = await asyncio.gather(
            manager.create(connection_id="conn-a", terminal_id="TERM-RACE"),
            manager.create(connection_id="conn-b", terminal_id="TERM-RACE"),
        )

        self.assertEqual(len(registry), 1)
        winner = registry.get("TERM-RACE")
        self.assertIn(winner, results)
        # Exactly one supersede/close should have happened (the loser).
        self.assertEqual(len(closer.calls), 1)


class ReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_after_clean_close_creates_fresh_session(self) -> None:
        manager, registry, closer = make_manager()
        await manager.create(connection_id="conn-1", terminal_id="TERM-1")
        await manager.close("TERM-1", reason="logout")
        self.assertEqual(len(registry), 0)

        session = await manager.create(connection_id="conn-2", terminal_id="TERM-1")
        self.assertEqual(session.connection_id, "conn-2")
        self.assertEqual(session.state, DeviceConnectivityState.AUTHENTICATED)
        self.assertEqual(
            closer.calls, []
        )  # nothing to supersede - old session already gone


class DisconnectCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_connection_closed_closes_bound_session(self) -> None:
        offline_calls = []
        manager, registry, _ = make_manager(
            on_device_offline=lambda s, reason: offline_calls.append((s, reason))
        )
        session = await manager.create(connection_id="conn-1", terminal_id="TERM-1")

        await manager.handle_connection_closed("conn-1")

        self.assertEqual(len(registry), 0)
        self.assertEqual(session.state, DeviceConnectivityState.OFFLINE)
        self.assertEqual(len(offline_calls), 1)
        self.assertIs(offline_calls[0][0], session)
        self.assertEqual(offline_calls[0][1], "connection_closed")

    async def test_handle_connection_closed_for_unbound_connection_is_a_noop(
        self,
    ) -> None:
        manager, registry, _ = make_manager()
        await manager.create(connection_id="conn-1", terminal_id="TERM-1")

        await manager.handle_connection_closed("conn-never-authenticated")

        self.assertEqual(len(registry), 1)  # untouched

    async def test_close_is_idempotent(self) -> None:
        manager, registry, _ = make_manager()
        await manager.create(connection_id="conn-1", terminal_id="TERM-1")
        await manager.close("TERM-1", reason="logout")
        await manager.close("TERM-1", reason="logout")  # must not raise
        self.assertEqual(len(registry), 0)


class HeartbeatTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_sweep_expires_stale_sessions(self) -> None:
        offline_calls = []
        manager, registry, _ = make_manager(
            on_device_offline=lambda s, reason: offline_calls.append((s, reason))
        )
        await manager.create(connection_id="conn-1", terminal_id="TERM-1")

        await asyncio.sleep(0.1)
        await manager._sweep_once(timeout_seconds=0.05)

        self.assertEqual(len(registry), 0)
        self.assertEqual(offline_calls[0][1], "session_expired")

    async def test_sweep_does_not_expire_fresh_sessions(self) -> None:
        manager, registry, _ = make_manager()
        await manager.create(connection_id="conn-1", terminal_id="TERM-1")

        await manager._sweep_once(timeout_seconds=10.0)

        self.assertEqual(len(registry), 1)

    async def test_touch_resets_expiration(self) -> None:
        manager, registry, _ = make_manager()
        await manager.create(connection_id="conn-1", terminal_id="TERM-1")

        for _ in range(4):
            await asyncio.sleep(0.03)
            manager.touch("TERM-1")
            await manager._sweep_once(timeout_seconds=0.1)

        self.assertEqual(len(registry), 1)  # kept alive by repeated touches

    async def test_start_stop_sweep_task(self) -> None:
        manager, registry, _ = make_manager()
        await manager.create(connection_id="conn-1", terminal_id="TERM-1")

        manager.start_sweep(timeout_seconds=0.05, interval_seconds=0.02)
        await asyncio.sleep(0.2)

        self.assertEqual(len(registry), 0)  # swept away by the background task
        await manager.stop_sweep()


class ConcurrentSessionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_distinct_terminals_coexist(self) -> None:
        manager, registry, closer = make_manager()
        sessions = await asyncio.gather(
            *[
                manager.create(connection_id=f"conn-{i}", terminal_id=f"TERM-{i}")
                for i in range(10)
            ]
        )
        self.assertEqual(len(registry), 10)
        self.assertEqual(closer.calls, [])  # no supersedes - all distinct terminals
        terminal_ids = {s.terminal_id for s in sessions}
        self.assertEqual(len(terminal_ids), 10)

    async def test_closing_one_does_not_affect_others(self) -> None:
        manager, registry, _ = make_manager()
        for i in range(5):
            await manager.create(connection_id=f"conn-{i}", terminal_id=f"TERM-{i}")

        await manager.close("TERM-2", reason="logout")

        self.assertEqual(len(registry), 4)
        self.assertIsNone(registry.get("TERM-2"))
        for i in [0, 1, 3, 4]:
            self.assertIsNotNone(registry.get(f"TERM-{i}"))


class RegistryConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_closes_every_session(self) -> None:
        manager, registry, _ = make_manager()
        for i in range(3):
            await manager.create(connection_id=f"conn-{i}", terminal_id=f"TERM-{i}")

        await manager.shutdown()

        self.assertEqual(len(registry), 0)
        self.assertEqual(manager.session_count, 0)

    async def test_session_count_matches_registry_length(self) -> None:
        manager, registry, _ = make_manager()
        await manager.create(connection_id="conn-1", terminal_id="TERM-1")
        await manager.create(connection_id="conn-2", terminal_id="TERM-2")
        self.assertEqual(manager.session_count, len(registry))
        self.assertEqual(manager.session_count, 2)

    async def test_find_by_connection_id(self) -> None:
        manager, registry, _ = make_manager()
        session = await manager.create(connection_id="conn-1", terminal_id="TERM-1")
        found = registry.find_by_connection_id("conn-1")
        self.assertIs(found, session)
        self.assertIsNone(registry.find_by_connection_id("no-such-connection"))


if __name__ == "__main__":
    unittest.main()
