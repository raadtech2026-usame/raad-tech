"""HTTP request/response DTOs for `organization` (Backend LLD §16; API Contracts §4.1).
Pydantic models are transport-only — the boundary at which JSON becomes/comes-from the
application layer's plain-dataclass commands/DTOs. No business logic lives here; routers do
that translation (`routers.py`), never the schemas themselves. Mirrors
`iam.api.schemas`'s shape exactly.

`org_type`/`status` are transported as the approved lower-case snake_case strings (Database
Design §4.1/§4.2), matching `organization.domain.value_objects`' enum values one-for-one — no
case-folding translation is needed here (unlike `iam.api.schemas`'s `Role`, whose domain values
are upper-case). **ADR-0016 (RAAD business model realignment) removed `billing_model` from
every schema below** — RAAD bills Organizations only now.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OrganizationResponse(BaseModel):
    id: str
    name: str
    org_type: str
    parent_org_id: str | None
    region_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    trial_started_at: datetime | None = None
    trial_ends_at: datetime | None = None
    #: Derived (`Organization.trial_state()`), never a stored column — see that method's
    #: docstring. `"not_started" | "trialing" | "expired"`.
    trial_state: str = "not_started"


class RegisterOrganizationRequest(BaseModel):
    """ADR-0017: Organization Onboarding is one guided workflow now, not two disconnected
    steps — this request also carries the identity fields needed to provision the
    Organization's first Org Admin login (`admin_email`/`admin_phone`: at least one required,
    `iam.User`'s own invariant).

    **ADR-0040 §5 adds `plan_id`.** Supplying it opens the organization's subscription and
    issues its first invoice in the same workflow, with period dates computed by `billing` from
    the plan's own cycle. Optional, so the pre-ADR-0040 onboarding contract still works
    unchanged.

    **`trial_enabled`/`trial_duration_days`** start the organization on a time-boxed trial
    instead of (never alongside — the application layer rejects both) selecting a plan. A trial
    defers subscription/plan selection entirely; see `organization.domain.entities.Organization.
    start_trial` for the mechanism."""

    name: str
    org_type: str
    region_id: str
    parent_org_id: str | None = None
    admin_full_name: str
    admin_email: str | None = None
    admin_phone: str | None = None
    plan_id: str | None = None
    trial_enabled: bool = False
    trial_duration_days: int | None = None


class OrganizationOnboardedResponse(BaseModel):
    """`POST /organizations`'s actual response shape (ADR-0017) — wraps the usual
    `OrganizationResponse` with the newly-provisioned Org Admin's `user_id` and a generated
    one-time temporary password, surfaced exactly once here for hand-off. Never re-derivable
    afterward via any other endpoint."""

    organization: OrganizationResponse
    admin_user_id: str
    temporary_password: str


class UpdateOrganizationRequest(BaseModel):
    """Partial update, limited to the transitions the Application layer actually exposes:
    `status` (`"active"`/`"suspended"`/`"inactive"`, mapped to `suspend_organization`/
    `reactivate_organization`/`deactivate_organization`) and, as of the Organization Management
    phase, `name` (mapped to `rename_organization` — see `Organization.rename`'s own docstring
    for why this is the one identity field with real backend support; `region_id`/`org_type`/
    `parent_org_id` remain deliberately constructor-set-only). At least one field must be given;
    both may be given in the same request.

    API Contracts §4.1 also lists `billing_model` as a `PATCH /organizations/{id}` input
    (**CR-1**). Never wired here even before ADR-0016 — `organization.domain.entities.
    Organization`'s own docstring recorded that `change_billing_model` was deliberately left
    unimplemented, since neither the Database Design nor Phase 2 §18 documented a rule for
    changing it post-registration. ADR-0016 (RAAD business model realignment) has since removed
    `billing_model` from the aggregate entirely — there is nothing left to change, so this is no
    longer even a deferred field, just a historical API-Contracts-vs-implementation gap.
    """

    status: str | None = None
    name: str | None = None


class RegionResponse(BaseModel):
    id: str
    name: str
    geographic_scope: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class CreateRegionRequest(BaseModel):
    name: str
    geographic_scope: str | None = None


class UpdateRegionRequest(BaseModel):
    """Partial update, limited to the transition the Application layer actually exposes
    (`RegionApplicationService` has `activate_region`/`deactivate_region`) — `status`
    (`"active"`/`"inactive"`, mapped to the matching command). At least one field must be
    given."""

    status: str | None = None


class GrantRegionAssignmentRequest(BaseModel):
    """Priority 1 Item 6 (`PROJECT_STATUS.md`, RBAC grant/revoke route). Backs a Regional
    Manager's `ScopeResolver` formula (Database Design §4.6)."""

    user_id: str
    region_id: str


class GrantSupportAssignmentRequest(BaseModel):
    """Same item — backs a Support Staff's `ScopeResolver` formula."""

    user_id: str
    organization_id: str


class ScopeAssignmentsResponse(BaseModel):
    user_id: str
    region_ids: list[str]
    organization_ids: list[str]
