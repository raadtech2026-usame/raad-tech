"""Telemetry Worker — ticks a dedicated `TelemetryBrokerConsumer` reading the separate
`raad:telemetry` Redis stream and dispatches incoming high-volume `DevicePositionReported`
events to `core.events.processor.EventProcessorRegistry`.

Separating telemetry consumption from the general `NotificationWorker` ensures high-frequency
GPS positions never starve domain events (notifications, video session lifecycle, subscriptions)
nor exceed consumer group limits.
"""

from __future__ import annotations

from raad.core.events.ports import BrokerConsumer
from raad.core.events.processor import EventProcessorRegistry
from raad.core.time.clock import Clock
from raad.core.workers.base import Worker


class TelemetryWorker(Worker):
    def __init__(
        self,
        *,
        clock: Clock,
        consumer: BrokerConsumer,
        registry: EventProcessorRegistry,
    ) -> None:
        super().__init__("telemetry", clock)
        self._consumer = consumer
        self._registry = registry

    async def run_once(self) -> None:
        await self._consumer.consume(self._registry.dispatch)
