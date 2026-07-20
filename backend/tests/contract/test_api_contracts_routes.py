"""Contract tests: the running app's real route registration against
`docs/business/RAAD_Phase3.3_API_Contracts_v1.md`'s documented `/api/v1` surface
(`.claude/rules/testing.md` #4: "a passing contract test means the implementation matches the
documented API, not just that it returns 200").

**Scope, deliberately: OpenAPI-schema-based route/method existence only, not live request/
response validation.** `app.openapi()` reflects the *real* FastAPI route registration (every
`@router.get/post/patch/delete` decorator actually present in source) — comparing it against the
documented contract genuinely answers "does the implementation match the documented API," not
just "does this test file assert what I already believe." What this suite does **not** do:
exercise a live HTTP request/response cycle (status codes, response body shapes, auth
enforcement) — that would need `fastapi.testclient.TestClient`, which needs `httpx`, which is
**not** an approved dependency in this codebase yet (`.claude/rules/workflow.md` #1/#2 requires
explaining a new dependency and getting explicit go-ahead before installing one; not sought this
phase, to avoid a further pause after `redis-py`'s already-used approval). Flagged here as a
real, deliberate scope limit, not silently presented as a full end-to-end contract suite.

**A real, load-bearing finding this suite caught before it existed as a test:** `GET
/organizations`, `/regions`, `/vehicles`, `/devices`, `/users` were all documented (API
Contracts §4.1/§4.2, "GET/POST") but never implemented — each router's own module docstring had
already flagged this, explicitly deferred pending `ScopeResolver`, which ADR-0005 (this same
Backend Stabilization phase) has since resolved. All five are now built; see each module's own
`domain/repositories.py`/`application/services.py`/`api/routers.py` diffs for the fix.
"""

from __future__ import annotations

import unittest

from raad.main import create_app

# --- Documented routes (API Contracts §2, §4.1-§4.8) ---------------------------------------
# (method, path, citation). `path` uses this codebase's own actual FastAPI parameter names
# (e.g. `{organization_id}`, not the doc's generic `{id}`) since that's what `app.openapi()`
# actually reports.
DOCUMENTED_ROUTES: list[tuple[str, str, str]] = [
    # §2.1 Authentication
    ("POST", "/api/v1/auth/login", "API Contracts §2.1"),
    ("POST", "/api/v1/auth/refresh", "API Contracts §2.1"),
    ("POST", "/api/v1/auth/logout", "API Contracts §2.1"),
    ("GET", "/api/v1/auth/me", "API Contracts §2.1"),
    # §4.1 Organizations, Regions, Users (C1/C2)
    ("GET", "/api/v1/organizations", "API Contracts §4.1"),
    ("POST", "/api/v1/organizations", "API Contracts §4.1"),
    ("GET", "/api/v1/organizations/{organization_id}", "API Contracts §4.1"),
    ("PATCH", "/api/v1/organizations/{organization_id}", "API Contracts §4.1"),
    ("GET", "/api/v1/regions", "API Contracts §4.1"),
    ("POST", "/api/v1/regions", "API Contracts §4.1"),
    ("GET", "/api/v1/users", "API Contracts §4.1"),
    ("POST", "/api/v1/users", "API Contracts §4.1"),
    ("GET", "/api/v1/users/{user_id}", "API Contracts §4.1 (uniform-CRUD addition)"),
    (
        "PATCH",
        "/api/v1/users/{user_id}",
        "API Contracts §4.1's documented `POST /users/{id}/disable` is served by this "
        "generic status-PATCH instead, mirroring `PATCH /organizations/{id}`'s identical "
        "consolidation (iam.api.routers's own module docstring).",
    ),
    # §4.2 Fleet & Device (C3)
    ("GET", "/api/v1/vehicles", "API Contracts §4.2"),
    ("POST", "/api/v1/vehicles", "API Contracts §4.2"),
    ("GET", "/api/v1/vehicles/{vehicle_id}", "API Contracts §4.2 (uniform-CRUD addition)"),
    ("PATCH", "/api/v1/vehicles/{vehicle_id}", "API Contracts §4.2 (uniform-CRUD addition)"),
    ("GET", "/api/v1/devices", "API Contracts §4.2"),
    ("POST", "/api/v1/devices", "API Contracts §4.2"),
    ("GET", "/api/v1/devices/{device_id}", "API Contracts §4.2 (uniform-CRUD addition)"),
    ("PATCH", "/api/v1/devices/{device_id}", "API Contracts §4.2 (uniform-CRUD addition)"),
    ("POST", "/api/v1/devices/{device_id}/activate", "API Contracts §4.2"),
    ("POST", "/api/v1/devices/{device_id}/assign", "API Contracts §4.2"),
    ("POST", "/api/v1/devices/{device_id}/reassign", "API Contracts §4.2"),
    ("POST", "/api/v1/devices/{device_id}/unassign", "API Contracts §4.2"),
    # §4.3 Transport Operations (C4)
    ("GET", "/api/v1/students", "API Contracts §4.3"),
    ("POST", "/api/v1/students", "API Contracts §4.3"),
    ("POST", "/api/v1/students/{student_id}/status", "API Contracts §4.3"),
    ("GET", "/api/v1/parents", "API Contracts §4.3"),
    ("POST", "/api/v1/parents", "API Contracts §4.3"),
    ("GET", "/api/v1/routes", "API Contracts §4.3"),
    ("POST", "/api/v1/routes", "API Contracts §4.3"),
    ("GET", "/api/v1/routes/{route_id}/stops", "API Contracts §4.3"),
    ("POST", "/api/v1/routes/{route_id}/stops", "API Contracts §4.3"),
    ("GET", "/api/v1/student-assignments", "API Contracts §4.3"),
    ("POST", "/api/v1/student-assignments", "API Contracts §4.3"),
    ("POST", "/api/v1/student-assignments/{student_assignment_id}/end", "API Contracts §4.3"),
    ("GET", "/api/v1/trips", "API Contracts §4.3"),
    ("POST", "/api/v1/trips", "API Contracts §4.3"),
    ("POST", "/api/v1/trips/{trip_id}/start", "API Contracts §4.3"),
    ("POST", "/api/v1/trips/{trip_id}/end", "API Contracts §4.3"),
    ("PATCH", "/api/v1/trips/{trip_id}/driver", "API Contracts §4.3"),
    # §4.4 Tracking (C5) — WS route excluded, see WS_ROUTES_DEFERRED below
    ("GET", "/api/v1/tracking/vehicles/{vehicle_id}/latest", "API Contracts §4.4"),
    ("GET", "/api/v1/tracking/trips/{trip_id}/positions", "API Contracts §4.4"),
    # §4.5 Video (C6)
    ("POST", "/api/v1/video/live", "API Contracts §4.5"),
    ("POST", "/api/v1/video/playback", "API Contracts §4.5"),
    ("POST", "/api/v1/video/sessions/{session_id}/stop", "API Contracts §4.5"),
    # §4.6 Notifications (C7) — WS route excluded, see WS_ROUTES_DEFERRED below
    ("GET", "/api/v1/notifications", "API Contracts §4.6"),
    ("POST", "/api/v1/notifications/{notification_id}/read", "API Contracts §4.6"),
    ("POST", "/api/v1/notifications/tokens", "API Contracts §4.6"),
    ("DELETE", "/api/v1/notifications/tokens/{device_token_id}", "API Contracts §4.6"),
    # §4.7 Billing (C8)
    ("GET", "/api/v1/billing/plans", "API Contracts §4.7"),
    ("GET", "/api/v1/billing/subscriptions", "API Contracts §4.7"),
    ("GET", "/api/v1/billing/invoices", "API Contracts §4.7"),
    ("POST", "/api/v1/billing/payments", "API Contracts §4.7"),
    ("POST", "/api/v1/billing/payments/callback", "API Contracts §4.7"),
    # §4.8 Reports (C9) & Admin/Audit (C10)
    ("POST", "/api/v1/reports/runs", "API Contracts §4.8"),
    ("GET", "/api/v1/reports/runs/{report_run_id}", "API Contracts §4.8"),
    ("GET", "/api/v1/admin/audit", "API Contracts §4.8"),
    ("GET", "/api/v1/admin/settings", "API Contracts §4.8"),
    ("PATCH", "/api/v1/admin/settings", "API Contracts §4.8"),
]

# Documented but genuinely not implemented — real, confirmed, deliberately deferred gaps, not
# silently forgotten. Password reset needs a reset-token + email/SMS delivery mechanism (the
# same "not an approved dependency" class of gap FCM/push already carries); MFA verify needs a
# TOTP/OTP challenge-response flow. Neither is a "wire up an existing list_all()" fix like the
# five this suite's own module docstring names — both are genuinely new business logic needing
# their own approved design first (`.claude/rules/workflow.md` #8), not built this phase.
DOCUMENTED_BUT_NOT_IMPLEMENTED: list[tuple[str, str, str]] = [
    ("POST", "/api/v1/auth/password/forgot", "API Contracts §2.1 — needs a reset-token + "
     "delivery mechanism, not yet designed"),
    ("POST", "/api/v1/auth/password/reset", "API Contracts §2.1 — same dependency as forgot"),
    ("POST", "/api/v1/auth/mfa/verify", "API Contracts §2.2 — 'if enabled... recommended', "
     "no TOTP/OTP challenge-response flow exists"),
    ("POST", "/api/v1/regions/{region_id}/assignments", "API Contracts §4.1 — module "
     "ownership needed an explicit design decision (organization.domain.entities's own "
     "docstring); ScopeAssignmentApplicationService.grant_region_assignment now exists "
     "(ADR-0005) but has no HTTP route yet, the same 'use-case exists, no approved endpoint "
     "yet' posture Route.remove_stop/Trip.interrupt already establish"),
    ("GET", "/api/v1/devices/{device_id}/status", "API Contracts §4.2 — connectivity is "
     "device-plane runtime state (JT808 service), not yet implementable (fleet_device.api."
     "routers's own module docstring)"),
]

