"""Standard error envelope (Backend LLD §14.2): `{ error: { code, message, correlation_id,
details? } }`. Every module and every delivery mechanism returns errors in this shape."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    correlation_id: str | None = None
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
