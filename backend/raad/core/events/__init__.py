"""Event base types and outbound ports (Backend LLD §10). Interfaces only in this phase —
no persistence, broker, or dispatcher implementation is wired yet."""
from raad.core.events.base import DomainEvent
from raad.core.events.ports import BrokerPort, EventDispatcher, OutboxPublisher

__all__ = ["BrokerPort", "DomainEvent", "EventDispatcher", "OutboxPublisher"]
