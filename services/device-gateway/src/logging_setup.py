"""Structured connection/lifecycle logging for the JT808 transport service (Phase 9.1).

Standalone from `backend.raad.core.logging` — independent deployables don't share code
(`.claude/rules/architecture.md` #2). Minimal JSON-line formatter, stdlib `logging` only.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_with_fields(
    logger: logging.Logger, level: int, message: str, **fields: object
) -> None:
    logger.log(level, message, extra={"extra_fields": fields})
