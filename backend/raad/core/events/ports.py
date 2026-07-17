"""Event infrastructure ports (Backend LLD §10). `OutboxPublisher` has a concrete
implementation (`core.events.outbox.SqlOutboxPublisher`, Phase 4.4/4.5); `EventDispatcher`,
`BrokerPort` (producer), and `BrokerConsumer` remain interfaces only — a broker (Redis
Streams/RabbitMQ at MVP, Kafka as the scale path, Phase 2 §4.3) is still an open item, not
decided in this phase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Sequence

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
    def subscribe(
        self, event_type: str, handler: Callable[[DomainEvent], None]
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def dispatch(self, events: Sequence[DomainEvent]) -> None:
        raise NotImplementedError


class BrokerPort(ABC):
    """Outbound (producer) publish to the event bus (Redis Streams/RabbitMQ at MVP, Kafka as
    the scale path — Phase 2 §4.3). Event contracts are broker-agnostic by design; only this
    port's concrete adapter changes when the broker is swapped."""

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError


class BrokerConsumer(ABC):
    """Inbound (consumer) side of the broker port — subscribes to event topics/streams and
    invokes a handler per message (§10.3: "anything crossing a module or service boundary
    goes through the outbox+broker"). Consumers must be idempotent (dedupe by `event_id` —
    see `core.workers.idempotency.IdempotencyStore`), since delivery is at-least-once.
    """

    @abstractmethod
    async def consume(self, handler: Callable[[DomainEvent], Awaitable[None]]) -> None:
        raise NotImplementedError
