"""`RedisDeviceSessionRegistry` tests. A minimal in-memory fake stands in for the Redis string/
set commands this class calls (`get`, `set`, `delete`, `sadd`, `srem`, `smembers`, `scard`) — no
real Redis connection, mirroring every other fake-external-port test in this suite. Exercises the
same behavioral contract `test_device_session_registry.py` already proves for the in-memory
registry, so the two implementations are verified against equivalent expectations.
"""

import unittest

from src.session.device_session import DeviceConnectivityState, DeviceSession
from src.session.device_session_manager import DeviceSessionManager
from src.session.redis_device_session_registry import RedisDeviceSessionRegistry


class FakeRedis:
    def __init__(self) -> None:
        self._strings: dict[str, str] = {}
        self._sets: dict[str, set[str]] = {}

    async def get(self, key: str):
        return self._strings.get(key)

    async def set(self, key: str, value: str) -> None:
        self._strings[key] = value

    async def delete(self, key: str) -> None:
        self._strings.pop(key, None)

    async def sadd(self, key: str, *values: str) -> None:
        self._sets.setdefault(key, set()).update(values)

    async def srem(self, key: str, *values: str) -> None:
        self._sets.get(key, set()).difference_update(values)

    async def smembers(self, key: str):
        return set(self._sets.get(key, set()))

    async def scard(self, key: str) -> int:
        return len(self._sets.get(key, set()))


def _make_session(terminal_id: str = "TERM-1", connection_id: str = "conn-1") -> DeviceSession:
    return DeviceSession(
        terminal_id=terminal_id,
        connection_id=connection_id,
        device_id="device-1",
        vehicle_id="vehicle-1",
        organization_id="org-1",
    )


class RedisDeviceSessionRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_then_get_round_trips(self) -> None:
        redis = FakeRedis()
        registry = RedisDeviceSessionRegistry(redis)
        session = _make_session()

        previous = await registry.add_exclusive(session)
        self.assertIsNone(previous)

        fetched = await registry.get("TERM-1")
        self.assertEqual(fetched.terminal_id, "TERM-1")
        self.assertEqual(fetched.device_id, "device-1")
        self.assertEqual(fetched.vehicle_id, "vehicle-1")
        self.assertEqual(fetched.organization_id, "org-1")
        self.assertEqual(fetched.state, DeviceConnectivityState.AUTHENTICATED)

    async def test_add_exclusive_returns_previous_session_for_same_terminal(self) -> None:
        redis = FakeRedis()
        registry = RedisDeviceSessionRegistry(redis)
        first = _make_session(connection_id="conn-1")
        second = _make_session(connection_id="conn-2")

        await registry.add_exclusive(first)
        previous = await registry.add_exclusive(second)

        self.assertEqual(previous.connection_id, "conn-1")
        current = await registry.get("TERM-1")
        self.assertEqual(current.connection_id, "conn-2")

    async def test_find_by_connection_id(self) -> None:
        redis = FakeRedis()
        registry = RedisDeviceSessionRegistry(redis)
        await registry.add_exclusive(_make_session())

        found = await registry.find_by_connection_id("conn-1")
        self.assertEqual(found.terminal_id, "TERM-1")
        self.assertIsNone(await registry.find_by_connection_id("no-such-connection"))

    async def test_supersede_clears_the_previous_connections_index_key(self) -> None:
        """Regression, live-found 2026-09-02 against the physical bench unit. The superseded
        connection's index key used to survive `add_exclusive`, so looking that dead connection
        up still resolved to the terminal — and therefore to the *new*, live session that had
        just replaced it."""
        redis = FakeRedis()
        registry = RedisDeviceSessionRegistry(redis)

        await registry.add_exclusive(_make_session(connection_id="conn-old"))
        await registry.add_exclusive(_make_session(connection_id="conn-new"))

        self.assertIsNone(await registry.find_by_connection_id("conn-old"))
        still_live = await registry.find_by_connection_id("conn-new")
        self.assertIsNotNone(still_live)
        self.assertEqual(still_live.connection_id, "conn-new")

    async def test_find_by_connection_id_ignores_a_stale_index_key(self) -> None:
        """Defense-in-depth for the same bug: an orphaned index key written by a pre-fix process
        (14 existed on the bench) must never resolve to a session that no longer owns it."""
        redis = FakeRedis()
        registry = RedisDeviceSessionRegistry(redis)
        await registry.add_exclusive(_make_session(connection_id="conn-new"))
        # Simulate the orphan a pre-fix process would have left behind.
        await redis.set("device_session:by_connection:conn-orphan", "TERM-1")

        self.assertIsNone(await registry.find_by_connection_id("conn-orphan"))

    async def test_remove_if_current_removes_matching_session(self) -> None:
        redis = FakeRedis()
        registry = RedisDeviceSessionRegistry(redis)
        session = _make_session()
        await registry.add_exclusive(session)

        await registry.remove_if_current("TERM-1", session)

        self.assertIsNone(await registry.get("TERM-1"))
        self.assertIsNone(await registry.find_by_connection_id("conn-1"))
        self.assertEqual(await registry.count(), 0)

    async def test_remove_if_current_is_a_noop_for_a_stale_session(self) -> None:
        """Mirrors the in-memory registry's own identity-guard test: a superseded session's
        belated close-cleanup must not delete the newer session that already replaced it."""
        redis = FakeRedis()
        registry = RedisDeviceSessionRegistry(redis)
        old = _make_session(connection_id="conn-1")
        new = _make_session(connection_id="conn-2")
        await registry.add_exclusive(old)
        await registry.add_exclusive(new)

        await registry.remove_if_current("TERM-1", old)  # stale - must not remove `new`

        current = await registry.get("TERM-1")
        self.assertIsNotNone(current)
        self.assertEqual(current.connection_id, "conn-2")

    async def test_all_and_count_reflect_every_registered_session(self) -> None:
        redis = FakeRedis()
        registry = RedisDeviceSessionRegistry(redis)
        await registry.add_exclusive(_make_session("TERM-1", "conn-1"))
        await registry.add_exclusive(_make_session("TERM-2", "conn-2"))
        await registry.add_exclusive(_make_session("TERM-3", "conn-3"))

        self.assertEqual(await registry.count(), 3)
        terminal_ids = {s.terminal_id for s in await registry.all()}
        self.assertEqual(terminal_ids, {"TERM-1", "TERM-2", "TERM-3"})

    async def test_save_persists_in_place_mutations(self) -> None:
        redis = FakeRedis()
        registry = RedisDeviceSessionRegistry(redis)
        session = _make_session()
        await registry.add_exclusive(session)

        session.touch()
        session.mark_online()
        await registry.save(session)

        fetched = await registry.get("TERM-1")
        self.assertEqual(fetched.state, DeviceConnectivityState.ONLINE)



