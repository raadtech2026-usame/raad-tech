"""Tracking HTTP interface layer (Backend LLD §16) — Phase 8.4 scope. Thin FastAPI
controllers only: request → application service → response DTO. No business logic, no direct
repository/SQLAlchemy access. `/ws/tracking` (API Contracts §11.2) is not part of this
package's scope this phase — see `api/ws.py`. Public surface of this package.
"""

from raad.modules.tracking.api.routers import tracking_router

__all__ = ["tracking_router"]
