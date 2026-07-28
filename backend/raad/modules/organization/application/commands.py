"""Organization application commands (Backend LLD §4.2 "intent DTOs"). Immutable request
objects describing what the caller wants done, matching `iam.application.commands`'s exact
shape: every command carries the calling `Principal` as `actor` (LLD's own contract-skeleton
style), and identifiers are plain `str` (converted to value objects inside the service), while
`OrgType` is passed as the already-typed domain enum — the same treatment
`InviteUserCommand.role: Role` gives a core-shared enum, since both are "already-parsed by the
caller" rather than a raw wire string this layer would need to validate. **ADR-0016 (RAAD
business model realignment): `billing_model` is removed from every command below** — RAAD bills
Organizations only now, so there is no longer a per-organization billing-model choice to carry.
"""

from __future__ import annotations

from dataclasses import dataclass

from raad.core.tenancy.principal import Principal
from raad.modules.organization.domain.value_objects import OrgType


@dataclass(frozen=True)
class RegisterOrganizationCommand:
    name: str
    org_type: OrgType
    region_id: str
    parent_org_id: str | None
    actor: Principal


@dataclass(frozen=True)
class OnboardOrganizationCommand:
    """ADR-0017: RAAD creates an Organization and its first Org Admin `iam.User` (a
    login-capable account, generated one-time temporary password) as one guided workflow —
    replaces the previously fully-manual, disconnected two-step process (`POST /organizations`
    then a separate, unlinked `POST /users`).

    **Plan selection is still not part of this command.** It was originally deferred pending
    ADR-0016 (Organization-Only Billing), which has since landed — `billing.Subscription` now
    keys on `organization_id` alone, so the shape this command would have been throwaway code
    against no longer applies. Wiring "select a subscription plan" into onboarding remains a
    real, flagged follow-up (not attempted this phase — a new command field plus an
    `OrganizationApplicationService.onboard_organization` orchestration change, outside this
    phase's own scope of removing the parent-billing path), not a silent omission."""

    name: str
    org_type: OrgType
    region_id: str
    parent_org_id: str | None
    admin_full_name: str
    admin_email: str | None
    admin_phone: str | None
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
class UpdateOrganizationGeofenceCommand:
    """ADR-0014. No approved HTTP route exists yet — reachable at the application layer only,
    the same posture `GrantRegionAssignmentCommand`/`GrantSupportAssignmentCommand` already
    establish below."""

    organization_id: str
    latitude: float
    longitude: float
    radius_m: int
    actor: Principal


@dataclass(frozen=True)
class UpdateOrganizationApproachingDistanceCommand:
    """ADR-0014 amendment. No approved HTTP route exists yet — same posture as
    `UpdateOrganizationGeofenceCommand` above."""

    organization_id: str
    approaching_distance_m: int
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


@dataclass(frozen=True)
class GrantRegionAssignmentCommand:
    """Backs `ScopeResolver`'s Regional Manager formula (Database Design §4.6). No approved
    HTTP route exists yet — reachable at the application layer only, same posture as
    `iam.application.commands.GrantRolePermissionCommand`."""

    user_id: str
    region_id: str
    actor: Principal


@dataclass(frozen=True)
class RevokeRegionAssignmentCommand:
    user_id: str
    region_id: str
    actor: Principal


@dataclass(frozen=True)
class GrantSupportAssignmentCommand:
    user_id: str
    organization_id: str
    actor: Principal


@dataclass(frozen=True)
class RevokeSupportAssignmentCommand:
    user_id: str
    organization_id: str
    actor: Principal
