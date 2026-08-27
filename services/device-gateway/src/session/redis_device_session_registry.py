"""`RedisDeviceSessionRegistry` — a Redis-backed implementation of `DeviceSessionRegistryPort`
(`session_registry_port.py`), the same operations `DeviceSessionRegistry` (in-memory) exposes,
per `.claude/rules/jt808.md` #4 ("session state lives in Redis... enabling sharded, sticky device
connections"). **Wired into `Jt808Server` via `DeviceGateway` whenever a broker is configured**
(P0 #2 fix, device-gateway session-durability audit, 2026-08-25) — see `gateway.py`'s
`_build_jt808_provisioning`-adjacent construction for the exact conditional wiring, the same
pattern already used for `RedisEventPublisher`/`DeviceRegistryProjection`. `MdvrServer` (LSZ) is
untouched by this and keeps the in-memory default — LSZ remains dormant per CLAUDE.md's own
posture, with no live wiring benefit to justify touching it.

**What made this a drop-in replacement (Phase 2 of the P0 #2 fix, done first, no behavior
change):** `DeviceSessionRegistry`'s methods were previously synchronous — correct for an
in-memory dict, since no operation ever awaits anything. Any Redis-backed implementation is
inherently asynchronous (every operation is network I/O), so this class's methods are `async def`
throughout, including `count()` in place of `__len__` (Python's `__len__` cannot itself be a
coroutine). Wiring this into `DeviceSessionManager` required converting every
`DeviceSessionRegistry`-shaped call site to `await` (the in-memory implementation's methods too,
for interface consistency via the shared `DeviceSessionRegistryPort`), rippling through
`DeviceSessionManager` itself and every handler that calls `context.device_sessions.resolve(...)`
— mechanically safe since every call site was already inside an `async def`, but genuinely
touching both vendor stacks and their test suites. That refactor landed first, behavior-preserving
against the in-memory registry, before this class was ever constructed outside its own test file.

**Clock semantics — a second, explicitly-flagged limitation.** `DeviceSession.authenticated_at`/
`last_seen_at` are `time.monotonic()` floats, meaningful only for comparisons *within the process
that wrote them* — a second device-gateway process reading a session from Redis cannot correctly
compare its own `time.monotonic()` clock against a value written by a different process's clock
(monotonic clocks have an arbitrary, per-process epoch). This registry stores and returns those
floats faithfully (so a *single* process's own restart-recovery round-trips correctly), but true
multi-process expiry-sweep correctness would additionally require converting `DeviceSession`'s
timestamps to wall-clock time throughout `session/device_session.py`/`device_session_manager.py`
— a separate change, also not undertaken here, flagged rather than silently assumed solved.

**Requires a `decode_responses=True` client** (verified against `redis.asyncio.Redis`'s actual
method signatures, redis-py 8.0.1) — `_deserialize` calls `json.loads(raw)` on whatever `get()`
returns; a client without `decode_responses=True` would hand back `bytes`, which `json.loads`
(Python 3.6+) actually accepts transparently, so this specific path would still work either way —
but `smembers()` in `all()` would return a `set` of `bytes` terminal ids, and this class's own
`_session_key`/`_connection_index_key` f-string helpers would then embed a `bytes` repr (e.g.
`"device_session:b'TERM-1'"`) instead of the real key, silently breaking every lookup. Always
construct with `decode_responses=True` (`gateway.DeviceGateway._build_redis_client()` already
does).
"""

from __future__ import annotations

import json

from redis.asyncio import Redis

from src.session.device_session import DeviceConnectivityState, DeviceSession
from src.session.session_registry_port import DeviceSessionRegistryPort

_SESSION_KEY_PREFIX = "device_session:"
_CONNECTION_INDEX_PREFIX = "device_session:by_connection:"
_ALL_TERMINALS_KEY = "device_session:index"


def _session_key(terminal_id: str) -> str:
    return f"{_SESSION_KEY_PREFIX}{terminal_id}"


