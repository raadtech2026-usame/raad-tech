"""HTTP request/response DTOs for `fleet_device` (Backend LLD §16; API Contracts §4.2).
Pydantic models are transport-only — the boundary at which JSON becomes/comes-from the
application layer's plain-dataclass commands/DTOs. No business logic lives here; routers do
that translation (`routers.py`), never the schemas themselves. Mirrors
`iam`/`organization.api.schemas`'s shape exactly.

`status`/`lifecycle_state`/`position` are transported as the approved lower-case snake_case
strings (Database Design §5), matching `fleet_device.domain.value_objects`' enum values
one-for-one — no case-folding translation is needed.

`organization_id` appears in the register requests following `iam.CreateUserRequest`'s
precedent; constraining an Org Admin to their own organization is the pending tenant/scope
authorization layer's job (`require_permission` + `effective_org_scope`), not a schema rule.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

# --- Vehicle ------------------------------------------------------------------------------


class VehicleResponse(BaseModel):
    id: str
    organization_id: str
    plate_no: str
    label: str | None
    capacity: int | None
    status: str


class RegisterVehicleRequest(BaseModel):
    organization_id: str
    plate_no: str
    label: str | None = None
    capacity: int | None = None


class UpdateVehicleRequest(BaseModel):
    """Partial update, limited to the transitions the Application layer actually exposes
    (`VehicleApplicationService` has `activate_vehicle`/`deactivate_vehicle`/
    `mark_vehicle_under_maintenance`, no generic field-editing use-case) — `status`
    (`"active"`/`"inactive"`/`"maintenance"`, mapped to the matching command). At least one
    field must be given."""

    status: str | None = None


# --- Device -------------------------------------------------------------------------------


class CameraResponse(BaseModel):
    id: str
    channel_no: int
    position: str
    label: str | None


class DeviceResponse(BaseModel):
    id: str
    organization_id: str
    terminal_id: str
    model: str | None
    vendor: str | None
    sim_msisdn: str | None
    lifecycle_state: str
    last_seen_at: datetime | None
    cameras: list[CameraResponse]


class RegisterDeviceRequest(BaseModel):
    organization_id: str
    terminal_id: str
    model: str | None = None
    vendor: str | None = None
    sim_msisdn: str | None = None


class UpdateDeviceRequest(BaseModel):
    """Partial update, limited to the lifecycle transitions the Application layer exposes
    via PATCH — `lifecycle_state` ∈ `"activated"` (Suspended→Activated, i.e. reactivate),
    `"suspended"`, `"retired"`. `Registered→Activated` has its own approved behavioral route
    (`POST /devices/{id}/activate`, API Contracts §4.2), and `"assigned"` is never set
    directly — only via the assignment routes. At least one field must be given."""

    lifecycle_state: str | None = None


# --- Device ↔ Vehicle assignment ----------------------------------------------------------


class AssignDeviceRequest(BaseModel):
    """API Contracts §4.2: `POST /devices/{id}/assign` — body `{vehicle_id}`."""

    vehicle_id: str


class ReassignDeviceRequest(BaseModel):
    """API Contracts §4.2: `POST /devices/{id}/reassign` — closes prior, opens new
    (Phase 2 §19)."""

    vehicle_id: str


class DeviceAssignmentResponse(BaseModel):
    id: str
    organization_id: str
    device_id: str
    vehicle_id: str
    assigned_by: str | None
    assigned_at: datetime
    unassigned_at: datetime | None
    is_active: bool
