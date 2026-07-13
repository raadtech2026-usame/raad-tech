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

from pydantic import BaseModel


class OrganizationResponse(BaseModel):
    id: str
    name: str
    org_type: str
    parent_org_id: str | None
    region_id: str
    billing_model: str
    status: str


class RegisterOrganizationRequest(BaseModel):
    name: str
    org_type: str
    region_id: str
    billing_model: str
    parent_org_id: str | None = None


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


class CreateRegionRequest(BaseModel):
    name: str
    geographic_scope: str | None = None


class UpdateRegionRequest(BaseModel):
    """Partial update, limited to the transition the Application layer actually exposes
    (`RegionApplicationService` has `activate_region`/`deactivate_region`) — `status`
    (`"active"`/`"inactive"`, mapped to the matching command). At least one field must be
    given."""

    status: str | None = None
