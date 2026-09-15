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
from raad.core.time.clock import Clock
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
class OrganizationStatsDTO:
    """ADR-0020: "Total/Active/Suspended Organizations" + "New Organizations Today" KPIs.
    `by_status` uses the same lower-case status strings `OrganizationDTO.status` already does
    (`OrganizationStatus.value`) — never re-derived or re-cased here."""

    total: int
    by_status: dict[str, int]
    created_today: int


@dataclass(frozen=True)
class OrganizationDTO:
    id: str
    name: str
    org_type: str
    parent_org_id: str | None
    region_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    latitude: float | None
    longitude: float | None
    geofence_radius_m: int | None
    approaching_distance_m: int
    trial_started_at: datetime | None
    trial_ends_at: datetime | None
    #: Derived (`Organization.trial_state()`), never a stored column — see that method's own
    #: docstring and `domain.value_objects.TrialState` for why this is deliberately independent
    #: of `billing.SubscriptionStatus`.
    trial_state: str


@dataclass(frozen=True)
class RegionDTO:
    id: str
    name: str
    geographic_scope: str | None
    status: str
    created_at: datetime
    updated_at: datetime


def organization_to_dto(organization: Organization, *, clock: Clock) -> OrganizationDTO:
    """Shared mapper — the only place an `Organization` aggregate is projected into its DTO.

    `clock` is required (not defaulted/optional) so every call site is forced to supply the
    same clock the rest of that use-case already uses — `Organization.trial_state()` is a pure
    function of `(trial_ends_at, now)`, and every application-service method already holds
    `self._clock` for exactly this reason."""
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
        status=organization.status.value,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
        latitude=organization.latitude,
        longitude=organization.longitude,
        geofence_radius_m=organization.geofence_radius_m,
        approaching_distance_m=organization.approaching_distance_m,
        trial_started_at=organization.trial_started_at,
        trial_ends_at=organization.trial_ends_at,
        trial_state=organization.trial_state(clock=clock).value,
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
