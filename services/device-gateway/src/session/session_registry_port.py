"""`DeviceSessionRegistryPort` — the interface both `DeviceSessionRegistry` (in-memory) and
`RedisDeviceSessionRegistry` implement, mirroring `events/publisher_port.py`'s/`latest_position/
writer_port.py`'s own `ABC`+`@abstractmethod` convention for every other injectable dependency in
this deployable.

**P0 #2 fix (device-gateway session-durability audit, 2026-08-25):** formalizes the migration both
concrete classes' own docstrings already called for — `DeviceSessionManager` previously called most
registry methods synchronously, which only worked because the in-memory registry never needed to
`await` anything; `RedisDeviceSessionRegistry` is inherently asynchronous (every operation is
network I/O) and could not be wired in without this. Every method here is `async def`, including
`count()` in place of `__len__` (a coroutine cannot back `__len__`) and a `save()` method with no
in-memory equivalent need (mutating an in-memory `DeviceSession` already mutates what `get()`
returns; a Redis-backed `get()` returns a fresh deserialized copy each time, so a caller that
mutates a resolved session must explicitly persist it back).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.session.device_session import DeviceSession


class DeviceSessionRegistryPort(ABC):
    @abstractmethod
    async def add_exclusive(self, session: DeviceSession) -> DeviceSession | None:
        raise NotImplementedError

    @abstractmethod
    async def get(self, terminal_id: str) -> DeviceSession | None:
        raise NotImplementedError

    @abstractmethod
    async def save(self, session: DeviceSession) -> None:
        raise NotImplementedError

    @abstractmethod
    async def remove_if_current(self, terminal_id: str, session: DeviceSession) -> None:
        raise NotImplementedError

    @abstractmethod
    async def find_by_connection_id(self, connection_id: str) -> DeviceSession | None:
        raise NotImplementedError

    @abstractmethod
    async def all(self) -> list[DeviceSession]:
        raise NotImplementedError

    @abstractmethod
    async def count(self) -> int:
        raise NotImplementedError
