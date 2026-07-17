"""HTTP request/response DTOs for `transport_ops` (Backend LLD §16; API Contracts §4.3).
Pydantic models are transport-only — the boundary at which JSON becomes/comes-from the
application layer's plain-dataclass commands/DTOs. No business logic lives here; routers do
that translation (`routers.py`), never the schemas themselves. Mirrors
`organization.api.schemas`'s shape exactly.

`status` is transported as the approved lower-case snake_case string (Database Design §6.2:
`active`/`disabled`/`graduated`/`transferred`), matching `transport_ops.domain.value_objects.
StudentStatus`'s enum values one-for-one — no case-folding translation needed here (unlike
`iam.api.schemas`'s `Role`).

Only `StudentSummaryResponse` omits `organization_id`/`external_ref`, mirroring
`StudentSummaryDTO`'s own lighter shape (`application/queries.py`) for the list endpoint.
"""

from __future__ import annotations

from pydantic import BaseModel


class StudentResponse(BaseModel):
    id: str
    organization_id: str
    full_name: str
    external_ref: str | None
    status: str


class StudentSummaryResponse(BaseModel):
    id: str
    full_name: str
    status: str


class EnrollStudentRequest(BaseModel):
    organization_id: str
    full_name: str
    external_ref: str | None = None


class UpdateStudentRequest(BaseModel):
    """Uniform-CRUD `PATCH /students/{id}` (API Contracts §4 preamble). Limited to the field
    edit the Application layer actually exposes (`StudentApplicationService.update_student` ->
    `Student.update_details`) — `full_name`/`external_ref`. **Not** `status`: status
    transitions are their own approved, behavioral route (`POST /students/{id}/status`, API
    Contracts §4.3 line 123, with its own CR-1 consequence) — the same separation
    `fleet_device.api.routers` draws between its uniform `PATCH /devices/{id}` and its
    behavioral `POST /devices/{id}/activate`, rather than `iam.api.schemas.UpdateUserRequest`'s
    bundled-fields shape, since Student's status route is independently documented with its
    own role/notes row, unlike `iam`'s status field.

    At least one field must be given."""

    full_name: str | None = None
    external_ref: str | None = None


class UpdateStudentStatusRequest(BaseModel):
    """`POST /students/{id}/status` (API Contracts §4.3 line 123 verbatim: 'body `{status}`
    -> disable/graduate/transfer -> emits CR-1 revocation'). `status` accepts any of
    `StudentStatus`'s four values (`active`/`disabled`/`graduated`/`transferred`) — the
    documented prose names only the three revoking transitions as the notable/CR-1-relevant
    ones, but the route itself is the single generic status-transition endpoint (the same
    "one PATCH/POST dispatches by status string" shape `organization`/`fleet_device` already
    use for their own multi-value status fields), and `StudentApplicationService.
    activate_student` is an equally-approved Phase 10.2 use-case with no other route to reach
    it from. Treating `active` as reachable here too is an interpretation, not a silent
    assumption — flagged in `routers.py`."""

    status: str
