"""HTTP request/response DTOs for `reporting` (Backend LLD §16; API Contracts §4.8). Pydantic
models are transport-only — no business logic here; `routers.py` does the DTO<->application
translation. Mirrors `billing.api.schemas`/`notifications.api.schemas`'s shape exactly.

Only the two documented endpoints (API Contracts §4.8 lines 188-189) get a schema here. No
documented request/response body example exists for `POST /reports/runs` either (unlike
`billing`'s payment endpoint) — `RequestReportRequest`'s fields mirror `ReportRun.request()`'s
own factory fields 1:1, the established convention every other module's create-request schema
already follows when no literal example is documented.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RequestReportRequest(BaseModel):
    organization_id: str
    type: str
    params: dict[str, Any] | None = None


class ReportRunResponse(BaseModel):
    id: str
    organization_id: str
    type: str
    params: dict[str, Any] | None
    status: str
    artifact_url: str | None
    requested_by: str
    created_at: datetime
    completed_at: datetime | None
