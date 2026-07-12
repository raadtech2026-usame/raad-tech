"""Organization domain layer (Backend LLD §5; Database Design §4.1/§4.2) — Phase 6.1 scope.

Framework-free: entities/value objects/events/repository interfaces only. No application
services, no infra, no DI — those are later phases. Public surface of this package.

Scope: `Organization` and `Region` only. `OrgSettings` (§4.7) and `region_assignments`/
`support_assignments` (§4.6) are deliberately deferred pending an explicit design decision —
see `entities.py`'s module docstring for why.
"""

from raad.modules.organization.domain.entities import Organization, Region
from raad.modules.organization.domain.repositories import (
    OrganizationRepository,
    RegionRepository,
)
from raad.modules.organization.domain.value_objects import (
    BillingModel,
    OrgType,
    OrganizationId,
    OrganizationStatus,
    RegionId,
    RegionStatus,
)

__all__ = [
    "BillingModel",
    "Organization",
    "OrganizationId",
    "OrganizationRepository",
    "OrganizationStatus",
    "OrgType",
    "Region",
    "RegionId",
    "RegionRepository",
    "RegionStatus",
]
