"""Application-layer command validators (Backend LLD §4.1's application table: "Contextual
pre-conditions of a use-case"). These check pre-conditions that need repository I/O, which is
exactly why they're an application concern and not a domain one — mirroring
`iam.application.validators`'s identical reasoning (`modules/organization/domain/services.py`
explains why region-name uniqueness isn't a domain service either: domain services are I/O-free
operations over already-loaded entities).

`ensure_region_exists`/`ensure_parent_organization_exists` pre-check the two in-context foreign
keys Database Design §4.2 declares (`organizations.region_id FK→regions.id`,
`organizations.parent_org_id FK→organizations.id`) — both are enforced by the database too
(`.claude/rules/database.md` #3: in-context FKs are DB-enforced), but checking here first
surfaces a `NotFoundError` instead of a raw FK-violation error, the same defense-in-depth
`ensure_email_available`/`ensure_phone_available` already apply to `iam`'s DB-enforced unique
constraints.

Permission/authorization pre-condition checks (the LLD's "actor has permission" example) are
not implemented here yet, for the same reason `iam.application.validators` gives: the RBAC
permission matrix is still pending approval (`core.security.permissions.PermissionEvaluator`,
Phase 4.3).
"""

from __future__ import annotations

from raad.core.errors.exceptions import ConflictError, NotFoundError
from raad.modules.organization.application.ports import OrganizationUnitOfWork
from raad.modules.organization.domain.value_objects import OrganizationId, RegionId


async def ensure_region_name_available(uow: OrganizationUnitOfWork, name: str) -> None:
    existing = await uow.regions.get_by_name(name)
    if existing is not None:
        raise ConflictError(f"A region named {name!r} already exists.")


async def ensure_region_exists(
    uow: OrganizationUnitOfWork, region_id: RegionId
) -> None:
    existing = await uow.regions.get(region_id)
    if existing is None:
        raise NotFoundError(f"Region {region_id} not found.")


async def ensure_parent_organization_exists(
    uow: OrganizationUnitOfWork, parent_org_id: OrganizationId
) -> None:
    existing = await uow.organizations.get(parent_org_id)
    if existing is None:
        raise NotFoundError(f"Organization {parent_org_id} not found.")
