"""The last alarm word seen per terminal (ADR-0055 §2), so only a rising edge raises an alarm.

Redis-backed in production so a gateway restart does not re-announce an alarm that is still
set; in-memory otherwise. Either way the backend also keeps one open alert per bus and type, so
a repeat can never become a storm.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from redis.asyncio import Redis

#: Thirty days: long enough to outlive any outage, short enough not to accumulate forever.
_TTL_SECONDS = 30 * 24 * 3600


class AlarmStateStore(ABC):
    @abstractmethod
    async def swap(self, terminal_id: str, alarm_flags: int) -> int | None:
        """Stores `alarm_flags` and returns the previous word, or `None` if none was known."""
        raise NotImplementedError


class InMemoryAlarmStateStore(AlarmStateStore):
    def __init__(self) -> None:
        self._flags: dict[str, int] = {}

    async def swap(self, terminal_id: str, alarm_flags: int) -> int | None:
        previous = self._flags.get(terminal_id)
        self._flags[terminal_id] = alarm_flags
        return previous


class RedisAlarmStateStore(AlarmStateStore):
    KEY = "device-gateway:alarm-flags:{terminal_id}"

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def swap(self, terminal_id: str, alarm_flags: int) -> int | None:
        previous = await self._redis.set(
            self.KEY.format(terminal_id=terminal_id), str(alarm_flags), ex=_TTL_SECONDS, get=True
        )
        if previous is None:
            return None
        return int(previous.decode() if isinstance(previous, bytes) else previous)