def _connection_index_key(connection_id: str) -> str:
    return f"{_CONNECTION_INDEX_PREFIX}{connection_id}"


def _serialize(session: DeviceSession) -> str:
    return json.dumps(
        {
            "terminal_id": session.terminal_id,
            "connection_id": session.connection_id,
            "device_id": session.device_id,
            "vehicle_id": session.vehicle_id,
            "organization_id": session.organization_id,
            "authenticated_at": session.authenticated_at,
            "last_seen_at": session.last_seen_at,
            "state": session.state.value,
        }
    )


def _deserialize(raw: str) -> DeviceSession:
    data = json.loads(raw)
    return DeviceSession(
        terminal_id=data["terminal_id"],
        connection_id=data["connection_id"],
        device_id=data["device_id"],
        vehicle_id=data["vehicle_id"],
        organization_id=data["organization_id"],
        authenticated_at=data["authenticated_at"],
        last_seen_at=data["last_seen_at"],
        state=DeviceConnectivityState(data["state"]),
    )


class RedisDeviceSessionRegistry(DeviceSessionRegistryPort):
    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def add_exclusive(self, session: DeviceSession) -> DeviceSession | None:
        """Mirrors the in-memory registry's own `add_exclusive` contract exactly (returns
        whatever session previously occupied this `terminal_id`, if any — the caller supersedes
        it). Not atomic across a Redis cluster/multi-process race the way the in-memory
        registry's `asyncio.Lock` is *within one process* — a real gap for genuine multi-node use,
        flagged rather than papered over with a false sense of safety; closing it would need a
        Redis transaction (`WATCH`/`MULTI`) or a Lua script, not undertaken in this phase since
        (per this module's own docstring) no multi-node deployment exists yet to race."""
        previous_raw = await self._redis.get(_session_key(session.terminal_id))
        previous = _deserialize(previous_raw) if previous_raw else None

        await self._redis.set(_session_key(session.terminal_id), _serialize(session))
        await self._redis.set(_connection_index_key(session.connection_id), session.terminal_id)
        await self._redis.sadd(_ALL_TERMINALS_KEY, session.terminal_id)
        return previous

    async def get(self, terminal_id: str) -> DeviceSession | None:
        raw = await self._redis.get(_session_key(terminal_id))
        return _deserialize(raw) if raw else None

    async def save(self, session: DeviceSession) -> None:
        """Persists an in-place mutation (e.g. after `session.touch()`/`mark_online()`) back to
        Redis — the in-memory registry needs no equivalent since mutating the object already
        mutates what every `get()` call returns; a Redis-backed session is a *copy* on every
        `get()`, so callers that mutate a returned `DeviceSession` must explicitly `save()` it
        back — called by `DeviceSessionManager.touch()` after every `session.touch()`/
        `mark_online()` mutation (not by `close()`, which removes the record instead)."""
        await self._redis.set(_session_key(session.terminal_id), _serialize(session))

    async def remove_if_current(self, terminal_id: str, session: DeviceSession) -> None:
        current = await self.get(terminal_id)
        if current is not None and current.connection_id == session.connection_id:
            await self._redis.delete(_session_key(terminal_id))
            await self._redis.delete(_connection_index_key(session.connection_id))
            await self._redis.srem(_ALL_TERMINALS_KEY, terminal_id)

    async def find_by_connection_id(self, connection_id: str) -> DeviceSession | None:
        terminal_id = await self._redis.get(_connection_index_key(connection_id))
        if not terminal_id:
            return None
        return await self.get(terminal_id)

    async def all(self) -> list[DeviceSession]:
        terminal_ids = await self._redis.smembers(_ALL_TERMINALS_KEY)
        sessions = []
        for terminal_id in terminal_ids:
            session = await self.get(terminal_id)
            if session is not None:
                sessions.append(session)
        return sessions

    async def count(self) -> int:
        return await self._redis.scard(_ALL_TERMINALS_KEY)
