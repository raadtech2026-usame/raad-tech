"""WebSocket route aggregation (Backend LLD §16.1), the WebSocket-side mirror of
`interfaces/http/api_v1.py`'s REST aggregation: one `APIRouter` per module, mounted here under
its own documented path, never hand-built endpoint-by-endpoint in this file. `api_v1.py`'s own
module docstring used to name this exact file as where `/ws/tracking`/`/ws/notifications`
would be "wired separately... once the tracking/notifications modules have realtime handlers"
— they now do (`modules/tracking/api/ws.py`, `modules/notifications/api/ws.py`), so this file
does that wiring.

Deliberately **not** mounted under `/api/v1` (unlike every REST router) — API Contracts §11.1
gives the connect URLs as `wss://.../ws/tracking` and `wss://.../ws/notifications`, un-prefixed
by any API version segment, matching `interfaces/http/health.py`'s identical un-versioned
placement for the same reason: these are their own stable, protocol-level entry points, not
resource routes under the versioned REST surface.
"""

from __future__ import annotations

from fastapi import APIRouter

from raad.modules.notifications.api.ws import notifications_ws_router
from raad.modules.tracking.api.ws import tracking_ws_router

ws_router = APIRouter()

ws_router.include_router(tracking_ws_router, prefix="/ws/tracking")
ws_router.include_router(notifications_ws_router, prefix="/ws/notifications")
