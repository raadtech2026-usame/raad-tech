"""Repository base interfaces and SQLAlchemy infrastructure (Backend LLD §7.2).

Generic, aggregate-agnostic contracts. Each module defines its own aggregate-specific
repository interface in `modules/<context>/domain/repositories.py` by extending
`TenantScopedRepository` for its aggregate (e.g. a future `TripRepository(
TenantScopedRepository[Trip, TripId])`) — no aggregate-specific repository is defined here,
since no module's domain layer is implemented in this phase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, Sequence, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.base import Base
from raad.core.tenancy.scope import TenantRegionScope

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
    async def list(
        self, spec: Specification, page: int, page_size: int
    ) -> Page[TAggregate]:
        raise NotImplementedError


TModel = TypeVar("TModel", bound=Base)


class SqlAlchemyRepositoryBase(Generic[TModel]):
    """Infra-layer helper wrapping common query mechanics (session-bound CRUD, mandatory
    tenant/region scope filtering, soft-delete-aware reads) for a single ORM *model* class —
    not an aggregate. A module's concrete repository (`infra/repositories.py`) composes this
    (rather than implementing `Repository`/`TenantScopedRepository` by hand) and adds its own
    row<->aggregate mapping on top, per §7.1's "aggregate-in/aggregate-out" rule — this class
    only ever returns ORM rows, since it has no knowledge of any module's domain types.

    Set `model` in the subclass, e.g. `class DeviceModelRepo(SqlAlchemyRepositoryBase[Device
    ORM]): model = DeviceORM`.
    """

    model: type[TModel]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id_: str, *, include_deleted: bool = False) -> TModel | None:
        statement = select(self.model).where(self.model.id == id_)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            statement = statement.where(self.model.deleted_at.is_(None))
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    def add(self, instance: TModel) -> None:
        self._session.add(instance)

    async def list_scoped(
        self, scope: TenantRegionScope, *, include_deleted: bool = False
    ) -> Sequence[TModel]:
        """Applies the mandatory tenant/region scope filter (Phase 2 §17.4) to a model with an
        `organization_id` column — the single place tenant isolation is enforced at the
        persistence layer (Backend LLD §7.3), rather than trusting every call site to
        remember it."""
        statement = select(self.model)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            statement = statement.where(self.model.deleted_at.is_(None))
        if not scope.is_unrestricted and hasattr(self.model, "organization_id"):
            statement = statement.where(
                self.model.organization_id.in_(scope.organization_ids)
            )
        result = await self._session.execute(statement)
        return result.scalars().all()
