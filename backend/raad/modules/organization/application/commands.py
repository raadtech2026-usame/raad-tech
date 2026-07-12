"""Organization application commands (Backend LLD §4.2 "intent DTOs"). Immutable request
objects describing what the caller wants done, matching `iam.application.commands`'s exact
shape: every command carries the calling `Principal` as `actor` (LLD's own contract-skeleton
style), and identifiers are plain `str` (converted to value objects inside the service), while
`OrgType`/`BillingModel` are passed as the already-typed domain enums — the same treatment
`InviteUserCommand.role: Role` gives a core-shared enum, since both are "already-parsed by the
caller" rather than raw wire strings this layer would need to validate.
"""

from __future__ import annotations

from dataclasses import dataclass

from raad.core.tenancy.principal import Principal
from raad.modules.organization.domain.value_objects import BillingModel, OrgType


@dataclass(frozen=True)
class RegisterOrganizationCommand:
    name: str
    org_type: OrgType
    region_id: str
    billing_model: BillingModel
    parent_org_id: str | None
    actor: Principal


@dataclass(frozen=True)
class SuspendOrganizationCommand:
    organization_id: str
    actor: Principal


@dataclass(frozen=True)
class ReactivateOrganizationCommand:
    organization_id: str
    actor: Principal


@dataclass(frozen=True)
class DeactivateOrganizationCommand:
    organization_id: str
    actor: Principal


@dataclass(frozen=True)
class CreateRegionCommand:
    name: str
    geographic_scope: str | None
    actor: Principal


@dataclass(frozen=True)
class ActivateRegionCommand:
    region_id: str
    actor: Principal


@dataclass(frozen=True)
class DeactivateRegionCommand:
    region_id: str
    actor: Principal
