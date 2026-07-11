"""Event infrastructure (Backend LLD §10): base envelope, outbox (write + relay side), event
processor registry, and broker ports. `EventDispatcher`, `BrokerPort` (producer), and
`BrokerConsumer` remain interfaces only — no dispatcher/broker implementation is wired yet
(broker choice is an open item, Phase 2 §4.3)."""

from raad.core.events.base import DomainEvent
from raad.core.events.outbox import OutboxRecord, OutboxWriter, SqlOutboxPublisher
from raad.core.events.ports import (
    BrokerConsumer,
    BrokerPort,
    EventDispatcher,
    OutboxPublisher,
)
from raad.core.events.processor import EventProcessor, EventProcessorRegistry

__all__ = [
    "BrokerConsumer",
    "BrokerPort",
    "DomainEvent",
    "EventDispatcher",
    "EventProcessor",
    "EventProcessorRegistry",
    "OutboxPublisher",
    "OutboxRecord",
    "OutboxWriter",
    "SqlOutboxPublisher",
]
