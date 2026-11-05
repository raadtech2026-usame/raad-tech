"""FastAPI dependency wiring for data_transfer module.

Resolves DI-container-bound DataTransferUnitOfWork, DataTransferApplicationService,
and validates target organization scope for centralized platform operations.
"""

from __future__ import annotations

from fastapi import Depends, Request

from raad.core.di.container import Container
from raad.core.errors.exceptions import NotFoundError
from raad.core.tenancy.principal import Principal
from raad.core.tenancy.scope import TenantRegionScope
from raad.interfaces.http.deps import get_container, get_principal, get_scope
from raad.modules.data_transfer.application.ports import DataTransferUnitOfWork
from raad.modules.data_transfer.application.services import (
    DataTransferApplicationService,
)
from raad.modules.organization.api.deps import get_organization_uow
from raad.modules.organization.application.ports import OrganizationUnitOfWork


def get_data_transfer_uow(
    container: Container = Depends(get_container),
    scope: TenantRegionScope = Depends(get_scope),
) -> DataTransferUnitOfWork:
    uow = container.resolve(DataTransferUnitOfWork)
    uow.scope = scope
    return uow


def get_data_transfer_service(
    container: Container = Depends(get_container),
) -> DataTransferApplicationService:
    return container.resolve(DataTransferApplicationService)


async def resolve_target_organization(
    organization_id: str,
    principal: Principal = Depends(get_principal),
    scope: TenantRegionScope = Depends(get_scope),
    org_uow: OrganizationUnitOfWork = Depends(get_organization_uow),
) -> str:
    """Validates that the target organization exists and is within the caller's authorized scope.

    ADR-0021: Any access attempt outside the principal's authorized scope raises NotFoundError (404)
    rather than 403 Forbidden to eliminate IDOR enumeration vulnerabilities.
    """
    clean_org_id = organization_id.strip()
    if not clean_org_id:
        raise NotFoundError("Organization ID must not be empty.")

    # Scope enforcement at platform administration boundary
    if not scope.allows(clean_org_id):
        raise NotFoundError(f"Organization '{clean_org_id}' not found.")

    # Verify existence in the organization registry
    async with org_uow:
        org = await org_uow.organizations.get_by_id(clean_org_id)
        if org is None:
            raise NotFoundError(f"Organization '{clean_org_id}' not found.")

    return clean_org_id
