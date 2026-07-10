"""HTTP surface of the `iam` module (C1). Mounted at `/api/v1/auth` (Backend LLD §16.1).

Empty per Phase 4.2 scope — no endpoints beyond health checks are implemented yet. Real
routes (login, refresh, logout, password reset, `/auth/me`) are added once `core/security`
and this module's application/domain layers exist.
"""
from fastapi import APIRouter

auth_router = APIRouter()
