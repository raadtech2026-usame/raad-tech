"""HTTP surface of the `notifications` module (C7). Mounted at `/api/v1/notifications`; the
realtime `/ws/notifications` WebSocket endpoint lives in `api/ws.py` (Backend LLD §16.1, §1).

Empty per Phase 4.2 scope — no endpoints beyond health checks are implemented yet.
"""
from fastapi import APIRouter

notifications_router = APIRouter()
