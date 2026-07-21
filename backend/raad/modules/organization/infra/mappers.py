"""ORM ↔ Domain mappers for `organization` (Backend LLD §7.1 "aggregate-in/aggregate-out";
§17 `db`). Mappers own **every** conversion between SQLAlchemy rows and domain objects —
repositories (`repositories.py`) never construct or read ORM columns directly outside calling
these functions, and never return an ORM model to a caller. Mirrors `iam.infra.mappers`'s
`existing=` in-place-update pattern exactly.
"""

from __future__ import annotations

from datetime import datetime

from raad.modules.organization.domain.entities import Organization, Region
from raad.modules.organization.domain.value_objects import (
    BillingModel,
    OrganizationId,
    OrganizationStatus,
    OrgType,
    RegionId,
    RegionStatus,
)
from raad.modules.organization.infra.models import OrganizationModel, RegionModel


def _naive(value: datetime | None) -> datetime | None:
    """Strips tzinfo before a domain-computed timestamp crosses into a `DateTime(timezone=
    False)` column (ADR-0002) — the same pattern `fleet_device`/`iam`/`tracking.infra.
    mappers`'s own `_naive` helper already applies. `created_at`/`updated_at` are set from
    `Clock.now()` (tz-aware, `SystemClock`) in the domain layer; the DB columns are
    naive-UTC-by-convention (`core.db.mixins.utcnow`'s own discipline)."""
    return value.replace(tzinfo=None) if value is not None and value.tzinfo else value


def organization_to_model(
    organization: Organization, *, existing: OrganizationModel | None = None
) -> OrganizationModel:
    """Projects an `Organization` aggregate onto its ORM row. If `existing` is given, mutates
    and returns that same instance (so the SQLAlchemy session keeps tracking the one row it
    already knows about, rather than a duplicate) — otherwise constructs a new
    `OrganizationModel`."""
    model = (
        existing if existing is not None else OrganizationModel(id=str(organization.id))
    )
    model.name = organization.name
    model.org_type = organization.org_type.value
    model.parent_org_id = (
        str(organization.parent_org_id)
        if organization.parent_org_id is not None
        else None
    )
    model.region_id = str(organization.region_id)
    model.billing_model = organization.billing_model.value
    model.status = organization.status.value
    model.created_at = _naive(organization.created_at)
    model.updated_at = _naive(organization.updated_at)
    return model


def model_to_organization(model: OrganizationModel) -> Organization:
    return Organization(
        id=OrganizationId(model.id),
        name=model.name,
        org_type=OrgType(model.org_type),
        parent_org_id=(
            OrganizationId(model.parent_org_id) if model.parent_org_id else None
        ),
        region_id=RegionId(model.region_id),
        billing_model=BillingModel(model.billing_model),
        status=OrganizationStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def region_to_model(
    region: Region, *, existing: RegionModel | None = None
) -> RegionModel:
    model = existing if existing is not None else RegionModel(id=str(region.id))
    model.name = region.name
    model.geographic_scope = region.geographic_scope
    model.status = region.status.value
    model.created_at = _naive(region.created_at)
    model.updated_at = _naive(region.updated_at)
    return model


def model_to_region(model: RegionModel) -> Region:
    return Region(
        id=RegionId(model.id),
        name=model.name,
        geographic_scope=model.geographic_scope,
        status=RegionStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
