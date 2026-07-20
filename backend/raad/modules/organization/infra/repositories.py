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

from datetime import datetime, timezone

from raad.core.db.repository import SqlAlchemyRepositoryBase
from raad.core.db.unit_of_work import SqlAlchemyUnitOfWork
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.domain.entities import Organization, Region
from raad.modules.organization.domain.repositories import (
    OrganizationRepository,
    RegionRepository,
    ScopeAssignmentRepository,
)
from raad.modules.organization.domain.value_objects import OrganizationId, RegionId
from raad.modules.organization.infra.mappers import (
    model_to_organization,
    model_to_region,
    organization_to_model,
    region_to_model,
)
from raad.modules.organization.infra.models import (
    OrganizationModel,
    RegionAssignmentModel,
    RegionModel,
    SupportAssignmentModel,
)


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

    async def list_ids_by_region_ids(
        self, region_ids: frozenset[str]
    ) -> frozenset[str]:
        if not region_ids:
            return frozenset()
        statement = select(OrganizationModel.id).where(
            OrganizationModel.region_id.in_(region_ids),
            OrganizationModel.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        return frozenset(result.scalars().all())

    async def list_all(self) -> list[Organization]:
        """`list_scoped`'s org filter is inert here (`OrganizationModel` has no
        `organization_id` column — it *is* the tenant root), the identical situation
        `billing.infra.repositories.SqlAlchemyPlanRepository.list_all` already establishes for
        `PlanModel`; the soft-delete filter still applies."""
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [self._track(row) for row in rows]  # type: ignore[misc]

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

    async def list_all(self) -> list[Region]:
        """`RegionModel` has no `organization_id` either (a platform-level geographic
        division, not tenant-owned) — same inert-filter posture as
        `SqlAlchemyOrganizationRepository.list_all` above."""
        rows = await self.list_scoped(TenantRegionScope(organization_ids=None))
        return [self._track(row) for row in rows]  # type: ignore[misc]

    def flush_tracked_changes(self) -> None:
        for region, model in self._tracked.values():
            region_to_model(region, existing=model)

    def _track(self, row: RegionModel | None) -> Region | None:
        if row is None:
            return None
        region = model_to_region(row)
        self._tracked[row.id] = (region, row)
        return region


class SqlAlchemyScopeAssignmentRepository(ScopeAssignmentRepository):
    """No identity-map/`flush_tracked_changes` needed — pure grant data, same reasoning as
    `iam.infra.repositories.SqlAlchemyRolePermissionRepository`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_assigned_region_ids(self, user_id: str) -> frozenset[str]:
        statement = select(RegionAssignmentModel.region_id).where(
            RegionAssignmentModel.user_id == user_id
        )
        result = await self._session.execute(statement)
        return frozenset(result.scalars().all())

    async def list_assigned_organization_ids(self, user_id: str) -> frozenset[str]:
        statement = select(SupportAssignmentModel.organization_id).where(
            SupportAssignmentModel.user_id == user_id
        )
        result = await self._session.execute(statement)
        return frozenset(result.scalars().all())

    async def grant_region(
        self, user_id: str, region_id: str, *, granted_by: str | None
    ) -> None:
        existing = await self._session.get(
            RegionAssignmentModel, (user_id, region_id)
        )
        if existing is not None:
            return
        self._session.add(
            RegionAssignmentModel(
                user_id=user_id,
                region_id=region_id,
                granted_by=granted_by,
                granted_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

    async def revoke_region(self, user_id: str, region_id: str) -> None:
        existing = await self._session.get(
            RegionAssignmentModel, (user_id, region_id)
        )
        if existing is not None:
            await self._session.delete(existing)

    async def grant_organization(
        self, user_id: str, organization_id: str, *, granted_by: str | None
    ) -> None:
        existing = await self._session.get(
            SupportAssignmentModel, (user_id, organization_id)
        )
        if existing is not None:
            return
        self._session.add(
            SupportAssignmentModel(
                user_id=user_id,
                organization_id=organization_id,
                granted_by=granted_by,
                granted_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

    async def revoke_organization(self, user_id: str, organization_id: str) -> None:
        existing = await self._session.get(
            SupportAssignmentModel, (user_id, organization_id)
        )
        if existing is not None:
            await self._session.delete(existing)


class SqlAlchemyOrganizationUnitOfWork(SqlAlchemyUnitOfWork, OrganizationUnitOfWork):
    """Concrete `OrganizationUnitOfWork` (Backend LLD §8.2/§6.2). Constructs `organization`'s
    repositories once the session is open, and re-syncs every tracked aggregate's in-place
    mutations onto its ORM row (`flush_tracked_changes`, above) immediately before delegating
    to `SqlAlchemyUnitOfWork.commit()` — which still owns the actual outbox-write +
    session-commit behavior, preserved exactly (§8.3), via `super().commit()`. Identical shape
    to `iam.infra.repositories.SqlAlchemyIamUnitOfWork`.
    """

    organizations: SqlAlchemyOrganizationRepository
    regions: SqlAlchemyRegionRepository
    scope_assignments: SqlAlchemyScopeAssignmentRepository

    async def __aenter__(self) -> "SqlAlchemyOrganizationUnitOfWork":
        await super().__aenter__()
        self.organizations = SqlAlchemyOrganizationRepository(self.session)
        self.regions = SqlAlchemyRegionRepository(self.session)
        self.scope_assignments = SqlAlchemyScopeAssignmentRepository(self.session)
        return self

    async def commit(self) -> None:
        self.organizations.flush_tracked_changes()
        self.regions.flush_tracked_changes()
        await super().commit()
