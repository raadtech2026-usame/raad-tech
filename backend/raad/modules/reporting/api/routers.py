"""HTTP surface of the `reporting` module (C9). Mounted at `/api/v1/reports` (Backend LLD
§16.1).

Empty per Phase 4.2 scope — no endpoints beyond health checks are implemented yet.
"""
from fastapi import APIRouter

reports_router = APIRouter()
