"""Event infrastructure ports — interfaces only (Backend LLD §10).

Concrete implementations (a MySQL-backed outbox writer/relay, an in-process dispatcher, a
Redis Streams/RabbitMQ broker client) are added when the persistence and broker layers are
wired in a later phase. Defining the ports now lets application services depend on
abstractions from day one (§4.2 `EventRecorder`/outbox pattern).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Sequence

from raad.core.events.base import DomainEvent


class OutboxPublisher(ABC):
    """Used by the Outbox Relay worker (§10.2, §11.2) to publish committed-but-unpublished
    outbox rows to the broker."""

    @abstractmethod
    async def publish_pending(self, batch_size: int) -> int:
        """Returns the number of events published."""
        raise NotImplementedError


class EventDispatcher(ABC):
    """In-process dispatcher for purely intra-module reactions (§10.3's 'in-process fast
    path'). Anything crossing a module or service boundary goes through the outbox+broker
    instead, via `BrokerPort`."""

    @abstractmethod
    def subscribe(self, event_type: str, handler: Callable[[DomainEvent], None]) -> None:
        raise NotImplementedError

    @abstractmethod
    def dispatch(self, events: Sequence[DomainEvent]) -> None:
        raise NotImplementedError


class BrokerPort(ABC):
    """Outbound publish to the event bus (Redis Streams/RabbitMQ at MVP, Kafka as the scale
    path — Phase 2 §4.3). Event contracts are broker-agnostic by design; only this port's
    concrete adapter changes when the broker is swapped."""

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError
