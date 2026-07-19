"""v1 router aggregation (Backend LLD §16.1).

One router per resource prefix, each owned by exactly one module, mounted under the
versioned base path `/api/v1`. `iam`'s `auth_router`/`users_router` have real endpoints as of
Phase 5.4; every other router remains empty (Phase 4.2 scope) — this file establishes correct
placement so real endpoints land under the right prefix as each module's layers are built out.
"""

from fastapi import APIRouter

from raad.modules.billing.api.routers import billing_router
from raad.modules.fleet_device.api.routers import devices_router, vehicles_router
from raad.modules.iam.api.routers import auth_router, users_router
from raad.modules.notifications.api.routers import notifications_router
from raad.modules.organization.api.routers import organizations_router, regions_router
from raad.modules.platform_audit.api.routers import admin_router
from raad.modules.reporting.api.routers import reports_router
from raad.modules.tracking.api.routers import tracking_router
from raad.modules.transport_ops.api.routers import (
    drivers_router,
    parents_router,
    routes_router,
    student_assignments_router,
    students_router,
    trips_router,
)
from raad.modules.video.api.routers import video_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])  # iam (C1)
api_router.include_router(users_router, prefix="/users", tags=["users"])

api_router.include_router(
    organizations_router, prefix="/organizations", tags=["organizations"]
)  # organization (C2)
api_router.include_router(regions_router, prefix="/regions", tags=["organizations"])

api_router.include_router(
    vehicles_router, prefix="/vehicles", tags=["fleet"]
)  # fleet_device (C3)
api_router.include_router(devices_router, prefix="/devices", tags=["fleet"])

api_router.include_router(
    students_router, prefix="/students", tags=["transport-ops"]
)  # transport_ops (C4)
api_router.include_router(parents_router, prefix="/parents", tags=["transport-ops"])
api_router.include_router(routes_router, prefix="/routes", tags=["transport-ops"])
api_router.include_router(trips_router, prefix="/trips", tags=["transport-ops"])
api_router.include_router(
    drivers_router, prefix="/drivers", tags=["transport-ops"]
)  # transport_ops (C4) — Phase 10.8; no documented API Contracts row, see routers.py
api_router.include_router(
    student_assignments_router,
    prefix="/student-assignments",
    tags=["transport-ops"],
)  # transport_ops (C4) — Phase 13

api_router.include_router(
    tracking_router, prefix="/tracking", tags=["tracking"]
)  # tracking (C5)

api_router.include_router(video_router, prefix="/video", tags=["video"])  # video (C6)

api_router.include_router(
    notifications_router, prefix="/notifications", tags=["notifications"]
)  # notifications (C7)

api_router.include_router(
    billing_router, prefix="/billing", tags=["billing"]
)  # billing (C8)

api_router.include_router(
    reports_router, prefix="/reports", tags=["reporting"]
)  # reporting (C9)

api_router.include_router(
    admin_router, prefix="/admin", tags=["admin"]
)  # platform_audit (C10)

# WebSocket endpoints (/ws/tracking, /ws/notifications) are wired separately in
# interfaces/http/ws.py once the tracking/notifications modules have realtime handlers
# (Backend LLD §16.2) — not added in this phase.
