"""Notification Worker (Backend LLD §11.2's "Notification Worker" row: "subscribe to domain
events... trip-lifecycle/geofence event -> notification service"). Foundation: ticks a
`BrokerConsumer` (ADR-0008's `RedisStreamsBrokerConsumer`, bound only when `RAAD_BROKER__URL` is
configured) and dispatches each event to `core.events.processor.EventProcessorRegistry` — the
same "leave unbound, don't fake it" policy `OutboxRelayWorker` already follows for its own
optional dependency. The actual event -> notification business mapping lives in
`modules/notifications/events/subscribers.py`, registered once at construction
(`register_notification_processors`) — this file is purely consumption/dispatch plumbing, no
business logic of its own.
"""

from __future__ import annotations

from raad.core.events.ports import BrokerConsumer
from raad.core.events.processor import EventProcessorRegistry
from raad.core.time.clock import Clock
from raad.core.workers.base import Worker


class NotificationWorker(Worker):
    def __init__(
        self,
        *,
        clock: Clock,
        consumer: BrokerConsumer,
        registry: EventProcessorRegistry,
    ) -> None:
        super().__init__("notification", clock)
        self._consumer = consumer
        self._registry = registry

    async def run_once(self) -> None:
        await self._consumer.consume(self._registry.dispatch)
