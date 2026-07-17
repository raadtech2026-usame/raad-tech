"""Role & Permission foundation (Backend LLD §17 `security`: "RBAC permission matrix,
permission dependencies"; Phase 2 §12.2).

`Role` (the closed set of roles) already lives in `core/tenancy/principal.py` — re-exported
here for a single `core.security` import surface. `Permission` is the string-keyed capability
type; the concrete **matrix** (which permissions each role holds) is deliberately not defined
here — it is authorization *business data* that isn't in the approved documentation yet (only
the roles and the general RBAC/tenant/region shape are, Phase 2 §12.2/§17.4). Defining it now
would mean inventing per-role capabilities without an approved source, which this phase's
scope explicitly forbids (foundation/interfaces only, no business logic).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import NewType

from raad.core.tenancy.principal import Principal, Role

Permission = NewType("Permission", str)


class PermissionEvaluator(ABC):
    """Authorization contract: given an authenticated `Principal`, does it hold the given
    `Permission`? The concrete matrix-backed implementation is added once the RBAC permission
    matrix (Phase 2 §12.2) is formally approved and owned by `modules/iam`."""

    @abstractmethod
    async def has_permission(
        self, principal: Principal, permission: Permission
    ) -> bool:
        raise NotImplementedError


__all__ = ["Permission", "PermissionEvaluator", "Principal", "Role"]
