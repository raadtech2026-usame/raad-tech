"""Outbox infrastructure (Backend LLD §10, §17 `events`; Database Design §8.8).

`OutboxRecord` is the ORM model for the `outbox` table; `OutboxWriter` writes a `DomainEvent`
into it using the caller's own `AsyncSession` — deliberately *not* committing that session
itself, so the insert lands in the same transaction as the business change that raised the
event (`SqlAlchemyUnitOfWork.commit`, `core/db/unit_of_work.py` — the "no event without a
committed state change" guarantee, LLD §8.3).

Reading/publishing pending rows (`OutboxPublisher`, `core/events/ports.py`) is a separate
concern for the Outbox Relay worker, not implemented in this phase.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CHAR, JSON, Integer, String
from sqlalchemy.dialects.mysql import DATETIME as MySqlDateTime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import UlidPrimaryKeyMixin, utcnow
from raad.core.events.base import DomainEvent


class OutboxRecord(UlidPrimaryKeyMixin, Base):
    """`(id, event_id UX, event_type, event_version, aggregate_type, aggregate_id,
    organization_id, payload_json, correlation_id, created_at, published_at?)` — Database
    Design §8.8. Immutable except `published_at`, set once by the relay; no `updated_at` (this
    is a ledger, not a mutable business row, so `TimestampMixin` doesn't apply)."""

    __tablename__ = "outbox"

    event_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(CHAR(26), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(CHAR(26), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[Any] = mapped_column(
        MySqlDateTime(fsp=3), nullable=False, default=utcnow
    )
    published_at: Mapped[Any | None] = mapped_column(
        MySqlDateTime(fsp=3), nullable=True, default=None
    )


class OutboxWriter:
    """Persistence-support class writing event rows in the same transaction (LLD §6.2/§10)."""

    async def write(self, session: AsyncSession, event: DomainEvent) -> None:
        session.add(
            OutboxRecord(
                event_id=event.event_id,
                event_type=event.event_type,
                event_version=event.version,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                organization_id=event.org_id,
                payload_json=event.payload,
                correlation_id=event.correlation_id,
                created_at=event.occurred_at.replace(tzinfo=None),
            )
        )

    async def write_all(self, session: AsyncSession, events: list[DomainEvent]) -> None:
        for event in events:
            await self.write(session, event)
