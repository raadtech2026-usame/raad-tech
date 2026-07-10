"""Scope resolution port (Phase 2 §17.4 `effective_org_scope`).

The formula is fixed by approved architecture:

    Founder            -> ALL organizations
    RegionalManager    -> organizations WHERE region_id IN user.assigned_regions
    SupportStaff       -> organizations WHERE org_id IN user.assigned_orgs
    FinanceStaff       -> billing data only; ops monitoring only if explicitly granted
    (tenant roles)     -> the principal's own organization_id only

The concrete resolver needs `region_assignments` / `support_assignments` / `org_users` data,
which is owned by the `organization` and `iam` modules (not yet implemented). Only the
interface is defined here, per this phase's foundation-only scope for tenancy.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from raad.core.tenancy.principal import Principal
from raad.core.tenancy.scope import TenantRegionScope


class ScopeResolver(ABC):
    @abstractmethod
    async def effective_org_scope(self, principal: Principal) -> TenantRegionScope:
        """Resolves the given principal's effective organization/region scope. Implemented
        once the organization module's region/assignment data is available."""
        raise NotImplementedError
