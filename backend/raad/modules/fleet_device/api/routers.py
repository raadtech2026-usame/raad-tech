"""HTTP surface of the `fleet_device` module (C3). Mounted at `/api/v1/vehicles` and
`/api/v1/devices` (Backend LLD §16.1).

Empty per Phase 4.2 scope — no endpoints beyond health checks are implemented yet.
"""
from fastapi import APIRouter

vehicles_router = APIRouter()
devices_router = APIRouter()
