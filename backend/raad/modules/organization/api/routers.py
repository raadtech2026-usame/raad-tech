"""HTTP surface of the `organization` module (C2). Mounted at `/api/v1/organizations` and
`/api/v1/regions` (Backend LLD §16.1).

Empty per Phase 4.2 scope — no endpoints beyond health checks are implemented yet.
"""
from fastapi import APIRouter

organizations_router = APIRouter()
regions_router = APIRouter()
