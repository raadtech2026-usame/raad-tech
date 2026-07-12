"""Organization application layer (Backend LLD §4) — Phase 6.2 scope.

Orchestration only: loads aggregates via repositories bound to `OrganizationUnitOfWork`,
invokes domain behavior, records the resulting `DomainEvent`s, commits, and returns a DTO. No
FastAPI/SQLAlchemy, no infra, no business rules (those live in `modules/organization/domain`).
Public surface of this package.
"""

from raad.modules.organization.application.commands import (
    ActivateRegionCommand,
    CreateRegionCommand,
    DeactivateOrganizationCommand,
    DeactivateRegionCommand,
    ReactivateOrganizationCommand,
    RegisterOrganizationCommand,
    SuspendOrganizationCommand,
)
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.application.queries import (
    GetOrganizationByIdQuery,
    GetRegionByIdQuery,
    OrganizationDTO,
    RegionDTO,
)
from raad.modules.organization.application.services import (
    OrganizationApplicationService,
    RegionApplicationService,
)

__all__ = [
    "ActivateRegionCommand",
    "CreateRegionCommand",
    "DeactivateOrganizationCommand",
    "DeactivateRegionCommand",
    "GetOrganizationByIdQuery",
    "GetRegionByIdQuery",
    "OrganizationApplicationService",
    "OrganizationDTO",
    "OrganizationUnitOfWork",
    "ReactivateOrganizationCommand",
    "RegionApplicationService",
    "RegionDTO",
    "RegisterOrganizationCommand",
    "SuspendOrganizationCommand",
]
