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
