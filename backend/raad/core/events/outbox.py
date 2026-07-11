"""Outbox infrastructure (Backend LLD §10, §17 `events`; Database Design §8.8).

`OutboxRecord` is the ORM model for the `outbox` table; `OutboxWriter` writes a `DomainEvent`
into it using the caller's own `AsyncSession` — deliberately *not* committing that session
itself, so the insert lands in the same transaction as the business change that raised the
event (`SqlAlchemyUnitOfWork.commit`, `core/db/unit_of_work.py` — the "no event without a
committed state change" guarantee, LLD §8.3).

`SqlOutboxPublisher` is the read/relay side (§10.2, §11.2 "Outbox Relay"): it queries
unpublished rows and hands each to a `BrokerPort` — broker-agnostic, since no broker
implementation is chosen yet (Phase 2 §4.3 is still an open item). The Outbox Relay *worker*
that runs this on an interval is `interfaces/workers/outbox_relay.py`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CHAR, JSON, Integer, String, select
from sqlalchemy.dialects.mysql import DATETIME as MySqlDateTime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from raad.core.db.base import Base
from raad.core.db.mixins import UlidPrimaryKeyMixin, utcnow
from raad.core.events.base import DomainEvent
from raad.core.events.ports import BrokerPort, OutboxPublisher


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


class SqlOutboxPublisher(OutboxPublisher):
    """Concrete `OutboxPublisher`: queries the oldest `batch_size` unpublished rows, publishes
    each via the given `BrokerPort`, and marks `published_at` — all in one session/commit per
    call, so a crash mid-batch leaves already-published rows correctly marked and the rest
    still pending (safe to re-run, §11.2's "Marks published_at; safe re-run")."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], broker: BrokerPort
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker

    async def publish_pending(self, batch_size: int) -> int:
        async with self._session_factory() as session:
            statement = (
                select(OutboxRecord)
                .where(OutboxRecord.published_at.is_(None))
                .order_by(OutboxRecord.created_at)
                .limit(batch_size)
            )
            rows = (await session.execute(statement)).scalars().all()

            for row in rows:
                event = DomainEvent(
                    event_id=row.event_id,
                    event_type=row.event_type,
                    version=row.event_version,
                    occurred_at=row.created_at,
                    org_id=row.organization_id,
                    correlation_id=row.correlation_id,
                    payload=row.payload_json,
                    aggregate_type=row.aggregate_type,
                    aggregate_id=row.aggregate_id,
                )
                await self._broker.publish(event)
                row.published_at = utcnow()

            await session.commit()
            return len(rows)
