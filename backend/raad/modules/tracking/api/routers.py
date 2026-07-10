"""HTTP surface of the `tracking` module (C5). Mounted at `/api/v1/tracking` (REST reads);
the realtime `/ws/tracking` WebSocket endpoint lives in `api/ws.py` (Backend LLD §16.1, §1).

Empty per Phase 4.2 scope — no endpoints beyond health checks are implemented yet.
"""
from fastapi import APIRouter

tracking_router = APIRouter()
