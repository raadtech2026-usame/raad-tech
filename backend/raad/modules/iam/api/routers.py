"""HTTP surface of the `iam` module (C1) — Phase 5.4. `auth_router` mounts at `/api/v1/auth`,
`users_router` at `/api/v1/users` (`interfaces/http/api_v1.py`).

Thin controllers only (Backend LLD §16.2): parse the request DTO, call exactly one
application-service method, return the response DTO. No business logic, no repository/
SQLAlchemy access, no aggregate manipulation — every error raised by the application/domain
layers already maps to the standard `ErrorEnvelope` via the global exception handlers
(`core/errors/handlers.py`, registered once in `main.py`); routers never build an error
response themselves.

**`GET /users` (list) — added under the Backend Stabilization phase.** Previously deferred here
("no listing use-case... adding one means touching Domain and Application, both frozen this
phase") because RBAC/scope work was explicitly out of scope at the time; `UserRepository.
list_all` (`domain/repositories.py`) and `UserApplicationService.list_users` now exist.
**Scope-filtered as of ADR-0021** (the tenant-isolation audit's confirmed `regional_manager`/
`support_staff` bypass) — this route, `GET /users/{id}`, `PATCH /users/{id}`, and
`POST /users/{id}/reset-password` all resolve via `api/deps.get_scoped_iam_uow`, not the plain
`get_iam_uow` every other route here still uses; see that dependency's own docstring for exactly
which routes need scoping and which don't.

**Endpoints deliberately not implemented** (see the module's own docstrings for why touching
Domain/Application is out of scope this phase):
- `DELETE /users/{id}` — Database Design §9 keeps "soft delete" (`deleted_at`) and
  "business status" (`user.disable()`, `status=disabled`) explicitly separate concepts; the
  `User` aggregate has no soft-delete behavior, so a correct implementation needs a Domain
  addition out of scope here. Confirmed with the user rather than silently conflating the two.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from raad.core.di.container import Container
from raad.core.errors.exceptions import ValidationError
from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal, Role
from raad.core.tenancy.resolver import ScopeResolver
from raad.interfaces.http.deps import (
    get_container,
    get_current_user,
    get_filter_conditions,
    get_offset_page_request,
    get_search_query,
    get_sort_params,
    require_permission,
)
from raad.interfaces.http.pagination import OffsetPageResponse, to_offset_page_response
from raad.modules.iam.api.deps import (
    get_auth_service,
    get_iam_uow,
    get_permission_service,
    get_scoped_iam_uow,
    get_user_service,
)
from raad.modules.iam.api.schemas import (
    ChangePasswordRequest,
    CreateUserRequest,
    LoginRequest,
    LogoutRequest,
    PasswordResetResponse,
    PrincipalResponse,
    RefreshRequest,
    RolePermissionRequest,
    RolePermissionsResponse,
    TokenResponse,
    UpdateUserRequest,
    UserResponse,
)
from raad.modules.iam.application.commands import (
    ActivateUserCommand,
    ChangePasswordCommand,
    DisableMfaCommand,
    DisableUserCommand,
    EnableMfaCommand,
    GrantRolePermissionCommand,
    InviteUserCommand,
    LoginCommand,
    LogoutCommand,
    RefreshAccessTokenCommand,
    ResetPasswordToTemporaryCommand,
    RevokeRolePermissionCommand,
)
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.queries import (
    AuthResultDTO,
    GetUserByIdQuery,
    ListUsersQuery,
    UserDTO,
)
from raad.modules.iam.application.services import (
    AuthApplicationService,
    PermissionApplicationService,
    UserApplicationService,
)

auth_router = APIRouter()
users_router = APIRouter()
roles_router = APIRouter()


def _parse_role(value: str) -> Role:
    try:
        return Role(value.upper())
    except ValueError as exc:
        raise ValidationError(
            f"Unknown role: {value!r}", details={"field": "role"}
        ) from exc


async def _resolve_region_ids(result: AuthResultDTO, *, container: Container) -> list[str]:
    """RAAD-staff region scope (`core.tenancy.ScopeResolver.effective_org_scope`) is real now
    (ADR-0005, `organization.infra.adapters.OrganizationScopeResolver`) — only a Regional
    Manager's `TenantRegionScope.region_ids` is ever non-empty (every other role resolves to
    `frozenset()`), matching that resolver's own documented formula exactly."""
    resolver = container.resolve(ScopeResolver)
    principal = Principal(
        user_id=result.user.id,
        role=Role(result.user.role),
        org_id=result.user.organization_id,
    )
    scope = await resolver.effective_org_scope(principal)
    return sorted(scope.region_ids)


