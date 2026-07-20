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

    @abstractmethod
    async def list_ids_by_region_ids(
        self, region_ids: frozenset[str]
    ) -> frozenset[str]:
        """Backs `ScopeResolver`'s Regional Manager formula (Phase 2 §17.4: "organizations
        WHERE region_id IN user.assigned_regions"). An in-module query (`organizations` and
        `region_assignments` are both owned by this same module), not a cross-module read."""
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


class ScopeAssignmentRepository(ABC):
    """Backs `region_assignments`/`support_assignments` (Database Design §4.6): "RAAD-staff
    scoping... applied as an *additional* scope filter." Previously deferred in this module's
    own `domain/entities.py` docstring ("needs an explicit design decision before
    implementation") — built now under the Backend Stabilization phase's explicit authority to
    resolve confirmed architectural gaps (`core.tenancy.resolver.ScopeResolver` has been an
    unbound interface since Phase 4.3 for exactly this reason).

    Pure grant/revoke reference data, no aggregate lifecycle — mirrors `iam.domain.repositories.
    RolePermissionRepository`'s identical "no rich entity, primitives in and out" shape for the
    analogous `role_permissions` table.
    """

    @abstractmethod
    async def list_assigned_region_ids(self, user_id: str) -> frozenset[str]:
        raise NotImplementedError

    @abstractmethod
    async def list_assigned_organization_ids(self, user_id: str) -> frozenset[str]:
        raise NotImplementedError

    @abstractmethod
    async def grant_region(
        self, user_id: str, region_id: str, *, granted_by: str | None
    ) -> None:
        """Idempotent: granting an already-held region assignment is a no-op."""
        raise NotImplementedError

    @abstractmethod
    async def revoke_region(self, user_id: str, region_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def grant_organization(
        self, user_id: str, organization_id: str, *, granted_by: str | None
    ) -> None:
        """Idempotent: granting an already-held support (org) assignment is a no-op."""
        raise NotImplementedError

    @abstractmethod
    async def revoke_organization(self, user_id: str, organization_id: str) -> None:
        raise NotImplementedError
