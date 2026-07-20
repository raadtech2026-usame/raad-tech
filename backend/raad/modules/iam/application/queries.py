"""IAM application queries and DTOs (Backend LLD §4.2/§7.1 CQRS-lite read-models). DTOs are
plain dataclasses — the boundary between the domain's aggregates and any future API/infra
layer, so neither ever depends on the other's internal shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from raad.modules.iam.domain.entities import User


@dataclass(frozen=True)
class GetUserByIdQuery:
    user_id: str


@dataclass(frozen=True)
class ListUsersQuery:
    pass


@dataclass(frozen=True)
class UserDTO:
    id: str
    organization_id: str | None
    role: str
    email: str | None
    phone: str | None
    full_name: str
    status: str
    mfa_enabled: bool
    last_login_at: datetime | None


@dataclass(frozen=True)
class AuthResultDTO:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    user: UserDTO


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
        mfa_enabled=user.mfa_enabled,
        last_login_at=user.last_login_at,
    )
