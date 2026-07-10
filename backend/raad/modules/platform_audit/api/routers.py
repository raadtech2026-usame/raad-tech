"""HTTP surface of the `platform_audit` module (C10). Mounted at `/api/v1/admin` (system
settings, audit — Backend LLD §16.1).

Empty per Phase 4.2 scope — no endpoints beyond health checks are implemented yet.
"""
from fastapi import APIRouter

admin_router = APIRouter()
