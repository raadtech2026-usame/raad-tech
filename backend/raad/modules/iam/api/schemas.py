"""HTTP request/response DTOs for `iam` (Backend LLD §16; API Contracts §2/§4.1). Pydantic
models are transport-only — the boundary at which JSON becomes/comes-from the application
layer's plain-dataclass commands/DTOs. No business logic lives here; routers do that
translation (`routers.py`), never the schemas themselves.

`role`/`status` are transported as the approved lower-case snake_case strings (Database
Design §4.3, API Contracts §2.2 example: `"role": "org_admin"`), matching
`core.tenancy.principal.Role`'s upper-case values case-folded — the same translation
`modules/iam/infra/mappers.py` already does at the persistence boundary.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    identifier: str = Field(..., description="Email or E.164 phone number.")
    password: str


class PrincipalResponse(BaseModel):
    user_id: str
    role: str
    organization_id: str | None = None
    region_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Resolved via `core.tenancy.ScopeResolver.effective_org_scope` (ADR-0005). Only "
            "ever non-empty for a Regional Manager's assigned regions — every other role "
            "resolves to an empty list, matching that resolver's own documented formula."
        ),
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    principal: PrincipalResponse


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    organization_id: str | None
    role: str
    email: str | None
    phone: str | None
    full_name: str
    status: str
    mfa_enabled: bool
    last_login_at: datetime | None


class CreateUserRequest(BaseModel):
    organization_id: str | None = None
    role: str
    email: str | None = None
    phone: str | None = None
    full_name: str


class UpdateUserRequest(BaseModel):
    """Partial update, limited to the transitions the Application layer actually exposes
    (Phase 5.2's `UserApplicationService` has no generic field-editing use-case) — `status`
    (`"active"`/`"disabled"`, mapped to `activate_user`/`disable_user`) and `mfa_enabled`
    (mapped to `enable_mfa`/`disable_mfa`). At least one must be given. A fuller field-level
    update (`full_name`, `email`, `phone`) needs an Application-layer addition out of scope
    for this HTTP-only phase.
    """

    status: str | None = None
    mfa_enabled: bool | None = None