def _auth_result_to_response(
    result: AuthResultDTO, *, region_ids: list[str]
) -> TokenResponse:
    return TokenResponse(
        access_token=result.access_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
        refresh_token=result.refresh_token,
        principal=PrincipalResponse(
            user_id=result.user.id,
            role=result.user.role.lower(),
            organization_id=result.user.organization_id,
            region_ids=region_ids,
            is_password_change_required=result.user.is_password_change_required,
        ),
    )


def _user_dto_to_response(user: UserDTO) -> UserResponse:
    return UserResponse(
        id=user.id,
        organization_id=user.organization_id,
        role=user.role.lower(),
        email=user.email,
        phone=user.phone,
        full_name=user.full_name,
        status=user.status,
        created_at=user.created_at,
        updated_at=user.updated_at,
        mfa_enabled=user.mfa_enabled,
        last_login_at=user.last_login_at,
        is_password_change_required=user.is_password_change_required,
    )


@auth_router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange credentials for access + refresh tokens",
    description="Public (API Contracts §2.1). `identifier` is an email or E.164 phone number.",
)
async def login(
    request: Request,
    body: LoginRequest,
    auth_service: AuthApplicationService = Depends(get_auth_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
) -> TokenResponse:
    email = body.identifier if "@" in body.identifier else None
    phone = body.identifier if body.identifier.startswith("+") else None
    command = LoginCommand(email=email, phone=phone, plain_password=body.password)
    result = await auth_service.login(command, uow=uow)
    region_ids = await _resolve_region_ids(result, container=get_container(request))
    return _auth_result_to_response(result, region_ids=region_ids)


@auth_router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate the access token",
    description=(
        "Auth: refresh token (API Contracts §2.1). Revokes the presented refresh token and "
        "issues a brand new access/refresh pair (rotation)."
    ),
)
async def refresh(
    request: Request,
    body: RefreshRequest,
    auth_service: AuthApplicationService = Depends(get_auth_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
) -> TokenResponse:
    command = RefreshAccessTokenCommand(refresh_token=body.refresh_token)
    result = await auth_service.refresh(command, uow=uow)
    region_ids = await _resolve_region_ids(result, container=get_container(request))
    return _auth_result_to_response(result, region_ids=region_ids)


@auth_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
    description=(
        "Auth: bearer (API Contracts §2.1). Idempotent — logging out an already-invalid or "
        "unknown token is a no-op, not an error."
    ),
)
async def logout(
    body: LogoutRequest,
    principal: Principal = Depends(get_current_user),
    auth_service: AuthApplicationService = Depends(get_auth_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
) -> None:
    command = LogoutCommand(refresh_token=body.refresh_token)
    await auth_service.logout(command, uow=uow)


@auth_router.post(
    "/change-password",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Change the current principal's own password",
    description=(
        "Auth: bearer (new — ADR-0017). Self-service only, identified by the bearer token, "
        "never a body-supplied `user_id`. Clears `is_password_change_required` — this is how "
        "a Org Admin/Parent/Driver who received a one-time temporary password satisfies the "
        "forced-change gate before doing anything else."
    ),
)
async def change_password(
    body: ChangePasswordRequest,
    principal: Principal = Depends(get_current_user),
    user_service: UserApplicationService = Depends(get_user_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
) -> UserResponse:
    command = ChangePasswordCommand(
        user_id=principal.user_id,
        new_plain_password=body.new_password,
        actor=principal,
    )
    user = await user_service.change_password(command, uow=uow)
    return _user_dto_to_response(user)


@auth_router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Current principal's profile",
    description="Auth: bearer (API Contracts §2.1).",
)
async def get_me(
    principal: Principal = Depends(get_current_user),
    user_service: UserApplicationService = Depends(get_user_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
) -> UserResponse:
    user = await user_service.get_user_by_id(
        GetUserByIdQuery(user_id=principal.user_id), uow=uow
    )
    return _user_dto_to_response(user)


@users_router.get(
    "",
    response_model=OffsetPageResponse[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="List users",
    description=(
        "In-scope admin (API Contracts §4.1). Scope-filtered (ADR-0021) by the caller's "
        "resolved tenant/region scope. Paginated/filterable/sortable per §7/§8."
    ),
)
async def list_users(
    principal: Principal = Depends(require_permission(Permission("iam.users.read"))),
    user_service: UserApplicationService = Depends(get_user_service),
    uow: IamUnitOfWork = Depends(get_scoped_iam_uow),
    page_request: OffsetPageRequest = Depends(get_offset_page_request),
    sort: list[SortSpec] = Depends(get_sort_params),
    filters: list[FilterCondition] = Depends(get_filter_conditions),
    search: str | None = Depends(get_search_query),
) -> OffsetPageResponse[UserResponse]:
    page = await user_service.list_users(
        ListUsersQuery(
            page_request=page_request, sort=sort, filters=filters, search=search
        ),
        uow=uow,
    )
    return to_offset_page_response(page, _user_dto_to_response)


@users_router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a new user",
    description=(
        "Role-restricted creation, in-scope admin (API Contracts §4.1). Authorization uses "
        "`require_permission` (`core.security.PermissionEvaluator`), resolving against the "
        "real seeded RBAC permission matrix (ADR-0004)."
    ),
)
async def create_user(
    body: CreateUserRequest,
    principal: Principal = Depends(require_permission(Permission("iam.users.create"))),
    user_service: UserApplicationService = Depends(get_user_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
) -> UserResponse:
    command = InviteUserCommand(
        organization_id=body.organization_id,
        role=_parse_role(body.role),
        email=body.email,
        phone=body.phone,
        full_name=body.full_name,
        actor=principal,
    )
    user = await user_service.invite_user(command, uow=uow)
    return _user_dto_to_response(user)


@users_router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a user by id",
    description=(
        "In-scope admin (API Contracts §4.1). Authorization resolves against the real "
        "seeded RBAC permission matrix — see `create_user`'s note."
    ),
)
async def get_user(
    user_id: str,
    principal: Principal = Depends(require_permission(Permission("iam.users.read"))),
    user_service: UserApplicationService = Depends(get_user_service),
    uow: IamUnitOfWork = Depends(get_scoped_iam_uow),
) -> UserResponse:
    user = await user_service.get_user_by_id(GetUserByIdQuery(user_id=user_id), uow=uow)
    return _user_dto_to_response(user)


@users_router.patch(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a user's status or MFA flag",
    description=(
        "In-scope admin (API Contracts §4.1). Limited to the transitions the Application "
        "layer exposes — see `UpdateUserRequest`'s docstring. Authorization resolves against "
        "the real seeded RBAC permission matrix — see `create_user`'s note. Composing both "
        "`status` and `mfa_enabled` in one request performs two separate commits (not atomic), "
        "since each reuses an existing single-purpose Application-layer method."
    ),
)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    principal: Principal = Depends(require_permission(Permission("iam.users.update"))),
    user_service: UserApplicationService = Depends(get_user_service),
    uow: IamUnitOfWork = Depends(get_scoped_iam_uow),
) -> UserResponse:
    if body.status is None and body.mfa_enabled is None:
        raise ValidationError(
            "At least one of 'status' or 'mfa_enabled' must be provided.",
            details={"fields": ["status", "mfa_enabled"]},
        )

    user: UserDTO | None = None

    if body.status is not None:
        if body.status == "active":
            user = await user_service.activate_user(
                ActivateUserCommand(user_id=user_id, actor=principal), uow=uow
            )
        elif body.status == "disabled":
            user = await user_service.disable_user(
                DisableUserCommand(user_id=user_id, actor=principal), uow=uow
            )
        else:
            raise ValidationError(
                f"Unsupported status: {body.status!r}", details={"field": "status"}
            )

    if body.mfa_enabled is not None:
        if body.mfa_enabled:
            user = await user_service.enable_mfa(
                EnableMfaCommand(user_id=user_id, actor=principal), uow=uow
            )
        else:
            user = await user_service.disable_mfa(
                DisableMfaCommand(user_id=user_id, actor=principal), uow=uow
            )

    if user is None:
        # Guaranteed not to happen by the "at least one field" guard above — an explicit
        # raise rather than `assert`, since `assert` is stripped under `python -O`/
        # `PYTHONOPTIMIZE` and this invariant must hold regardless of how the interpreter is
        # invoked.
        raise RuntimeError(
            "update_user: no field was processed despite the guard above."
        )
    return _user_dto_to_response(user)


@users_router.post(
    "/{user_id}/reset-password",
    response_model=PasswordResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Administrator-initiated password reset",
    description=(
        "ADR-0017 Amendment. In-scope admin only (`iam.users.reset_password`) — not "
        "self-service (use `POST /auth/change-password` for that). Generates a brand new "
        "one-time temporary password for `{user_id}`, invalidating whatever password they had "
        "before and revoking every refresh token already issued to them. The new password is "
        "returned in this response exactly once and is never retrievable again afterward."
    ),
)
async def reset_user_password(
    user_id: str,
    principal: Principal = Depends(
        require_permission(Permission("iam.users.reset_password"))
    ),
    user_service: UserApplicationService = Depends(get_user_service),
    uow: IamUnitOfWork = Depends(get_scoped_iam_uow),
) -> PasswordResetResponse:
    command = ResetPasswordToTemporaryCommand(user_id=user_id, actor=principal)
    user, temporary_password = await user_service.reset_password_to_temporary(
        command, uow=uow
    )
    return PasswordResetResponse(
        user=_user_dto_to_response(user), temporary_password=temporary_password
    )


# --- Role/permission matrix management (Priority 1 Item 6, PROJECT_STATUS.md) -----------------
#
# `PermissionApplicationService` (`application/services.py`) has existed, reachable at the
# application layer only, since the Backend Stabilization phase — its own docstring named the
# gap this closes: "RAAD can't onboard its own staff without hand-editing the DB". No documented
# route exists for this in API Contracts (that document has no `/roles` or `/admin/roles`
# surface at all) — built anyway on Database Design §4.4's own unambiguous requirement
# ("editable by Founder... without code change"), the same "use-case exists, no approved
# endpoint yet, built on the schema authority instead" posture already established for
# `/drivers` and `Route.remove_stop`/`Trip.interrupt`. Founder-only in the seeded matrix
# (migration `<this item's own revision>`) — the most sensitive action in the whole system,
# since it can grant any permission to any role, including itself.


@roles_router.get(
    "/{role}/permissions",
    response_model=RolePermissionsResponse,
    summary="List a role's granted permissions",
)
async def list_role_permissions(
    role: str,
    principal: Principal = Depends(
        require_permission(Permission("iam.role_permissions.list"))
    ),
    permission_service: PermissionApplicationService = Depends(get_permission_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
) -> RolePermissionsResponse:
    parsed_role = _parse_role(role)
    permissions = await permission_service.list_permissions_for_role(
        parsed_role, uow=uow
    )
    return RolePermissionsResponse(
        role=parsed_role.value, permissions=sorted(permissions)
    )


@roles_router.post(
    "/{role}/permissions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Grant a permission to a role",
)
async def grant_role_permission(
    role: str,
    body: RolePermissionRequest,
    principal: Principal = Depends(
        require_permission(Permission("iam.role_permissions.grant"))
    ),
    permission_service: PermissionApplicationService = Depends(get_permission_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
) -> None:
    command = GrantRolePermissionCommand(
        role=_parse_role(role), permission=body.permission, actor=principal
    )
    await permission_service.grant_role_permission(command, uow=uow)


@roles_router.post(
    "/{role}/permissions/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a permission from a role",
)
async def revoke_role_permission(
    role: str,
    body: RolePermissionRequest,
    principal: Principal = Depends(
        require_permission(Permission("iam.role_permissions.revoke"))
    ),
    permission_service: PermissionApplicationService = Depends(get_permission_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
) -> None:
    command = RevokeRolePermissionCommand(
        role=_parse_role(role), permission=body.permission, actor=principal
    )
    await permission_service.revoke_role_permission(command, uow=uow)
