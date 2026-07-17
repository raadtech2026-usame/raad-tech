"""Outbox Relay worker (Backend LLD §11.2: "Poll / CDC" trigger, "Publish committed outbox
rows to the broker"). Foundation only: this ticks `SqlOutboxPublisher.publish_pending` on an
interval. If no `OutboxPublisher` is bound (no `BrokerPort`/broker configured — the broker
choice, Phase 2 §4.3, is still an open item), each tick is a documented no-op rather than a
crash — the same "leave unbound, don't fake it" policy `core/di` uses for other pending ports.
"""

from __future__ import annotations

from raad.core.di.container import Container
from raad.core.events.ports import OutboxPublisher
from raad.core.logging.setup import get_logger
from raad.core.time.clock import Clock
from raad.core.workers.base import Worker

logger = get_logger("raad.workers.outbox_relay")


class OutboxRelayWorker(Worker):
    def __init__(self, container: Container, *, batch_size: int) -> None:
        super().__init__("outbox_relay", container.resolve(Clock))
        self._container = container
        self._batch_size = batch_size

    async def run_once(self) -> None:
        publisher = self._container.try_resolve(OutboxPublisher)
        if publisher is None:
            logger.debug(
                "outbox_relay_idle", extra={"reason": "no OutboxPublisher bound"}
            )
            return

        published = await publisher.publish_pending(self._batch_size)
        if published:
            logger.info("outbox_relay_published", extra={"count": published})
