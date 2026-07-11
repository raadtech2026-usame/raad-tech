"""Dead Letter Queue foundation (Backend LLD §11.3: "Retry with backoff, bounded attempts,
then dead-letter queue + alert"). Interface only — a concrete sink (a broker-backed DLQ topic,
or a DB table) is added once the broker (Phase 2 §4.3) is chosen; not implemented in this
phase (no RabbitMQ/Kafka, no new business table).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.events.base import DomainEvent


class DeadLetterQueue(ABC):
    @abstractmethod
    async def send(self, *, event: DomainEvent, error: str, attempts: int) -> None:
        raise NotImplementedError
