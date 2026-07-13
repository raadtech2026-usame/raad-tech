"""Organization infrastructure layer (Backend LLD §6.2/§7/§8; Database Design §4.1/§4.2) —
Phase 6.3 scope. SQLAlchemy ORM models, ORM↔domain mappers, and the concrete
repositories/UnitOfWork that implement the domain's and application's interfaces. Importing
this package registers `OrganizationModel`/`RegionModel` onto `core.db.base.Base.metadata` —
not yet wired into `migrations/env.py` (deliberately deferred to the dedicated migrations
phase, mirroring IAM's own Phase 5.3 → 5.5 split). No HTTP/FastAPI, no new business rules —
`domain/` and `application/` are unchanged. Public surface of this package.
"""

from raad.modules.organization.infra.mappers import (
    model_to_organization,
    model_to_region,
    organization_to_model,
    region_to_model,
)
from raad.modules.organization.infra.models import OrganizationModel, RegionModel
from raad.modules.organization.infra.repositories import (
    SqlAlchemyOrganizationRepository,
    SqlAlchemyOrganizationUnitOfWork,
    SqlAlchemyRegionRepository,
)

__all__ = [
    "OrganizationModel",
    "RegionModel",
    "SqlAlchemyOrganizationRepository",
    "SqlAlchemyOrganizationUnitOfWork",
    "SqlAlchemyRegionRepository",
    "model_to_organization",
    "model_to_region",
    "organization_to_model",
    "region_to_model",
]
