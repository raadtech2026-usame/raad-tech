"""Structured JSON log formatter (Backend LLD §13.1 — one event per line, machine-readable)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from raad.core.logging.context import get_context
from raad.core.logging.redaction import redact

_RESERVED = logging.LogRecord(
    name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
).__dict__.keys()


class JsonFormatter(logging.Formatter):
    """Renders one JSON object per log line, with bound request/correlation/tenant context
    (from contextvars) merged in and sensitive fields redacted."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(get_context())

        extra = {
            key: value for key, value in record.__dict__.items() if key not in _RESERVED
        }
        payload.update(extra)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(redact(payload), default=str)
