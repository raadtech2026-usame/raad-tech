"""Fleet & Device HTTP interface layer (Backend LLD §16) — Phase 7.4 scope. Thin FastAPI
controllers only: request DTO → application service → response DTO. No business logic, no
direct repository/SQLAlchemy access. Public surface of this package.
"""

from raad.modules.fleet_device.api.routers import devices_router, vehicles_router

__all__ = ["devices_router", "vehicles_router"]
