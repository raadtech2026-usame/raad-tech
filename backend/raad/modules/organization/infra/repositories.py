"""SQLAlchemy repository implementations for `organization` (Backend LLD §7, §8; Database
Design §4.1/§4.2). Compose `SqlAlchemyRepositoryBase` (`core.db.repository`) for common query
mechanics; every ORM ↔ domain conversion goes through `mappers.py` — repositories never return
an ORM model, only the domain aggregates `modules/organization/domain/repositories.py` declares
(§7.1's "aggregate-in/aggregate-out" rule).

**The identity-map problem this file solves** — identical to `iam.infra.repositories`'s own
docstring: because `get()`/`get_by_name()`/etc. return a plain domain object (not the tracked
ORM row), a handler that does `org = await uow.organizations.get(id); org.suspend(...)` mutates
only that detached domain object — SQLAlchemy's session never sees the change, since it only
dirty-tracks its own `OrganizationModel`/`RegionModel` instances. Per Phase 6.2, the application
layer never re-calls `add()` after such a mutation (reserved for genuinely new aggregates), so
this layer bridges the gap: each repository keeps a `{id: (domain_object, orm_row)}` map of
everything it has returned or added, and `flush_tracked_changes()` re-projects every tracked
domain object onto its row via the mapper immediately before commit — called by
`SqlAlchemyOrganizationUnitOfWork.commit()`, below.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.domain.entities import Organization, Region
from raad.modules.organization.domain.repositories import (
    OrganizationRepository,
    RegionRepository,
)
from raad.modules.organization.domain.value_objects import OrganizationId, RegionId
from raad.modules.organization.infra.mappers import (
    model_to_organization,
    model_to_region,
    organization_to_model,
    region_to_model,
)
from raad.modules.organization.infra.models import OrganizationModel, RegionModel


class SqlAlchemyOrganizationRepository(
    SqlAlchemyRepositoryBase[OrganizationModel], OrganizationRepository
):
    """`organizations` has no module-owned uniqueness constraint beyond its primary key
    (Database Design §4.2 lists no `UX` on `name`), matching
    `organization.domain.repositories.OrganizationRepository`'s own docstring — no
    `get_by_name` lookup exists here, unlike `SqlAlchemyRegionRepository` below."""

    model = OrganizationModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Organization, OrganizationModel]] = {}

    async def get(self, organization_id: OrganizationId) -> Organization | None:
        row = await self.get_by_id(str(organization_id))
        return self._track(row)

    def add(self, organization: Organization) -> None:
        model = organization_to_model(organization)
        super().add(model)
        self._tracked[str(organization.id)] = (organization, model)

    def flush_tracked_changes(self) -> None:
        for organization, model in self._tracked.values():
            organization_to_model(organization, existing=model)

    def _track(self, row: OrganizationModel | None) -> Organization | None:
        if row is None:
            return None
        organization = model_to_organization(row)
        self._tracked[row.id] = (organization, row)
        return organization


class SqlAlchemyRegionRepository(
    SqlAlchemyRepositoryBase[RegionModel], RegionRepository
):
    model = RegionModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._tracked: dict[str, tuple[Region, RegionModel]] = {}

    async def get(self, region_id: RegionId) -> Region | None:
        row = await self.get_by_id(str(region_id))
        return self._track(row)

    async def get_by_name(self, name: str) -> Region | None:
        statement = select(RegionModel).where(
            RegionModel.name == name, RegionModel.deleted_at.is_(None)
        )
        result = await self._session.execute(statement)
        return self._track(result.scalar_one_or_none())

    def add(self, region: Region) -> None:
        model = region_to_model(region)
        super().add(model)
        self._tracked[str(region.id)] = (region, model)

    def flush_tracked_changes(self) -> None:
        for region, model in self._tracked.values():
            region_to_model(region, existing=model)

    def _track(self, row: RegionModel | None) -> Region | None:
        if row is None:
            return None
        region = model_to_region(row)
        self._tracked[row.id] = (region, row)
        return region


class SqlAlchemyOrganizationUnitOfWork(SqlAlchemyUnitOfWork, OrganizationUnitOfWork):
    """Concrete `OrganizationUnitOfWork` (Backend LLD §8.2/§6.2). Constructs `organization`'s
    two repositories once the session is open, and re-syncs every tracked aggregate's in-place
    mutations onto its ORM row (`flush_tracked_changes`, above) immediately before delegating
    to `SqlAlchemyUnitOfWork.commit()` — which still owns the actual outbox-write +
    session-commit behavior, preserved exactly (§8.3), via `super().commit()`. Identical shape
    to `iam.infra.repositories.SqlAlchemyIamUnitOfWork`.
    """

    organizations: SqlAlchemyOrganizationRepository
    regions: SqlAlchemyRegionRepository

    async def __aenter__(self) -> "SqlAlchemyOrganizationUnitOfWork":
        await super().__aenter__()
        self.organizations = SqlAlchemyOrganizationRepository(self.session)
        self.regions = SqlAlchemyRegionRepository(self.session)
        return self

    async def commit(self) -> None:
        self.organizations.flush_tracked_changes()
        self.regions.flush_tracked_changes()
        await super().commit()
