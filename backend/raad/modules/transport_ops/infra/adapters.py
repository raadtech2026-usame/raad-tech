"""External adapters for `transport_ops` — concrete implementations of this module's own
outbound ports that need another module's data (Backend LLD §6.2/§6.3 Anti-Corruption Layer).

**`IamUserProvisioningAdapter`** is the concrete `application.ports.UserProvisioningPort`
(ADR-0003, accepted). It calls `iam`'s own public application-service surface
(`UserApplicationService.create_user_with_temporary_password`) — never `iam`'s repository or ORM
layer — exactly the same dependency-inversion pattern `iam.infra.adapters.
IamPermissionEvaluator` already establishes for the reverse direction (`core` depending on
`iam`). Takes a `uow_factory` rather than a single `IamUnitOfWork` instance so every call gets
its own fresh session, mirroring that same adapter's `uow_factory` shape exactly.
"""

from __future__ import annotations

from typing import Callable

from raad.core.tenancy.principal import Principal, Role
from raad.modules.iam.application.commands import CreateUserWithTemporaryPasswordCommand
from raad.modules.iam.application.ports import IamUnitOfWork
from raad.modules.iam.application.services import UserApplicationService
from raad.modules.transport_ops.application.ports import UserProvisioningPort


class IamUserProvisioningAdapter(UserProvisioningPort):
    def __init__(
        self,
        *,
        user_service: UserApplicationService,
        uow_factory: Callable[[], IamUnitOfWork],
    ) -> None:
        self._user_service = user_service
        self._uow_factory = uow_factory

    async def create_user_with_temporary_password(
        self,
        *,
        organization_id: str,
        role: Role,
        email: str | None,
        phone: str | None,
        full_name: str,
        actor: Principal,
    ) -> tuple[str, str]:
        uow = self._uow_factory()
        command = CreateUserWithTemporaryPasswordCommand(
            organization_id=organization_id,
            role=role,
            email=email,
            phone=phone,
            full_name=full_name,
            actor=actor,
        )
        user_dto, temporary_password = await self._user_service.create_user_with_temporary_password(
            command, uow=uow
        )
        return user_dto.id, temporary_password
