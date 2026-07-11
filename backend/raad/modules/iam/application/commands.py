"""IAM application commands (Backend LLD §4.2 "intent DTOs"). Immutable request objects
describing what the caller wants done. Admin/self-service commands carry the calling
`Principal` as `actor`, matching the LLD's own contract-skeleton shape exactly (`Command
StartTrip { trip_id, driver_id, actor: Principal }`). Login/refresh/logout are
credential/token-based instead — there's no authenticated actor yet at that point (that's the
point of `LoginCommand`), and refresh/logout are identified purely by the presented token.
"""

from __future__ import annotations

from dataclasses import dataclass

from raad.core.tenancy.principal import Principal, Role


@dataclass(frozen=True)
class InviteUserCommand:
    organization_id: str | None
    role: Role
    email: str | None
    phone: str | None
    full_name: str
    actor: Principal


@dataclass(frozen=True)
class ActivateUserCommand:
    user_id: str
    actor: Principal


@dataclass(frozen=True)
class DisableUserCommand:
    user_id: str
    actor: Principal


@dataclass(frozen=True)
class ChangePasswordCommand:
    user_id: str
    new_plain_password: str
    actor: Principal


@dataclass(frozen=True)
class EnableMfaCommand:
    user_id: str
    actor: Principal


@dataclass(frozen=True)
class DisableMfaCommand:
    user_id: str
    actor: Principal


@dataclass(frozen=True)
class LoginCommand:
    email: str | None
    phone: str | None
    plain_password: str


@dataclass(frozen=True)
class RefreshAccessTokenCommand:
    refresh_token: str


@dataclass(frozen=True)
class LogoutCommand:
    refresh_token: str
