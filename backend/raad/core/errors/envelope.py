"""Standard error envelope (Backend LLD §14.2): `{ error: { code, message, correlation_id,
details? } }`. Every module and every delivery mechanism returns errors in this shape.

`reason`/`required_action` are the CR-1-specific extension API Contracts §3.3/§5.2 documents
for `PARENT_ACCESS_DENIED` (e.g. `reason="SUBSCRIPTION_EXPIRED"`,
`required_action="REDIRECT_TO_PAYMENT"`) — `None`/omitted-in-spirit on every other error code,
never a second envelope shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    correlation_id: str | None = None
    details: Any | None = None
    reason: str | None = None
    required_action: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
