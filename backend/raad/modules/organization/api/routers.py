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

**`scope_assignments_router` mounts at `/api/v1/scope-assignments`** (Priority 1 Item 6,
`PROJECT_STATUS.md`) — the design decision this module's own docstring used to say was still
pending: `region_assignments`/`support_assignments` (Database Design §4.6) are owned here (the
same module `ScopeAssignmentApplicationService` already lived in), not `iam` or
`platform_audit`, closing "RAAD can't onboard its own staff without hand-editing the DB." No
documented API Contracts surface exists for this either — built on the schema authority instead,
the same posture `iam.api.routers.roles_router` follows for the analogous `role_permissions`
gap.

**Endpoints deliberately not implemented** (see this module's own docstrings for why touching
Domain/Application is out of scope this phase):
- `PATCH /organizations/{id}`'s `billing_model` field — see `UpdateOrganizationRequest`'s
  docstring (`api/schemas.py`): `Organization` had no `change_billing_model` behavior even
  before ADR-0016 removed the field from the aggregate entirely, so only `status` is accepted.
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
    get_scope_assignment_service,
)
from raad.modules.organization.api.schemas import (
    CreateRegionRequest,
    GrantRegionAssignmentRequest,
    GrantSupportAssignmentRequest,
    OrganizationOnboardedResponse,
    OrganizationResponse,
    RegionResponse,
    RegisterOrganizationRequest,
    ScopeAssignmentsResponse,
    UpdateOrganizationRequest,
    UpdateRegionRequest,
)
from raad.modules.organization.application.commands import (
    ActivateRegionCommand,
    CreateRegionCommand,
    DeactivateOrganizationCommand,
    DeactivateRegionCommand,
    GrantRegionAssignmentCommand,
    GrantSupportAssignmentCommand,
    OnboardOrganizationCommand,
    ReactivateOrganizationCommand,
    RegisterOrganizationCommand,
    RevokeRegionAssignmentCommand,
    RevokeSupportAssignmentCommand,
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
    ScopeAssignmentApplicationService,
)
from raad.modules.organization.domain.value_objects import OrgType

organizations_router = APIRouter()
regions_router = APIRouter()
scope_assignments_router = APIRouter()


def _parse_org_type(value: str) -> OrgType:
    try:
        return OrgType(value)
    except ValueError as exc:
        raise ValidationError(
            f"Unknown org_type: {value!r}", details={"field": "org_type"}
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
    response_model=OrganizationOnboardedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Onboard a new organization",
    description=(
        "Founder, Reg.Mgr(region), Support(assigned) (API Contracts §4.1). Authorization "
        "uses `require_permission`, resolving against the real seeded RBAC permission matrix "
        "(ADR-0004), matching `iam.api.routers.create_user`'s posture. ADR-0017 (RAAD business "
        "model realignment): also provisions the Organization's first Org Admin login "
        "(`iam.User`, role=org_admin) with a generated one-time temporary password, returned "
        "here exactly once for hand-off — the previously fully-manual, two-step process is "
        "now one guided workflow."
    ),
)
async def register_organization(
    body: RegisterOrganizationRequest,
    principal: Principal = Depends(
        require_permission(Permission("organization.organizations.create"))
    ),
    org_service: OrganizationApplicationService = Depends(get_organization_service),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> OrganizationOnboardedResponse:
    command = OnboardOrganizationCommand(
        name=body.name,
        org_type=_parse_org_type(body.org_type),
        region_id=body.region_id,
        parent_org_id=body.parent_org_id,
        admin_full_name=body.admin_full_name,
        admin_email=body.admin_email,
        admin_phone=body.admin_phone,
        actor=principal,
    )
    organization, admin_user_id, temporary_password = await org_service.onboard_organization(
        command, uow=uow
    )
    return OrganizationOnboardedResponse(
        organization=_organization_dto_to_response(organization),
        admin_user_id=admin_user_id,
        temporary_password=temporary_password,
    )


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


# --- RAAD-staff scope-assignment management (Priority 1 Item 6, PROJECT_STATUS.md) ------------
#
# Founder-only in the seeded matrix — controls who else can act as a Regional Manager/Support
# Staff at all, the platform-configuration equivalent of `iam.role_permissions.*`.


@scope_assignments_router.get(
    "/{user_id}",
    response_model=ScopeAssignmentsResponse,
    summary="List a user's region and support scope assignments",
)
async def get_scope_assignments(
    user_id: str,
    principal: Principal = Depends(
        require_permission(Permission("organization.scope_assignments.list"))
    ),
    scope_service: ScopeAssignmentApplicationService = Depends(
        get_scope_assignment_service
    ),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> ScopeAssignmentsResponse:
    region_ids = await scope_service.list_region_assignments(user_id, uow=uow)
    organization_ids = await scope_service.list_organization_assignments(
        user_id, uow=uow
    )
    return ScopeAssignmentsResponse(
        user_id=user_id,
        region_ids=sorted(region_ids),
        organization_ids=sorted(organization_ids),
    )


@scope_assignments_router.post(
    "/regions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Grant a Regional Manager's region scope assignment",
)
async def grant_region_assignment(
    body: GrantRegionAssignmentRequest,
    principal: Principal = Depends(
        require_permission(Permission("organization.scope_assignments.grant"))
    ),
    scope_service: ScopeAssignmentApplicationService = Depends(
        get_scope_assignment_service
    ),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> None:
    command = GrantRegionAssignmentCommand(
        user_id=body.user_id, region_id=body.region_id, actor=principal
    )
    await scope_service.grant_region_assignment(command, uow=uow)


@scope_assignments_router.post(
    "/regions/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a Regional Manager's region scope assignment",
)
async def revoke_region_assignment(
    body: GrantRegionAssignmentRequest,
    principal: Principal = Depends(
        require_permission(Permission("organization.scope_assignments.revoke"))
    ),
    scope_service: ScopeAssignmentApplicationService = Depends(
        get_scope_assignment_service
    ),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> None:
    command = RevokeRegionAssignmentCommand(
        user_id=body.user_id, region_id=body.region_id, actor=principal
    )
    await scope_service.revoke_region_assignment(command, uow=uow)


@scope_assignments_router.post(
    "/support",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Grant a Support Staff's organization scope assignment",
)
async def grant_support_assignment(
    body: GrantSupportAssignmentRequest,
    principal: Principal = Depends(
        require_permission(Permission("organization.scope_assignments.grant"))
    ),
    scope_service: ScopeAssignmentApplicationService = Depends(
        get_scope_assignment_service
    ),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> None:
    command = GrantSupportAssignmentCommand(
        user_id=body.user_id,
        organization_id=body.organization_id,
        actor=principal,
    )
    await scope_service.grant_support_assignment(command, uow=uow)


@scope_assignments_router.post(
    "/support/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a Support Staff's organization scope assignment",
)
async def revoke_support_assignment(
    body: GrantSupportAssignmentRequest,
    principal: Principal = Depends(
        require_permission(Permission("organization.scope_assignments.revoke"))
    ),
    scope_service: ScopeAssignmentApplicationService = Depends(
        get_scope_assignment_service
    ),
    uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> None:
    command = RevokeSupportAssignmentCommand(
        user_id=body.user_id,
        organization_id=body.organization_id,
        actor=principal,
    )
    await scope_service.revoke_support_assignment(command, uow=uow)
