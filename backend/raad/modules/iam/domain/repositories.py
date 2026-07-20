"""Repository interfaces for the `iam` module (Backend LLD §5.1/§7.1/§7.2). Framework-free —
no SQLAlchemy/FastAPI/Pydantic.

Deliberately **not** extending `core.db.repository`'s `Repository`/`TenantScopedRepository`:
that module co-locates a SQLAlchemy-dependent concrete class (`SqlAlchemyRepositoryBase`) in
the same file, so importing anything from it — even just the interfaces — would make this
domain layer's import graph require SQLAlchemy to load at all, which is exactly what LLD §5.3
("the domain imports no framework, ORM, or I/O") forbids. These interfaces are declared fresh
instead, matching the same conceptual shape as the LLD §7.2 contract skeleton. The concrete
`infra/repositories.py` implementation (a later phase) is free to also satisfy
`core.db.repository.TenantScopedRepository` if useful — that's an infra-layer decision.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.tenancy.principal import Role
from raad.modules.iam.domain.entities import RefreshToken, User
from raad.modules.iam.domain.value_objects import (
    Email,
    PhoneNumber,
    RefreshTokenId,
    UserId,
)


class UserRepository(ABC):
    """Tenant scoping (Phase 2 §12.3/§17.4) applies here too — `organization_id=None` is only
    valid for RAAD-staff roles, and this repository's implementation is expected to enforce
    the same tenant/region scope as every other module's repository, not a shortcut version.
    """

    @abstractmethod
    async def get(self, user_id: UserId) -> User | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_email(self, email: Email) -> User | None:
        """Backs the global email-uniqueness constraint (Database Design §4.3)."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_phone(self, phone: PhoneNumber) -> User | None:
        """Backs the global phone-uniqueness constraint (Database Design §4.3)."""
        raise NotImplementedError

    @abstractmethod
    def add(self, user: User) -> None:
        """Persistence of changes is flushed by the Unit of Work, not the repository (§7.1)."""
        raise NotImplementedError

    @abstractmethod
    async def list_all(self) -> list[User]:
        """Backs `GET /users` (API Contracts §4.1) — Backend Stabilization phase addition.
        Previously deferred (`api/routers.py`'s own module docstring: "no listing use-case...
        needs `effective_org_scope` — still pending") specifically because `ScopeResolver`
        didn't exist yet; ADR-0005 resolves that blocker. Not itself scope-filtered yet — the
        same system-wide, already-flagged gap every other `list_all()` in this codebase
        carries."""
        raise NotImplementedError


class RefreshTokenRepository(ABC):
    @abstractmethod
    async def get(self, token_id: RefreshTokenId) -> RefreshToken | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_token_hash(self, token_hash: str) -> RefreshToken | None:
        """Lookup path for verifying a presented refresh token (Database Design §4.5:
        `token_hash CHAR(64)` unique)."""
        raise NotImplementedError

    @abstractmethod
    def add(self, refresh_token: RefreshToken) -> None:
        raise NotImplementedError


class RolePermissionRepository(ABC):
    """Backs the RBAC permission matrix (Database Design §4.4: `role_permissions(role_key,
    permission_key)`, "seedable reference data... editable by Founder... without code change").
    Pure reference/grant data — no aggregate lifecycle beyond grant/revoke, so this repository
    operates on primitives (`Role`, `Permission`) directly rather than a dedicated domain
    entity, mirroring how `student_parents` (a pure link table) needed no richer aggregate
    either (`transport_ops.domain.entities.StudentParent`'s own precedent).

    **Scope reduction, flagged:** Database Design §4.4 also names `roles`/`permissions`
    reference tables (id/label metadata for a future admin UI). Neither is built here — nothing
    in this codebase consumes a human-readable label yet, and `Role` is already a fixed Python
    `Enum` (`core.tenancy.principal.Role`) used pervasively across every module; making the role
    *set* itself dynamic would be a breaking change to `Principal.role`'s type well beyond this
    phase's "resolve confirmed issues, prefer minimal changes" mandate. What IS built —
    `role_permissions` — is the operationally load-bearing table: which permissions a role
    holds, editable without a code deploy, exactly as documented.
    """

    @abstractmethod
    async def list_permissions_for_role(self, role: Role) -> frozenset[str]:
        """Returns every `Permission` key granted to `role`. Used by the concrete
        `PermissionEvaluator` (`infra/permission_evaluator.py`)."""
        raise NotImplementedError

    @abstractmethod
    async def grant(self, role: Role, permission: str) -> None:
        """Idempotent: granting an already-held permission is a no-op, not an error."""
        raise NotImplementedError

    @abstractmethod
    async def revoke(self, role: Role, permission: str) -> None:
        """Idempotent: revoking a permission the role never held is a no-op."""
        raise NotImplementedError
