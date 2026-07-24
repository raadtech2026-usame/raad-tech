"""`RedisDeviceSessionRegistry` tests. A minimal in-memory fake stands in for the Redis string/
set commands this class calls (`get`, `set`, `delete`, `sadd`, `srem`, `smembers`, `scard`) — no
real Redis connection, mirroring every other fake-external-port test in this suite. Exercises the
same behavioral contract `test_device_session_registry.py` already proves for the in-memory
registry, so the two implementations are verified against equivalent expectations.
"""

import unittest

from src.session.device_session import DeviceConnectivityState, DeviceSession
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


if __name__ == "__main__":
    unittest.main()
