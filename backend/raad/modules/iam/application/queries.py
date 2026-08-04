"""IAM application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite read-models). DTOs are
plain dataclasses — the boundary between the domain's aggregates and any future API/infra
layer, so neither ever depends on the other's internal shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from raad.core.pagination import FilterCondition, OffsetPageRequest, SortSpec
from raad.core.security.ip_mask import mask_ip_address
from raad.modules.iam.domain.entities import RefreshToken, User


@dataclass(frozen=True)
class GetUserByIdQuery:
    user_id: str


@dataclass(frozen=True)
class ListSessionsQuery:
    """ADR-0019: `GET /auth/sessions`. `user_id` is always the caller's own
    (`principal.user_id`), never a client-supplied id — self-service only, the same posture
    `ChangePasswordCommand`/`get_me` already establish."""

    user_id: str


@dataclass(frozen=True)
class ListUsersQuery:
    page_request: OffsetPageRequest
    sort: list[SortSpec] = field(default_factory=list)
    filters: list[FilterCondition] = field(default_factory=list)
    search: str | None = None


@dataclass(frozen=True)
class UserDTO:
    id: str
    organization_id: str | None
    role: str
    email: str | None
    phone: str | None
    full_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    mfa_enabled: bool
    last_login_at: datetime | None
    is_password_change_required: bool


@dataclass(frozen=True)
class AuthResultDTO:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    user: UserDTO


@dataclass(frozen=True)
class SessionDTO:
    """ADR-0019: one active (non-revoked, non-expired) `RefreshToken`, shaped for
    `GET /auth/sessions`. `ip_address` is deliberately the **masked** form
    (`core.security.ip_mask.mask_ip_address`) — the ADR's own §5's column list names "masked
    `ip_address`", never the raw value, in this read path."""

    id: str
    device_label: str | None
    ip_address: str | None
    issued_at: datetime
    expires_at: datetime


def refresh_token_to_session_dto(token: RefreshToken) -> SessionDTO:
    """ADR-0019. `str(token.id)` mirrors `user_to_dto`'s identical `str(user.id)` convention."""
    return SessionDTO(
        id=str(token.id),
        device_label=token.device_label,
        ip_address=mask_ip_address(token.ip_address),
        issued_at=token.issued_at,
        expires_at=token.expires_at,
    )


def user_to_dto(user: User) -> UserDTO:
    """Shared mapper — the only place a `User` aggregate is projected into its DTO, used by
    both `UserApplicationService` and `AuthApplicationService` (`services.py`)."""
    return UserDTO(
        id=str(user.id),
        organization_id=(
            str(user.organization_id) if user.organization_id is not None else None
        ),
        role=user.role.value,
        email=str(user.email) if user.email is not None else None,
        phone=str(user.phone) if user.phone is not None else None,
        full_name=user.full_name,
        status=user.status.value,
        created_at=user.created_at,
        updated_at=user.updated_at,
        mfa_enabled=user.mfa_enabled,
        last_login_at=user.last_login_at,
        is_password_change_required=user.is_password_change_required,
    )