class SupersedeThenCloseOldConnectionTests(unittest.IsolatedAsyncioTestCase):
    """End-to-end reproduction of the live 2026-09-02 bench failure, driven through
    `DeviceSessionManager` exactly as the real JT/T 808 server does it: the device reconnects
    while its previous session is still registered, authenticates on the new connection, and the
    manager then closes the old connection — which fires the transport's own
    `handle_connection_closed(old_connection_id)` hook. The device's live session must survive.

    Before the fix this deleted the brand-new session, leaving a TCP-connected, successfully
    authenticated device with no session at all: every 0x0200/0x0704 was then dropped
    `position_report_dropped_unauthenticated` and no 0x9101 video command could be routed to it.
    """

    async def test_new_session_survives_the_old_connections_close_hook(self) -> None:
        closed: list[tuple[str, str]] = []

        async def close_connection(connection_id: str, reason: str) -> None:
            closed.append((connection_id, reason))

        offline: list[str] = []

        async def on_device_offline(session, reason: str) -> None:
            offline.append(reason)

        registry = RedisDeviceSessionRegistry(FakeRedis())
        manager = DeviceSessionManager(
            registry=registry,
            close_connection=close_connection,
            on_device_offline=on_device_offline,
        )

        await manager.create(
            connection_id="conn-old",
            terminal_id="TERM-1",
            device_id="dev-1",
            vehicle_id="veh-1",
            organization_id="org-1",
        )
        await manager.create(
            connection_id="conn-new",
            terminal_id="TERM-1",
            device_id="dev-1",
            vehicle_id="veh-1",
            organization_id="org-1",
        )
        self.assertEqual(closed, [("conn-old", "superseded")])

        # The transport now reports the old connection as closed - the exact hook that used to
        # destroy the new session.
        await manager.handle_connection_closed("conn-old")

        live = await manager.resolve("TERM-1")
        self.assertIsNotNone(live, "the newly authenticated session was destroyed")
        self.assertEqual(live.connection_id, "conn-new")
        self.assertEqual(await registry.count(), 1)
        self.assertEqual(offline, [], "no device_offline should fire for a superseded connection")

    async def test_closing_the_current_connection_still_removes_the_session(self) -> None:
        """The fix must not break the ordinary path: closing the connection that genuinely owns
        the session still tears it down and reports the device offline."""
        offline: list[str] = []

        async def on_device_offline(session, reason: str) -> None:
            offline.append(reason)

        async def close_connection(connection_id: str, reason: str) -> None:
            return None

        registry = RedisDeviceSessionRegistry(FakeRedis())
        manager = DeviceSessionManager(
            registry=registry,
            close_connection=close_connection,
            on_device_offline=on_device_offline,
        )
        await manager.create(connection_id="conn-1", terminal_id="TERM-1")

        await manager.handle_connection_closed("conn-1")

        self.assertIsNone(await manager.resolve("TERM-1"))
        self.assertEqual(await registry.count(), 0)
        self.assertEqual(offline, ["connection_closed"])


if __name__ == "__main__":
    unittest.main()
