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

    @abstractmethod
    async def send_malformed(self, *, raw_data: str, error: str) -> None:
        """A stream entry that could not even be deserialized into a `DomainEvent` at all —
        distinct from `send`'s "a well-formed event whose handler kept failing" case (real,
        live-found incident, 2026-09-01: a message written directly onto the shared broker
        stream by something other than this codebase's own event publisher — missing required
        fields like `event_id` — permanently wedged every consumer group reading that stream,
        since retrying a message that can never parse is pointless and previously blocked all
        *later*, well-formed messages from ever being reached). No `DomainEvent`/`attempts`
        exist for a message that never successfully parsed, so this is a distinct method, not an
        overload of `send`."""
        raise NotImplementedError
