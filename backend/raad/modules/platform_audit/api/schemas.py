"""HTTP request/response DTOs for `platform_audit` (Backend LLD §16; API Contracts §4.8).
Pydantic models are transport-only — no business logic here. Mirrors `billing.api.schemas`'s
shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEntryResponse(BaseModel):
    id: str
    organization_id: str | None
    actor_user_id: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    metadata: dict[str, Any] | None
    ip: str | None
    correlation_id: str | None
    created_at: datetime


class SystemSettingResponse(BaseModel):
    key: str
    value: dict[str, Any]
    scope: str


class SetSystemSettingRequest(BaseModel):
    """`PATCH /admin/settings` body — see `application/commands.py`'s module docstring for why
    this shape is a flagged, minimal placeholder, not a documented request contract."""

    key: str
    value: dict[str, Any]
    scope: str


class OrganizationStatsResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    created_today: int


class VehicleStatsResponse(BaseModel):
    total: int


class DeviceStatsResponse(BaseModel):
    total: int
    online: int
    offline: int


class UserStatsResponse(BaseModel):
    total: int
    by_status: dict[str, int]
    monthly_active: int
    created_today: int


class BillingStatsResponse(BaseModel):
    subscription_by_status: dict[str, int]
    expiring_soon: int
    revenue: float


class SystemHealthResponse(BaseModel):
    database: str
    broker: str


class PlatformStatsResponse(BaseModel):
    """ADR-0020. `GET /admin/platform-stats` — see `application/queries.py`'s `PlatformStatsDTO`
    docstring for the two named-but-deliberately-omitted KPIs ("Live Vehicle Locations",
    "Active Drivers")."""

    organizations: OrganizationStatsResponse
    vehicles: VehicleStatsResponse
    devices: DeviceStatsResponse
    users: UserStatsResponse
    billing: BillingStatsResponse
    system_health: SystemHealthResponse
