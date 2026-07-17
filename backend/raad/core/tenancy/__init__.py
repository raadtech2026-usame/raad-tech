"""Tenant + region scope context (Backend LLD §17; Phase 2 §12.3/§17.4). Foundation only —
concrete scope resolution is wired once the `organization`/`iam` modules exist."""

from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.resolver import ScopeResolver
from raad.core.tenancy.scope import TenantRegionScope

__all__ = ["Principal", "Role", "ScopeResolver", "TenantRegionScope"]
