"""Organization application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite read-models).
DTOs are plain dataclasses — the boundary between the domain's aggregates and any future
API/infra layer, so neither ever depends on the other's internal shape. Mirrors
`iam.application.queries`'s shape exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from raad.core.pagination import (
    FilterCondition,
    OffsetPageRequest,
    SortSpec,
)
from raad.modules.organization.domain.entities import Organization, Region


@dataclass(frozen=True)
class GetOrganizationByIdQuery:
    organization_id: str


@dataclass(frozen=True)
class ListOrganizationsQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class GetRegionByIdQuery:
    region_id: str


@dataclass(frozen=True)
class ListRegionsQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class OrganizationDTO:
    id: str
    name: str
    org_type: str
    parent_org_id: str | None
    region_id: str
    billing_model: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RegionDTO:
    id: str
    name: str
    geographic_scope: str | None
    status: str
    created_at: datetime
    updated_at: datetime


def organization_to_dto(organization: Organization) -> OrganizationDTO:
    """Shared mapper — the only place an `Organization` aggregate is projected into its DTO."""
    return OrganizationDTO(
        id=str(organization.id),
        name=organization.name,
        org_type=organization.org_type.value,
        parent_org_id=(
            str(organization.parent_org_id)
            if organization.parent_org_id is not None
            else None
        ),
        region_id=str(organization.region_id),
        billing_model=organization.billing_model.value,
        status=organization.status.value,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
    )


def region_to_dto(region: Region) -> RegionDTO:
    """Shared mapper — the only place a `Region` aggregate is projected into its DTO."""
    return RegionDTO(
        id=str(region.id),
        name=region.name,
        geographic_scope=region.geographic_scope,
        status=region.status.value,
        created_at=region.created_at,
        updated_at=region.updated_at,
    )
