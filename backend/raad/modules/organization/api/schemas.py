"""HTTP request/response DTOs for `organization` (Backend LLD §16; API Contracts §4.1).
Pydantic models are transport-only — the boundary at which JSON becomes/comes-from the
application layer's plain-dataclass commands/DTOs. No business logic lives here; routers do
that translation (`routers.py`), never the schemas themselves. Mirrors
`iam.api.schemas`'s shape exactly.

`org_type`/`billing_model`/`status` are transported as the approved lower-case snake_case
strings (Database Design §4.1/§4.2, e.g. `"billing_model": "organization_pays"`), matching
`organization.domain.value_objects`' enum values one-for-one — no case-folding translation is
needed here (unlike `iam.api.schemas`'s `Role`, whose domain values are upper-case).
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
    billing_model: str
    status: str
    created_at: datetime
    updated_at: datetime


class RegisterOrganizationRequest(BaseModel):
    """ADR-0017: Organization Onboarding is one guided workflow now, not two disconnected
    steps — this request also carries the identity fields needed to provision the
    Organization's first Org Admin login (`admin_email`/`admin_phone`: at least one required,
    `iam.User`'s own invariant)."""

    name: str
    org_type: str
    region_id: str
    billing_model: str
    parent_org_id: str | None = None
    admin_full_name: str
    admin_email: str | None = None
    admin_phone: str | None = None


class OrganizationOnboardedResponse(BaseModel):
    """`POST /organizations`'s actual response shape (ADR-0017) — wraps the usual
    `OrganizationResponse` with the newly-provisioned Org Admin's `user_id` and a generated
    one-time temporary password, surfaced exactly once here for hand-off. Never re-derivable
    afterward via any other endpoint."""

    organization: OrganizationResponse
    admin_user_id: str
    temporary_password: str


class UpdateOrganizationRequest(BaseModel):
    """Partial update, limited to the transition the Application layer actually exposes
    (`OrganizationApplicationService` has `suspend_organization`/`reactivate_organization`/
    `deactivate_organization`, no generic field-editing use-case) — `status`
    (`"active"`/`"suspended"`/`"inactive"`, mapped to the matching command). At least one
    field must be given.

    API Contracts §4.1 also lists `billing_model` as a `PATCH /organizations/{id}` input
    (**CR-1**). That is deliberately **not** included here: `organization.domain.entities.
    Organization`'s own docstring records that `change_billing_model` was deliberately left
    unimplemented, since neither the Database Design nor Phase 2 §18 documents a rule for
    changing it post-registration. Adding it would mean inventing an undocumented domain
    transition rather than implementing an approved one — flagged rather than silently
    built or silently dropped.
    """

    status: str | None = None


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
