"""External adapters for `organization` — concrete implementations of `core/` ports that need
this module's own data (Backend LLD §6.2/§6.3 Anti-Corruption Layer).

**`OrganizationScopeResolver`** is the concrete `core.tenancy.resolver.ScopeResolver` (Phase 2
§17.4's `effective_org_scope` formula, unbound since Phase 4.3 pending exactly this module's
region/assignment data — `domain/entities.py`'s own module docstring flagged this). Lives here,
not in `core/`, for the identical dependency-inversion reason `iam.infra.adapters.
IamPermissionEvaluator` does.

Formula (Phase 2 §17.4 verbatim):
    Founder            -> ALL organizations (unrestricted)
    RegionalManager    -> organizations WHERE region_id IN user.assigned_regions
    SupportStaff       -> organizations WHERE org_id IN user.assigned_orgs
    FinanceStaff       -> billing data only; ops monitoring only if explicitly granted
    (tenant roles)     -> the principal's own organization_id only

**Finance Staff, flagged.** No document names a separate assignment mechanism for Finance
Staff's "explicitly granted" ops scope — distinct from Support Staff's own `support_assignments`
grant. Reusing `support_assignments` for both (rather than inventing a third table no document
specifies) is this phase's own minimal, non-inventing choice: Finance Staff's *billing* access is
already governed entirely by the RBAC permission matrix (Layer 2, `role_permissions`), not by
this scope; this resolver only supplies the *ops-monitoring* scope Phase 2 §17.4 says defaults to
none "unless explicitly granted" — which `support_assignments` being empty for a given Finance
Staff user already satisfies by construction.
"""

from __future__ import annotations

from typing import Callable

from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.resolver import ScopeResolver
from raad.core.tenancy.scope import TenantRegionScope
from raad.modules.organization.application.ports import OrganizationUnitOfWork


class OrganizationScopeResolver(ScopeResolver):
    def __init__(self, uow_factory: Callable[[], OrganizationUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def effective_org_scope(self, principal: Principal) -> TenantRegionScope:
        if principal.role == Role.FOUNDER:
            return TenantRegionScope(organization_ids=None)

        if principal.role == Role.REGIONAL_MANAGER:
            uow = self._uow_factory()
            async with uow:
                region_ids = await uow.scope_assignments.list_assigned_region_ids(
                    principal.user_id
                )
                org_ids = await uow.organizations.list_ids_by_region_ids(region_ids)
            return TenantRegionScope(
                organization_ids=frozenset(org_ids), region_ids=region_ids
            )

        if principal.role in (Role.SUPPORT_STAFF, Role.FINANCE_STAFF):
            uow = self._uow_factory()
            async with uow:
                org_ids = await uow.scope_assignments.list_assigned_organization_ids(
                    principal.user_id
                )
            return TenantRegionScope(organization_ids=frozenset(org_ids))

        # Tenant roles (Org Admin, Driver, Parent): their own organization only.
        own_org = frozenset({principal.org_id}) if principal.org_id else frozenset()
        return TenantRegionScope(organization_ids=own_org)
