"""Module docstring only — `platform_audit` defines no outbound ports needing an adapter this
phase (unlike `billing`/`video`'s `PaymentProviderPort`/`VideoProviderPort`). `AuditEntry`'s
actual write path is the shared-kernel `core.audit.writer.AuditWriter` (ADR-0007), not anything
owned by this module.
"""

from __future__ import annotations
