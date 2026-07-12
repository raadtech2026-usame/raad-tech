"""Repository interfaces for the `organization` module (Backend LLD §5.1/§7.1/§7.2).
Framework-free — no SQLAlchemy/FastAPI/Pydantic.

Deliberately **not** extending `core.db.repository`'s `Repository`/`TenantScopedRepository`,
for the same reason `iam.domain.repositories` doesn't: that module co-locates a SQLAlchemy-
dependent concrete class in the same file, so importing anything from it would force this
domain layer's import graph to require SQLAlchemy (forbidden by LLD §5.3 / `.claude/rules/
backend.md` #2). The concrete `infra/repositories.py` implementation (a later phase) is free
to also satisfy `core.db.repository`'s interfaces if useful — an infra-layer decision.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.modules.organization.domain.entities import Organization, Region
from raad.modules.organization.domain.value_objects import OrganizationId, RegionId


class OrganizationRepository(ABC):
    """`organizations` has no module-owned uniqueness constraint beyond its primary key
    (Database Design §4.2 lists no `UX` on `name`) — so unlike `iam.UserRepository`, no
    `get_by_*` uniqueness-backing lookup is needed yet."""

    @abstractmethod
    async def get(self, organization_id: OrganizationId) -> Organization | None:
        raise NotImplementedError

    @abstractmethod
    def add(self, organization: Organization) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError


class RegionRepository(ABC):
    @abstractmethod
    async def get(self, region_id: RegionId) -> Region | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_name(self, name: str) -> Region | None:
        """Backs the global region-name-uniqueness constraint (Database Design §4.1: `name`
        is `UX`)."""
        raise NotImplementedError

    @abstractmethod
    def add(self, region: Region) -> None:
        raise NotImplementedError
