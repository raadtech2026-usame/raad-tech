"""Logging configuration entrypoint (Backend LLD §13.1).

Application logs (operational) are configured here. This is distinct from the audit log
(platform_audit module, Phase 2 §12.8) — audit is a transactional domain concern, not a
logging side-effect, and is not implemented by this package.
"""
from __future__ import annotations

import logging

from raad.core.config.settings import ObservabilitySettings
from raad.core.logging.formatter import JsonFormatter

_CONFIGURED = False


def configure_logging(settings: ObservabilitySettings) -> None:
    """Idempotent: safe to call once at startup. Installs a single stream handler with the
    structured JSON formatter and sets the root log level from settings."""
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    if _CONFIGURED:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
