"""Event infrastructure (Backend LLD §10): base envelope, outbox write-side, and ports.
`OutboxPublisher` (the *read*/relay side) and `BrokerPort`/`EventDispatcher` remain interfaces
only — no broker or dispatcher implementation is wired yet."""

from raad.core.events.base import DomainEvent
from raad.core.events.outbox import OutboxRecord, OutboxWriter
from raad.core.events.ports import BrokerPort, EventDispatcher, OutboxPublisher

__all__ = [
    "BrokerPort",
    "DomainEvent",
    "EventDispatcher",
    "OutboxPublisher",
    "OutboxRecord",
    "OutboxWriter",
]
