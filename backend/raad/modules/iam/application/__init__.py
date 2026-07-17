"""IAM application layer (Backend LLD §4) — Phase 5.2 scope.

Orchestration only: loads aggregates via repositories bound to `IamUnitOfWork`, invokes
domain behavior, records the resulting `DomainEvent`s, commits, and returns a DTO. No
FastAPI/SQLAlchemy, no infra, no business rules (those live in `modules/iam/domain`). Public
surface of this package.
"""

from raad.modules.iam.application.commands import (
    ActivateUserCommand,
    ChangePasswordCommand,
    DisableMfaCommand,
    DisableUserCommand,
    EnableMfaCommand,
    InviteUserCommand,
    LoginCommand,
    LogoutCommand,
    RefreshAccessTokenCommand,
)
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.queries import (
    AuthResultDTO,
    GetUserByIdQuery,
    UserDTO,
)
from raad.modules.iam.application.services import (
    AuthApplicationService,
    UserApplicationService,
)

__all__ = [
    "ActivateUserCommand",
    "AuthApplicationService",
    "AuthResultDTO",
    "ChangePasswordCommand",
    "DisableMfaCommand",
    "DisableUserCommand",
    "EnableMfaCommand",
    "GetUserByIdQuery",
    "IamUnitOfWork",
    "InviteUserCommand",
    "LoginCommand",
    "LogoutCommand",
    "RefreshAccessTokenCommand",
    "UserApplicationService",
    "UserDTO",
]