# WebSocket routes (API Contracts §4.4/§4.6) are not REST/OpenAPI-schema routes in the same
# sense — deliberately excluded from the schema-based check above, not silently ignored. Both
# are already documented as deferred (broker/Notification-Worker-adjacent realtime fan-out,
# CLAUDE.md's own "Known gaps").
WS_ROUTES_DEFERRED = ["/ws/tracking", "/ws/notifications"]

# Built but not in API Contracts' literal table — each already flagged in its own module's
# router docstring at the time it was built, not a silent addition. `.claude/rules/api.md` #5:
# generated docs (never hand-authored specs) are the source of truth for what's *built*; this
# list is this suite's own accounting of the delta against the *documented* contract.
ALLOWED_UNDOCUMENTED_EXTRAS: list[tuple[str, str, str]] = [
    # Uniform-CRUD get-by-id/update additions, the same precedent established repeatedly
    # across this codebase for every aggregate with a documented list/create row.
    ("GET", "/api/v1/regions/{region_id}", "uniform-CRUD addition"),
    ("PATCH", "/api/v1/regions/{region_id}", "uniform-CRUD addition"),
    ("GET", "/api/v1/parents/{parent_id}", "uniform-CRUD addition"),
    ("PATCH", "/api/v1/parents/{parent_id}", "uniform-CRUD addition"),
    ("GET", "/api/v1/parents/{parent_id}/students", "ListStudentsForParentQuery's own route"),
    ("GET", "/api/v1/students/{student_id}", "uniform-CRUD addition"),
    ("PATCH", "/api/v1/students/{student_id}", "uniform-CRUD addition"),
    ("GET", "/api/v1/students/{student_id}/parents", "student_parents link management"),
    ("POST", "/api/v1/students/{student_id}/parents", "student_parents link management"),
    ("DELETE", "/api/v1/students/{student_id}/parents/{parent_id}", "student_parents unlink"),
    ("GET", "/api/v1/routes/{route_id}", "uniform-CRUD addition"),
    ("PATCH", "/api/v1/routes/{route_id}", "uniform-CRUD addition"),
    (
        "GET",
        "/api/v1/student-assignments/{student_assignment_id}",
        "uniform-CRUD addition",
    ),
    ("GET", "/api/v1/trips/{trip_id}", "uniform-CRUD addition, CLAUDE.md's own note"),
    ("GET", "/api/v1/notifications/{notification_id}", "uniform-CRUD addition"),
    # /drivers has no corresponding row in API Contracts §4.3 at all (only Trip-level
    # PATCH /trips/{id}/driver is documented) — built anyway on Database Design §6.1's
    # unambiguous table ownership, flagged in transport_ops.api.routers's own module
    # docstring, per CLAUDE.md's "Transport Operations" paragraph.
    ("GET", "/api/v1/drivers", "Database Design §6.1 ownership, no API Contracts row"),
    ("POST", "/api/v1/drivers", "Database Design §6.1 ownership, no API Contracts row"),
    ("GET", "/api/v1/drivers/{driver_id}", "uniform-CRUD addition"),
    ("PATCH", "/api/v1/drivers/{driver_id}", "uniform-CRUD addition"),
    # Infrastructure/process health probes — outside API Contracts §1's `/api/v1` namespace
    # entirely by design (liveness/readiness checks are never versioned resource routes).
    ("GET", "/health", "process-level health probe, outside /api/v1"),
    ("GET", "/health/live", "process-level health probe, outside /api/v1"),
    ("GET", "/health/ready", "process-level health probe, outside /api/v1"),
]


def _actual_routes() -> set[tuple[str, str]]:
    app = create_app()
    schema = app.openapi()
    routes: set[tuple[str, str]] = set()
    for path, operations in schema["paths"].items():
        for method in operations:
            if method.upper() in ("GET", "POST", "PATCH", "PUT", "DELETE"):
                routes.add((method.upper(), path))
    return routes


class DocumentedRoutesExistTests(unittest.TestCase):
    def test_every_documented_route_is_registered(self) -> None:
        actual = _actual_routes()
        missing = [
            (method, path, citation)
            for method, path, citation in DOCUMENTED_ROUTES
            if (method, path) not in actual
        ]
        self.assertEqual(
            missing,
            [],
            f"Documented routes missing from the running app: {missing}",
        )


class NoSilentUndocumentedRoutesTests(unittest.TestCase):
    def test_every_built_route_is_either_documented_or_an_explained_extra(self) -> None:
        actual = _actual_routes()
        documented = {(method, path) for method, path, _ in DOCUMENTED_ROUTES}
        allowed_extra = {(method, path) for method, path, _ in ALLOWED_UNDOCUMENTED_EXTRAS}
        unexplained = sorted(actual - documented - allowed_extra)
        self.assertEqual(
            unexplained,
            [],
            "Routes exist that are neither in API Contracts nor in this suite's own "
            f"ALLOWED_UNDOCUMENTED_EXTRAS accounting — add a citation, don't leave it "
            f"silent: {unexplained}",
        )


if __name__ == "__main__":
    unittest.main()
