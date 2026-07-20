"""Dead Letter Queue foundation (Backend LLD §11.3: "Retry with backoff, bounded attempts,
then dead-letter queue + alert"). `RedisDeadLetterQueue` (Backend Stabilization phase,
ADR-0008 — `core/events/redis_streams.py`) is the concrete sink, a second Redis Stream
alongside the broker's own event stream.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.events.base import DomainEvent


class DeadLetterQueue(ABC):
    @abstractmethod
    async def send(self, *, event: DomainEvent, error: str, attempts: int) -> None:
        raise NotImplementedError
