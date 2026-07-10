"""Effective tenant/region scope (Phase 2 §12.3, §17.4).

`TenantRegionScope` is the resolved set of organizations a principal may access. It is applied
as a mandatory filter at the repository layer (§7.1) — never left to the caller to remember.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TenantRegionScope:
    """`organization_ids=None` means unrestricted (Founder, global scope, Phase 2 §17.3).
    Any other value is the explicit allow-set a query must be filtered by — e.g. a Regional
    Manager's `organizations WHERE region_id IN assigned_regions` (§17.4), or a tenant user's
    own single organization."""

    organization_ids: frozenset[str] | None
    region_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_unrestricted(self) -> bool:
        return self.organization_ids is None

    def allows(self, organization_id: str) -> bool:
        return self.is_unrestricted or organization_id in self.organization_ids
