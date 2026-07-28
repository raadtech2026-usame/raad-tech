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
class OnboardOrganizationCommand:
    """ADR-0017: RAAD creates an Organization and its first Org Admin `iam.User` (a
    login-capable account, generated one-time temporary password) as one guided workflow —
    replaces the previously fully-manual, disconnected two-step process (`POST /organizations`
    then a separate, unlinked `POST /users`).

    **Plan selection is deliberately not part of this command yet** — `services.py`'s
    `OrganizationApplicationService.onboard_organization` docstring records why: wiring "select
    a subscription plan" here would mean opening a
    `billing.Subscription` against that module's *current* dual-mode shape
    (`subscriber_type`/`subscriber_id`), which ADR-0016 (Organization-Only Billing, a separate,
    already-accepted, not-yet-implemented milestone) is about to simplify. Sequenced to land
    once ADR-0016 lands, avoiding throwaway code against a shape already scheduled to change —
    flagged here rather than silently omitted."""

    name: str
    org_type: OrgType
    region_id: str
    billing_model: BillingModel
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
