"""HTTP surface of the `iam` module (C1) — Phase 5.4. `auth_router` mounts at `/api/v1/auth`,
`users_router` at `/api/v1/users` (`interfaces/http/api_v1.py`).

Thin controllers only (Backend LLD §16.2): parse the request DTO, call exactly one
application-service method, return the response DTO. No business logic, no repository/
SQLAlchemy access, no aggregate manipulation — every error raised by the application/domain
layers already maps to the standard `ErrorEnvelope` via the global exception handlers
(`core/errors/handlers.py`, registered once in `main.py`); routers never build an error
response themselves.

**Endpoints deliberately not implemented** (see the module's own docstrings for why touching
Domain/Application is out of scope this phase):
- `GET /users` (list) — `UserApplicationService` has no listing use-case, and
  `UserRepository`/`RefreshTokenRepository` (Phase 5.1) have no `list()` method either; adding
  one means touching Domain and Application, both frozen this phase.
- `DELETE /users/{id}` — Database Design §9 keeps "soft delete" (`deleted_at`) and
  "business status" (`user.disable()`, `status=disabled`) explicitly separate concepts; the
  `User` aggregate has no soft-delete behavior, so a correct implementation needs a Domain
  addition out of scope here. Confirmed with the user rather than silently conflating the two.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from raad.core.errors.exceptions import ValidationError
from raad.core.security.permissions import Permission
from raad.core.tenancy.principal import Principal, Role
from raad.interfaces.http.deps import get_current_user, require_permission
from raad.modules.iam.api.deps import get_auth_service, get_iam_uow, get_user_service
from raad.modules.iam.api.schemas import (
    CreateUserRequest,
    LoginRequest,
    LogoutRequest,
    PrincipalResponse,
    RefreshRequest,
    TokenResponse,
    UpdateUserRequest,
    UserResponse,
)
from raad.modules.iam.application.commands import (
    ActivateUserCommand,
    DisableMfaCommand,
    DisableUserCommand,
    EnableMfaCommand,
    InviteUserCommand,
    LoginCommand,
    LogoutCommand,
    RefreshAccessTokenCommand,
)
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.queries import AuthResultDTO, GetUserByIdQuery, UserDTO
from raad.modules.iam.application.services import (
    AuthApplicationService,
    UserApplicationService,
)

auth_router = APIRouter()
users_router = APIRouter()


def _parse_role(value: str) -> Role:
    try:
        return Role(value.upper())
    except ValueError as exc:
        raise ValidationError(
            f"Unknown role: {value!r}", details={"field": "role"}
        ) from exc


def _auth_result_to_response(result: AuthResultDTO) -> TokenResponse:
    return TokenResponse(
        access_token=result.access_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
        refresh_token=result.refresh_token,
        principal=PrincipalResponse(
            user_id=result.user.id,
            role=result.user.role.lower(),
            organization_id=result.user.organization_id,
            region_ids=[],
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
        mfa_enabled=user.mfa_enabled,
        last_login_at=user.last_login_at,
    )


@auth_router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange credentials for access + refresh tokens",
    description="Public (API Contracts §2.1). `identifier` is an email or E.164 phone number.",
)
async def login(
    body: LoginRequest,
    auth_service: AuthApplicationService = Depends(get_auth_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
) -> TokenResponse:
    email = body.identifier if "@" in body.identifier else None
    phone = body.identifier if body.identifier.startswith("+") else None
    command = LoginCommand(email=email, phone=phone, plain_password=body.password)
    result = await auth_service.login(command, uow=uow)
    return _auth_result_to_response(result)


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
    body: RefreshRequest,
    auth_service: AuthApplicationService = Depends(get_auth_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
) -> TokenResponse:
    command = RefreshAccessTokenCommand(refresh_token=body.refresh_token)
    result = await auth_service.refresh(command, uow=uow)
    return _auth_result_to_response(result)


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


@users_router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a new user",
    description=(
        "Role-restricted creation, in-scope admin (API Contracts §4.1). Authorization uses "
        "`require_permission` (`core.security.PermissionEvaluator`) — pending the approved "
        "RBAC permission matrix, so this currently raises `NotImplementedError` (500) rather "
        "than a guessed matrix."
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
        "In-scope admin (API Contracts §4.1). Pending the approved RBAC permission matrix "
        "— see `create_user`'s note."
    ),
)
async def get_user(
    user_id: str,
    principal: Principal = Depends(require_permission(Permission("iam.users.read"))),
    user_service: UserApplicationService = Depends(get_user_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
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
        "layer exposes — see `UpdateUserRequest`'s docstring. Pending the approved RBAC "
        "permission matrix — see `create_user`'s note. Composing both `status` and "
        "`mfa_enabled` in one request performs two separate commits (not atomic), since each "
        "reuses an existing single-purpose Application-layer method."
    ),
)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    principal: Principal = Depends(require_permission(Permission("iam.users.update"))),
    user_service: UserApplicationService = Depends(get_user_service),
    uow: IamUnitOfWork = Depends(get_iam_uow),
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

    assert user is not None  # guaranteed by the "at least one field" guard above
    return _user_dto_to_response(user)
