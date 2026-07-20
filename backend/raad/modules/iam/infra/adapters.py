"""External adapters for `iam` — concrete implementations of `core/` ports that need this
module's own data (Backend LLD §6.2/§6.3 Anti-Corruption Layer).

**`IamPermissionEvaluator`** is the concrete `core.security.permissions.PermissionEvaluator`
(Database Design §4.4's RBAC permission matrix). It lives here, not in `core/`, because `core`
must depend on nothing in `modules/` (LLD §17's own rule) — the same dependency-inversion
pattern every other concrete port implementation in this codebase already follows (e.g.
`billing.infra.repositories.SqlAlchemyBillingUnitOfWork` implementing `core.db.unit_of_work.
UnitOfWork`). Takes a `uow_factory` rather than a single `IamUnitOfWork` instance so every
`has_permission` call gets its own fresh session — `require_permission` runs once per request,
same lifecycle every other per-request `UnitOfWork` already has.
"""

from __future__ import annotations

from typing import Callable

from raad.core.security.permissions import Permission, PermissionEvaluator
from raad.core.tenancy.principal import Principal
from raad.modules.iam.application.ports import IamUnitOfWork


class IamPermissionEvaluator(PermissionEvaluator):
    def __init__(self, uow_factory: Callable[[], IamUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def has_permission(
        self, principal: Principal, permission: Permission
    ) -> bool:
        uow = self._uow_factory()
        async with uow:
            granted = await uow.role_permissions.list_permissions_for_role(
                principal.role
            )
            return str(permission) in granted
