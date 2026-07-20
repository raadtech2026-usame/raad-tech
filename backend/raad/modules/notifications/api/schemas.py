"""HTTP request/response DTOs for `notifications` (Backend LLD §16; API Contracts §4.6).
Pydantic models are transport-only — no business logic here; `routers.py` does the DTO<->
application translation. Mirrors `billing.api.schemas`'s shape exactly.

Only the four documented REST endpoints (API Contracts §4.6 lines 161-164; `/ws/notifications`,
line 165, has no REST request/response shape) get a schema here. No `CreateNotificationRequest`
exists — no document names a generic `POST /notifications` creation route (`application/
commands.py`'s own docstring); `CreateNotificationCommand` is reachable at the application
layer only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: str
    organization_id: str
    recipient_user_id: str
    type: str
    title: str
    body: str
    data: dict[str, Any] | None
    trip_id: str | None
    status: str
    created_at: datetime
    read_at: datetime | None


class RegisterDeviceTokenRequest(BaseModel):
    fcm_token: str
    platform: str


class DeviceTokenResponse(BaseModel):
    id: str
    user_id: str
    fcm_token: str
    platform: str
    created_at: datetime
    revoked_at: datetime | None
