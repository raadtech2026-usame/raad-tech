"""Event processor foundation (Backend LLD §10/§11): the per-event-type handler contract a
worker invokes once it has an event in hand (from the broker or the in-process dispatcher).
No concrete processor is registered here — e.g. a future `TripStartedNotifier` is owned by
`modules/notifications` and registers itself once that module's application layer exists.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.events.base import DomainEvent


class EventProcessor(ABC):
    """Handles every event of one `event_type`. Implementations must be idempotent — the same
    event may be delivered more than once (at-least-once delivery, LLD §10.3)."""

    event_type: str

    @abstractmethod
    async def process(self, event: DomainEvent) -> None:
        raise NotImplementedError


class EventProcessorRegistry:
    """Maps `event_type` -> `EventProcessor` and dispatches to whichever is registered.
    Reusable plumbing only — modules populate this via `register()` once their own
    `EventProcessor` subclasses exist; empty by default."""

    def __init__(self) -> None:
        self._processors: dict[str, EventProcessor] = {}

    def register(self, processor: EventProcessor) -> None:
        self._processors[processor.event_type] = processor

    def get(self, event_type: str) -> EventProcessor | None:
        return self._processors.get(event_type)

    async def dispatch(self, event: DomainEvent) -> None:
        processor = self.get(event.event_type)
        if processor is not None:
            await processor.process(event)
