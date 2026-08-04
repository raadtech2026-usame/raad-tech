"""Outbound ports the `iam` application layer depends on (Backend LLD §4.2). `UnitOfWork` is
the existing core abstraction (`core.db.unit_of_work`), extended here with `iam`'s own
repositories — exactly the pattern that module's own docstring anticipates ("per-module
repository properties ... are added by each module's own UoW extension once that module's
domain/infra exist"). `Clock`, `IdGenerator`, `TokenService`, `PasswordHasher`, and
`PasswordPolicy` are likewise existing core ports, used as constructor dependencies by the
application services (`services.py`) — never redefined here.

`core.db.unit_of_work` co-locates the abstract `UnitOfWork` with its concrete
`SqlAlchemyUnitOfWork` implementation in the same file, so importing the interface
transitively requires SQLAlchemy to be installed. That's accepted deliberately here — unlike
the domain layer's zero-tolerance rule (Phase 5.1's `core.db.repository` situation),
SQLAlchemy is an already-approved project dependency (Phase 4.4), this application layer's own
code never references it directly, and the LLD's own `application/ports.py` contract skeleton
(§4.2) explicitly expects `interface UnitOfWork` to be referenced from exactly this file.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.db.unit_of_work import UnitOfWork
from raad.core.tenancy.principal import Role
from raad.modules.iam.domain.repositories import (
    RefreshTokenRepository,
    RolePermissionRepository,
    UserRepository,
)


class SessionCapPort(ABC):
    """ADR-0019: resolves the per-role concurrent-session cap from `platform_audit`'s
    `SystemSetting` store (`key="session_cap"`) — a live, admin-editable value (`PATCH
    /admin/settings`), not a `Settings`-object default like `LockoutSettings`. `iam` depends
    only on this abstract port, defined in its own application layer; the concrete adapter
    (`core/di/session_cap_adapter.py`) is the one place that actually reaches into
    `platform_audit`'s application facade, matching `.claude/rules/backend.md` #3's "cross-
    context data comes from the owning module's application service" — never a cross-module DB
    read, and never something `iam`'s own domain/infra/application code does directly.
    """

    @abstractmethod
    async def get_max_sessions(self, *, role: Role) -> int:
        raise NotImplementedError


class IamUnitOfWork(UnitOfWork):
    """Bundles the repositories `iam`'s use-cases need onto one transaction boundary (LLD
    §8.2 contract skeleton: `trips: TripRepository`, etc. — declared as plain attributes,
    matching that skeleton's own style, not abstract methods). The concrete implementation is
    `infra.repositories.SqlAlchemyIamUnitOfWork`.

    `role_permissions` added for the RBAC permission matrix (Database Design §4.4) — see
    `domain/repositories.py`'s `RolePermissionRepository` docstring."""

    users: UserRepository
    refresh_tokens: RefreshTokenRepository
    role_permissions: RolePermissionRepository
