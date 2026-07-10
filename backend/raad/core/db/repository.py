"""Repository base interfaces — interfaces only (Backend LLD §7.2).

Generic, aggregate-agnostic contracts. Each module defines its own aggregate-specific
repository interface in `modules/<context>/domain/repositories.py` by extending
`TenantScopedRepository` for its aggregate (e.g. a future `TripRepository(
TenantScopedRepository[Trip, TripId])`) — no aggregate-specific repository is defined here,
since no module's domain layer is implemented in this phase.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

TAggregate = TypeVar("TAggregate")
TId = TypeVar("TId")


class Specification(ABC):
    """Marker base for query specifications passed to `TenantScopedRepository.list`."""


class Page(Generic[TAggregate]):
    """Minimal page envelope for repository list results. Finalized alongside
    `core/pagination` (not implemented in this phase)."""

    def __init__(self, items: list[TAggregate], total: int) -> None:
        self.items = items
        self.total = total


class Repository(ABC, Generic[TAggregate, TId]):
    """Persistence-ignorant collection abstraction for one aggregate root (§7.1). Persistence
    of changes is flushed by the Unit of Work, not the repository."""

    @abstractmethod
    async def get(self, id: TId) -> TAggregate | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, aggregate: TAggregate) -> None:
        raise NotImplementedError


class TenantScopedRepository(Repository[TAggregate, TId], ABC):
    """Every query is implicitly filtered by the active tenant/region scope
    (`TenantRegionScope`, core/tenancy) — this is where isolation is enforced in exactly one
    place (§7.3, Phase 2 §12.3)."""

    @abstractmethod
    async def list(self, spec: Specification, page: int, page_size: int) -> Page[TAggregate]:
        raise NotImplementedError
