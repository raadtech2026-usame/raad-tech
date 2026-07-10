"""Unit of Work — interface only (Backend LLD §8).

Owns the transaction boundary for a single command: wraps a database session, buffers
domain events, and commits business rows + outbox rows atomically. The concrete
`SqlAlchemyUnitOfWork` (§6.2) is added once the persistence layer (engine, session factory,
ORM models — Phase 3.2) is wired in a later phase; per-module repository properties (e.g.
`trips: TripRepository`) are likewise added by each module's own UoW extension once that
module's domain/infra exist, rather than being hardcoded here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Sequence

from raad.core.events.base import DomainEvent


class UnitOfWork(ABC):
    """Context-managed. One instance per command, request-scoped via DI (§9.1)."""

    async def __aenter__(self) -> "UnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    @abstractmethod
    def record_events(self, events: Sequence[DomainEvent]) -> None:
        """Buffers domain events raised by aggregate behavior for atomic, post-commit
        publication via the outbox (§4.3 step 5, §10)."""
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        """Persists business rows and buffered events' outbox rows in one transaction."""
        raise NotImplementedError

    @abstractmethod
    async def rollback(self) -> None:
        raise NotImplementedError
