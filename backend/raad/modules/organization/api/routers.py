"""HTTP surface of the `organization` module (C2) — Phase 6.4. `organizations_router` mounts
at `/api/v1/organizations`, `regions_router` at `/api/v1/regions` (`interfaces/http/api_v1.py`).

Thin controllers only (Backend LLD §16.2): parse the request DTO, call exactly one
application-service method, return the response DTO. No business logic, no repository/
SQLAlchemy access, no aggregate manipulation — every error raised by the application/domain
layers already maps to the standard `ErrorEnvelope` via the global exception handlers
(`core/errors/handlers.py`, registered once in `main.py`); routers never build an error
response themselves. Mirrors `iam.api.routers`'s Phase 5.4 shape exactly: every route below is
authorization-gated via `require_permission` (`interfaces/http/deps.py`), resolving against the
real seeded RBAC permission matrix (ADR-0004), per API Contracts §4.1's role column and §3.1's
authorization layering.

**`GET /organizations` / `GET /regions` (list) — added under the Backend Stabilization phase.**
Previously deferred here for exactly the reason this same paragraph used to give: no listing
use-case/repository method existed, and API Contracts §4.1 requires the organizations list to
be scope-filtered (Founder/all, Reg.Mgr/region, Support/assigned), which needed
`effective_org_scope` — itself pending at the time. `ScopeResolver` (ADR-0005) is now real, and
`list_organizations`/`list_regions` now exist (`application/services.py`) — but **neither list
route is itself scope-filtered yet**, the same system-wide, already-flagged gap every other
`list_all()`-backed endpoint in this codebase carries (CLAUDE.md's "Known gaps": retrofitting
real per-request scope-filtering onto every existing list endpoint at once is a separate, larger
change, not bundled into this addition for consistency's sake).

**Endpoints deliberately not implemented** (see this module's own docstrings for why touching
Domain/Application is out of scope this phase):
- `POST /regions/{id}/assignments` — `organization.domain.entities`'s own docstring records
  `region_assignments`/`support_assignments` (Database Design §4.6) as deliberately deferred:
  module ownership isn't settled by the API contract rule (which routes only `/organizations`
  + `/regions` to this module), so it needs an explicit design decision, not an invented one
  here.
- `PATCH /organizations/{id}`'s `billing_model` field — see `UpdateOrganizationRequest`'s
  docstring (`api/schemas.py`): the `Organization` aggregate has no `change_billing_model`
  behavior by deliberate design (Phase 6.1), so only `status` is accepted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from raad.core.errors.exceptions import ValidationError
from raad.core.pagination import (
    FilterCondition,
    OffsetPageRequest,
    SortSpec,
)
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal
from raad.interfaces.http.deps import (
    get_filter_conditions,
    get_offset_page_request,
    get_search_query,
    get_sort_params,
    require_permission,
)
from raad.interfaces.http.pagination import OffsetPageResponse, to_offset_page_response
from raad.modules.organization.api.deps import (
    get_organization_service,
    get_organization_uow,
    get_region_service,
)
from raad.modules.organization.api.schemas import (
    CreateRegionRequest,
    OrganizationResponse,
    RegionResponse,
    RegisterOrganizationRequest,
    UpdateOrganizationRequest,
    UpdateRegionRequest,
)
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
    ListOrganizationsQuery,
    ListRegionsQuery,
    OrganizationDTO,
    RegionDTO,
)
from raad.modules.organization.application.services import (
    OrganizationApplicationService,
    RegionApplicationService,
)
from raad.modules.organization.domain.value_objects import BillingModel, OrgType

organizations_router = APIRouter()
regions_router = APIRouter()


def _parse_org_type(value: str) -> OrgType:
    try:
        return OrgType(value)
    except ValueError as exc:
        raise ValidationError(
            f"Unknown org_type: {value!r}", details={"field": "org_type"}
        ) from exc


def _parse_billing_model(value: str) -> BillingModel:
    try:
        return BillingModel(value)
    except ValueError as exc:
        raise ValidationError(
            f"Unknown billing_model: {value!r}", details={"field": "billing_model"}
        ) from exc


def _organization_dto_to_response(
    organization: OrganizationDTO,
) -> OrganizationResponse:
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        org_type=organization.org_type,
        parent_org_id=organization.parent_org_id,
        region_id=organization.region_id,
        billing_model=organization.billing_model,
        status=organization.status,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
    )


def _region_dto_to_response(region: RegionDTO) -> RegionResponse:
    return RegionResponse(
        id=region.id,
        name=region.name,
        geographic_scope=region.geographic_scope,
        status=region.status,
        created_at=region.created_at,
        updated_at=region.updated_at,
    )


@organizations_router.get(
    "",
    response_model=OffsetPageResponse[OrganizationResponse],
    status_code=status.HTTP_200_OK,
    summary="List organizations",
    description=(
        "Founder(all)/Reg.Mgr(region)/Support(assigned) (API Contracts §4.1). Not yet "
        "scope-filtered — see this file's module docstring. Paginated/filterable/sortable "
        "per §7/§8: `?page&page_size`, `?filter[field]=value`, `?sort=field`, `?q=`."
    ),
)
async def list_organizations(
    principal: Principal = Depends(
        require_permission(Permission("organization.organizations.read"))
    ),
    org_service: OrganizationApplicationService = Depends(get_organization_service),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[OrganizationResponse]:
    page = await org_service.list_organizations(
        ListOrganizationsQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _organization_dto_to_response)


@organizations_router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new organization",
    description=(
        "Founder, Reg.Mgr(region), Support(assigned) (API Contracts §4.1). Authorization "
        "uses `require_permission`, resolving against the real seeded RBAC permission matrix "
        "(ADR-0004), matching `iam.api.routers.create_user`'s posture."
    ),
)
async def register_organization(
    body: RegisterOrganizationRequest,
    principal: Principal = Depends(
        require_permission(Permission("organization.organizations.create"))
    ),
    org_service: OrganizationApplicationService = Depends(get_organization_service),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> OrganizationResponse:
    command = RegisterOrganizationCommand(
        name=body.name,
        org_type=_parse_org_type(body.org_type),
        region_id=body.region_id,
        billing_model=_parse_billing_model(body.billing_model),
        parent_org_id=body.parent_org_id,
        actor=principal,
    )
    organization = await org_service.register_organization(command, uow=uow)
    return _organization_dto_to_response(organization)


@organizations_router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get an organization by id",
    description=(
        "In-scope (API Contracts §4.1). Authorization resolves against the real seeded RBAC permission matrix — "
        "see `register_organization`'s note."
    ),
)
async def get_organization(
    organization_id: str,
    principal: Principal = Depends(
        require_permission(Permission("organization.organizations.read"))
    ),
    org_service: OrganizationApplicationService = Depends(get_organization_service),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> OrganizationResponse:
    organization = await org_service.get_organization_by_id(
        GetOrganizationByIdQuery(organization_id=organization_id), uow=uow
    )
    return _organization_dto_to_response(organization)


@organizations_router.patch(
    "/{organization_id}",
    response_model=OrganizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an organization's status",
    description=(
        "In-scope (API Contracts §4.1). Limited to the `status` transition the Application "
        "layer exposes — see `UpdateOrganizationRequest`'s docstring for why `billing_model` "
        "is not accepted here. Authorization resolves against the real seeded RBAC permission matrix — "
        "see `register_organization`'s note."
    ),
)
async def update_organization(
    organization_id: str,
    body: UpdateOrganizationRequest,
    principal: Principal = Depends(
        require_permission(Permission("organization.organizations.update"))
    ),
    org_service: OrganizationApplicationService = Depends(get_organization_service),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> OrganizationResponse:
    if body.status is None:
        raise ValidationError(
            "'status' must be provided.", details={"fields": ["status"]}
        )

    if body.status == "active":
        organization = await org_service.reactivate_organization(
            ReactivateOrganizationCommand(
                organization_id=organization_id, actor=principal
            ),
            uow=uow,
        )
    elif body.status == "suspended":
        organization = await org_service.suspend_organization(
            SuspendOrganizationCommand(
                organization_id=organization_id, actor=principal
            ),
            uow=uow,
        )
    elif body.status == "inactive":
        organization = await org_service.deactivate_organization(
            DeactivateOrganizationCommand(
                organization_id=organization_id, actor=principal
            ),
            uow=uow,
        )
    else:
        raise ValidationError(
            f"Unsupported status: {body.status!r}", details={"field": "status"}
        )

    return _organization_dto_to_response(organization)


@regions_router.get(
    "",
    response_model=OffsetPageResponse[RegionResponse],
    status_code=status.HTTP_200_OK,
    summary="List regions",
    description=(
        "Founder (API Contracts §4.1). Not yet scope-filtered — see this file's module "
        "docstring. Paginated/filterable/sortable per §7/§8."
    ),
)
async def list_regions(
    principal: Principal = Depends(
        require_permission(Permission("organization.regions.read"))
    ),
    region_service: RegionApplicationService = Depends(get_region_service),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[RegionResponse]:
    page = await region_service.list_regions(
        ListRegionsQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _region_dto_to_response)


@regions_router.post(
    "",
    response_model=RegionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new region",
    description=(
        "Founder (API Contracts §4.1). Authorization resolves against the real seeded RBAC permission matrix — "
        "see `register_organization`'s note."
    ),
)
async def create_region(
    body: CreateRegionRequest,
    principal: Principal = Depends(
        require_permission(Permission("organization.regions.create"))
    ),
    region_service: RegionApplicationService = Depends(get_region_service),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> RegionResponse:
    command = CreateRegionCommand(
        name=body.name, geographic_scope=body.geographic_scope, actor=principal
    )
    region = await region_service.create_region(command, uow=uow)
    return _region_dto_to_response(region)


@regions_router.get(
    "/{region_id}",
    response_model=RegionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a region by id",
    description=(
        "Founder (API Contracts §4.1). Authorization resolves against the real seeded RBAC permission matrix — "
        "see `register_organization`'s note."
    ),
)
async def get_region(
    region_id: str,
    principal: Principal = Depends(
        require_permission(Permission("organization.regions.read"))
    ),
    region_service: RegionApplicationService = Depends(get_region_service),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> RegionResponse:
    region = await region_service.get_region_by_id(
        GetRegionByIdQuery(region_id=region_id), uow=uow
    )
    return _region_dto_to_response(region)


@regions_router.patch(
    "/{region_id}",
    response_model=RegionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a region's status",
    description=(
        "Founder (API Contracts §4.1). Limited to the `status` transition the Application "
        "layer exposes. Authorization resolves against the real seeded RBAC permission matrix — "
        "see `register_organization`'s note."
    ),
)
async def update_region(
    region_id: str,
    body: UpdateRegionRequest,
    principal: Principal = Depends(
        require_permission(Permission("organization.regions.update"))
    ),
    region_service: RegionApplicationService = Depends(get_region_service),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> RegionResponse:
    if body.status is None:
        raise ValidationError(
            "'status' must be provided.", details={"fields": ["status"]}
        )

    if body.status == "active":
        region = await region_service.activate_region(
            ActivateRegionCommand(region_id=region_id, actor=principal), uow=uow
        )
    elif body.status == "inactive":
        region = await region_service.deactivate_region(
            DeactivateRegionCommand(region_id=region_id, actor=principal), uow=uow
        )
    else:
        raise ValidationError(
            f"Unsupported status: {body.status!r}", details={"field": "status"}
        )

    return _region_dto_to_response(region)
