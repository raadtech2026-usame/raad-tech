"""Shared-kernel audit-trail infrastructure. See `writer.py`'s module docstring and ADR-0007
(`docs/architecture/adr/0007-audit-entries-write-architecture.md`) for why this lives in
`core/`, not any bounded-context module."""

from __future__ import annotations
