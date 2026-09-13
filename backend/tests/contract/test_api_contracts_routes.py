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
# sense — `app.openapi()` (this suite's only inspection mechanism, see module docstring) has no
# representation for a `websocket()` route at all, so `_actual_routes()` can never see
# `/ws/tracking`/`/ws/notifications` regardless of whether they're wired. Both are now
# implemented (`interfaces/http/ws.py`, the WebSocket phase) — this list's name predates that
# and is now a schema-limitation exclusion, not a "not built yet" one; kept for the docstring
# trail rather than silently renamed.
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
    (
        "PATCH",
        "/api/v1/parents/{parent_id}/video-access",
        "ADR-0026 SS2 - grant/revoke, its own dedicated permission",
    ),
    (
        "PUT",
        "/api/v1/parents/{parent_id}/transportation",
        "2026-09-12 business-model correction - family-wide Vehicle/Route/Stop assignment, "
        "reuses transport_ops.student_assignments.create (no new permission)",
    ),
    (
        "POST",
        "/api/v1/video/intercom",
        "ADR-0036 - two-way intercom, its own video.intercom.start permission, RAAD-staff-only",
    ),
    # ADR-0039 - organization subscription lifecycle. API Contracts SS4.7 documents five billing
    # routes and no subscription-write surface at all; these four are the platform-admin
    # lifecycle controls (requirement 39G/39S) plus the Org Admin's own self-scoped read.
    (
        "GET",
        "/api/v1/billing/subscriptions/current",
        "ADR-0039 - self-scoped from principal.organization_id, no path/query id to override",
    ),
    (
        "POST",
        "/api/v1/billing/subscriptions/{subscription_id}/suspend",
        "ADR-0039 SS5 - platform-admin only, billing.subscriptions.manage (not org_admin)",
    ),
    (
        "POST",
        "/api/v1/billing/subscriptions/{subscription_id}/reactivate",
        "ADR-0039 SS5 - platform-admin only, billing.subscriptions.manage (not org_admin)",
    ),
    (
        "POST",
        "/api/v1/billing/subscriptions/{subscription_id}/extend-grace",
        "ADR-0039 SS1 - platform-admin grace extension, requirement 39G",
    ),
    (
        "GET",
        "/api/v1/billing/subscriptions/{subscription_id}",
        "uniform-CRUD addition, 2026-09-10 - backs the Founder's Subscription Details page; "
        "GetSubscriptionByIdQuery/get_subscription_by_id already existed, unwired",
    ),
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
    # RAAD business model realignment (ADR-0017): a temporary hand-off credential (Org
    # Admin onboarding, Parent/Driver registration) needs a self-service way to be changed,
    # which API Contracts §2.1 (written before this ADR) never documented.
    (
        "POST",
        "/api/v1/auth/change-password",
        "ADR-0017 forced-password-change gate, no API Contracts row",
    ),
    # ADR-0017 Amendment (2026-07-29): administrator-initiated regeneration for a user who
    # lost their temporary/only password before ever logging in - API Contracts predates this
    # amendment too, same as /auth/change-password above.
    (
        "POST",
        "/api/v1/users/{user_id}/reset-password",
        "ADR-0017 Amendment admin password reset, no API Contracts row",
    ),
    # RAAD business model realignment: the RAAD Platform may display aggregate student/parent
    # counts but must not list individual rows (migration c4d9a2e6f813 revoked
    # transport_ops.students.list/.parents.list from every RAAD-staff role) - these two
    # narrower, count-only routes back that KPI tile. API Contracts predates this realignment.
    ("GET", "/api/v1/students/count", "RAAD business model realignment, no API Contracts row"),
    ("GET", "/api/v1/parents/count", "RAAD business model realignment, no API Contracts row"),
    # ADR-0027 Change 1: resolves a vehicle's active Device/MDVR assignment — the one physical
    # source of both JT808 GPS and JT1078 video for that vehicle. API Contracts §4.2 predates
    # this ADR, same "documented predates the ADR" shape as the entries above.
    (
        "GET",
        "/api/v1/vehicles/{vehicle_id}/device-assignment",
        "ADR-0027 Change 1, no API Contracts row",
    ),
    # Infrastructure/process health probes — outside API Contracts §1's `/api/v1` namespace
    # entirely by design (liveness/readiness checks are never versioned resource routes).
    ("GET", "/health", "process-level health probe, outside /api/v1"),
    ("GET", "/health/live", "process-level health probe, outside /api/v1"),
    ("GET", "/health/ready", "process-level health probe, outside /api/v1"),
    # Priority 1 Item 5 (real health checks + minimum monitoring): same shape as the health
    # probes immediately above — unauthenticated, process-level, outside /api/v1 by design.
    ("GET", "/metrics", "process-level Prometheus scrape target, outside /api/v1 (Priority 1 Item 5)"),

    # Audit P0 #1 fix (2026-08-27): 19 routes built across six real, already-Accepted ADRs and
    # two PROJECT_STATUS.md Priority 1 items, none of which ever got a matching entry here when
    # they landed — the same "documented predates the ADR" shape every group above already
    # establishes, just never applied to this batch. Confirmed via `git log` against each route's
    # own introducing commit.

    # ADR-0023: canonical self-service identity resolution (commit cf9bc6d) — no API Contracts row.
    ("GET", "/api/v1/me", "ADR-0023 canonical self-service identity resolution, no API Contracts row"),
    ("GET", "/api/v1/me/students", "ADR-0023 canonical self-service identity resolution, no API Contracts row"),
    ("GET", "/api/v1/me/driver-profile", "ADR-0023 canonical self-service identity resolution, no API Contracts row"),

    # ADR-0019: account-sharing session cap self-service (commit 07cd3e8) — no API Contracts row.
    ("GET", "/api/v1/auth/sessions", "ADR-0019 account-sharing session cap self-service, no API Contracts row"),
    (
        "DELETE",
        "/api/v1/auth/sessions/{session_id}",
        "ADR-0019 account-sharing session cap self-service, no API Contracts row",
    ),

    # PROJECT_STATUS.md Priority 1 Item 6: RBAC grant/revoke routes (commit 756e8b2), reachable
    # only at the application layer before this — no API Contracts row, same posture
    # Route.remove_stop/Trip.interrupt already establish for a use-case-exists-no-route-yet gap,
    # just now closed with a real route.
    (
        "GET",
        "/api/v1/roles/{role}/permissions",
        "PROJECT_STATUS.md Priority 1 Item 6 RBAC grant/revoke routes, no API Contracts row",
    ),
    (
        "POST",
        "/api/v1/roles/{role}/permissions",
        "PROJECT_STATUS.md Priority 1 Item 6 RBAC grant/revoke routes, no API Contracts row",
    ),
    (
        "POST",
        "/api/v1/roles/{role}/permissions/revoke",
        "PROJECT_STATUS.md Priority 1 Item 6 RBAC grant/revoke routes, no API Contracts row",
    ),
    (
        "GET",
        "/api/v1/scope-assignments/{user_id}",
        "PROJECT_STATUS.md Priority 1 Item 6 RBAC grant/revoke routes, no API Contracts row",
    ),
    (
        "POST",
        "/api/v1/scope-assignments/regions",
        "PROJECT_STATUS.md Priority 1 Item 6 RBAC grant/revoke routes, no API Contracts row",
    ),
    (
        "POST",
        "/api/v1/scope-assignments/regions/revoke",
        "PROJECT_STATUS.md Priority 1 Item 6 RBAC grant/revoke routes, no API Contracts row",
    ),
    (
        "POST",
        "/api/v1/scope-assignments/support",
        "PROJECT_STATUS.md Priority 1 Item 6 RBAC grant/revoke routes, no API Contracts row",
    ),
    (
        "POST",
        "/api/v1/scope-assignments/support/revoke",
        "PROJECT_STATUS.md Priority 1 Item 6 RBAC grant/revoke routes, no API Contracts row",
    ),

    # ADR-0020: platform analytics read model (commit 7b55c87) — no API Contracts row.
    ("GET", "/api/v1/admin/platform-stats", "ADR-0020 platform analytics read model, no API Contracts row"),

    # ADR-0031: fleet-overview online-vehicles read model (commit d2366fc) — no API Contracts row.
    (
        "GET",
        "/api/v1/tracking/vehicles/online",
        "ADR-0031 fleet-overview online-vehicles read model, no API Contracts row",
    ),

    # ADR-0022: payment history list route (commit 59882f7) — POST /billing/payments and
    # /billing/payments/callback from the same ADR are already documented in API Contracts §4.7;
    # only this new GET list route was never added.
    ("GET", "/api/v1/billing/payments", "ADR-0022 payment history list route, no API Contracts row"),

    # ADR-0018: device inventory & allocation (commit d13a5a8) — no API Contracts row.
    ("POST", "/api/v1/device-inventory", "ADR-0018 device inventory & allocation, no API Contracts row"),
    (
        "POST",
        "/api/v1/device-inventory/{inventory_item_id}/allocate",
        "ADR-0018 device inventory & allocation, no API Contracts row",
    ),
    # ---- ADR-0040: ERP finance & reporting ---------------------------------------------------
    #
    # None of these appears in API Contracts SS4.7, which predates the ERP charter entirely
    # (ADR-0038 opened School ERP scope on 2026-09-04; ADR-0040 implements it). Three financial
    # domains now live behind three prefixes and are never merged (ADR-0038 SS2):
    #   /billing          RAAD   -> Organization  (SaaS revenue, C8)
    #   /school-finance   Org    -> Student       (school finance, C11)
    #   /platform-finance Vendor -> RAAD          (operating cost, C12)
    #
    # billing plan management - ADR-0040 SS4. `Plan` had no write route at all before; all four
    # are Founder-only behind a new `billing.plans.manage` permission, deliberately distinct
    # from the read-only `billing.plans.list` five roles already hold.
    ("POST", "/api/v1/billing/plans", "ADR-0040 SS4 - plan catalogue management, Founder-only"),
    ("PATCH", "/api/v1/billing/plans/{plan_id}", "ADR-0040 SS4 - repricing applies from the next period"),
    ("POST", "/api/v1/billing/plans/{plan_id}/activate", "ADR-0040 SS4"),
    ("POST", "/api/v1/billing/plans/{plan_id}/disable", "ADR-0040 SS4 - withdraws from catalogue, cancels nobody"),
    # school_erp (C11) - Organization -> Student. org_admin manages; RAAD staff read only.
    ("GET", "/api/v1/school-finance/categories", "ADR-0040 SS2 - school_erp C11"),
    ("POST", "/api/v1/school-finance/categories", "ADR-0040 SS2 - school_erp C11"),
    ("PATCH", "/api/v1/school-finance/categories/{category_id}", "ADR-0040 SS2 - school_erp C11"),
    ("POST", "/api/v1/school-finance/categories/{category_id}/archive", "ADR-0040 SS2 - archived, never deleted"),
    ("GET", "/api/v1/school-finance/fee-plans", "ADR-0040 SS2 - school_erp C11"),
    ("POST", "/api/v1/school-finance/fee-plans", "ADR-0040 SS2 - school_erp C11"),
    ("PATCH", "/api/v1/school-finance/fee-plans/{fee_plan_id}", "ADR-0040 SS2 - never retro-changes issued invoices"),
    ("POST", "/api/v1/school-finance/fee-plans/{fee_plan_id}/archive", "ADR-0040 SS2 - school_erp C11"),
    ("GET", "/api/v1/school-finance/student-invoices", "ADR-0040 SS2 - school_erp C11"),
    ("POST", "/api/v1/school-finance/student-invoices", "ADR-0040 SS3 - captures transport context at issue time"),
    ("POST", "/api/v1/school-finance/student-invoices/generate", "ADR-0040 SS2 - idempotent monthly billing run"),
    ("POST", "/api/v1/school-finance/student-invoices/{invoice_id}/cancel", "ADR-0040 SS2 - cancel/waive"),
    ("GET", "/api/v1/school-finance/student-invoices/{invoice_id}/payments", "ADR-0040 SS2 - school_erp C11"),
    ("POST", "/api/v1/school-finance/student-invoices/{invoice_id}/payments", "ADR-0040 SS2 - partial payments supported"),
    ("GET", "/api/v1/school-finance/student-payments", "ADR-0040 SS2 - school_erp C11"),
    ("POST", "/api/v1/school-finance/student-payments/{payment_id}/void", "ADR-0040 SS2 - reverses its invoice too"),
    ("GET", "/api/v1/school-finance/income", "ADR-0040 SS2 - school_erp C11"),
    ("POST", "/api/v1/school-finance/income", "ADR-0040 SS2 - non-student income only"),
    ("POST", "/api/v1/school-finance/income/{income_id}/void", "ADR-0040 SS2 - school_erp C11"),
    ("GET", "/api/v1/school-finance/expenses", "ADR-0040 SS2 - school_erp C11"),
    ("POST", "/api/v1/school-finance/expenses", "ADR-0040 SS2 - optional per-vehicle attribution"),
    ("POST", "/api/v1/school-finance/expenses/{expense_id}/void", "ADR-0040 SS2 - school_erp C11"),
    ("GET", "/api/v1/school-finance/summary", "ADR-0040 SS2 - organization finance KPIs"),
    ("GET", "/api/v1/school-finance/vehicles", "ADR-0040 SS2 - vehicle financial overview, one grouped query"),
    ("GET", "/api/v1/school-finance/vehicles/{vehicle_id}/invoices", "ADR-0040 SS2 - backs the printable bus report"),
    ("GET", "/api/v1/school-finance/students/{student_id}/invoices", "ADR-0040 SS2 - one student's history"),
    ("GET", "/api/v1/school-finance/profit-and-loss", "ADR-0040 SS2 - from recorded transactions only"),
    # 2026-09-10 explicit user directive ("Parent & Student Domain Restructure + Parent
    # Payments") - the family-level all-time summary, unaffected by ADR-0042 (still reads across
    # a parent's own children, now via real ParentInvoice rows instead of StudentInvoice).
    (
        "GET",
        "/api/v1/school-finance/parents/{parent_id}/summary",
        "2026-09-10 parent finance - family-level sum across a parent's own children",
    ),
    # ADR-0042 (2026-09-11, supersedes ADR-0041 SS1) - ParentBillingProfile + ParentInvoice are
    # real aggregates now, not a StudentInvoice-grouping read model. New permission namespace
    # (school_erp.parent_billing_profiles.*/.parent_invoices.*, migration a9c73e5f0b8d). The old
    # allocate-across-many-invoices payment quick-action
    # (GET/POST /school-finance/parents/{parent_id}/payments) and the grouped-read routes
    # (GET /school-finance/parents/{parent_id}/invoices/{period}) are removed outright, not kept
    # alongside the real thing - see ADR-0042's own "Correction made during implementation" note.
    (
        "GET",
        "/api/v1/school-finance/parents/{parent_id}/billing-profile",
        "ADR-0042 - a family's actual recurring transportation charge, if any",
    ),
    (
        "PUT",
        "/api/v1/school-finance/parents/{parent_id}/billing-profile",
        "ADR-0042 - create or update in place, no Fee Plan required",
    ),
    (
        "PATCH",
        "/api/v1/school-finance/parent-billing-profiles/{billing_profile_id}/status",
        "ADR-0042 - activate/deactivate, stops future generation without deleting history",
    ),
    (
        "POST",
        "/api/v1/school-finance/parent-invoices/generate",
        "ADR-0042 - the monthly billing run, idempotent per (parent, period)",
    ),
    (
        "GET",
        "/api/v1/school-finance/parent-invoices",
        "ADR-0042 - every real Parent Invoice in scope, the primary Finance page listing",
    ),
    (
        "GET",
        "/api/v1/school-finance/parent-invoices/{invoice_id}",
        "ADR-0042 - one Parent Invoice's own child line items",
    ),
    (
        "PATCH",
        "/api/v1/school-finance/parent-invoices/{invoice_id}/payment-status",
        "ADR-0042 - the entire payment workflow: Unpaid/Partial/Paid, no separate payment ledger",
    ),
    (
        "POST",
        "/api/v1/school-finance/parent-invoices/{invoice_id}/cancel",
        "ADR-0042 - cancel an issued-in-error invoice; blocked once it has received payment",
    ),
    # platform_finance (C12) - Vendor -> RAAD. founder/finance_staff only; no org_admin grant
    # exists in this namespace at all, and these tables carry no organization_id to scope by.
    ("GET", "/api/v1/platform-finance/categories", "ADR-0040 SS1 - platform_finance C12"),
    ("POST", "/api/v1/platform-finance/categories", "ADR-0040 SS1 - platform_finance C12"),
    ("GET", "/api/v1/platform-finance/expenses", "ADR-0040 SS1 - RAAD operating costs"),
    ("POST", "/api/v1/platform-finance/expenses", "ADR-0040 SS1 - RAAD operating costs"),
    ("POST", "/api/v1/platform-finance/expenses/{expense_id}/void", "ADR-0040 SS1"),
    ("GET", "/api/v1/platform-finance/income", "ADR-0040 SS1 - non-subscription income only"),
    ("POST", "/api/v1/platform-finance/income", "ADR-0040 SS1 - subscription kind rejected, billing owns it"),
    ("POST", "/api/v1/platform-finance/income/{income_id}/void", "ADR-0040 SS1"),
    ("GET", "/api/v1/platform-finance/profit-and-loss", "ADR-0040 SS1 - reads SaaS revenue from billing"),
    # reporting - ADR-0040 SS6. Synchronous render-and-stream, because Phase-2 SS10.1's object
    # store does not exist; the async ReportRun aggregate is untouched and still the right home
    # for long runs once one does.
    ("GET", "/api/v1/reports/catalog", "ADR-0040 SS6 - role-filtered report catalogue"),
    ("GET", "/api/v1/reports/{definition_key}/export", "ADR-0040 SS6 - renders PDF/XLSX inline"),
    (
        "GET",
        "/api/v1/reports/{definition_key}/preview",
        "ADR-0041 SS3 - JSON preview, same build_table call export uses",
    ),
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


def _flattened_route_declaration_order() -> list[tuple[frozenset[str], str]]:
    """The actual `(methods, relative_path)` sequence FastAPI will try to match against, in
    the exact order it will try them — i.e. Starlette's own "first full match wins" contract.

    Not `app.openapi()`: that enumerates the documented *set* of paths and says nothing about
    *order*, which is exactly the axis this test needs. Walks `_IncludedRouter.original_router`
    (this FastAPI version's mount-style router wrapper) recursively, since a router can itself
    include sub-routers.
    """
    app = create_app()

    def flatten(routes) -> list:
        out: list = []
        for route in routes:
            out.append(route)
            nested_router = getattr(route, "original_router", None)
            if nested_router is not None:
                out.extend(flatten(nested_router.routes))
        return out

    ordered = []
    for route in flatten(app.routes):
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if methods and path:
            ordered.append((frozenset(methods), path))
    return ordered


class SubscriptionRouteOrderingTests(unittest.TestCase):
    """Regression: `GET /billing/subscriptions/{subscription_id}` (added 2026-09-10, backing
    the Founder's Subscription Details page) must be declared *after* every literal sibling
    path under `/subscriptions` — `current` above all.

    Starlette dispatches by first full match in declaration order. A `{subscription_id}`
    route declared before `current` would capture `GET /subscriptions/current` with
    `subscription_id="current"`, and `ensure_subscription_exists` would raise `NotFoundError`
    for a request that has nothing to do with a missing subscription — a real, live-reproduced
    failure mode this codebase has already hit once this phase (three ADR-0039 lifecycle
    routes going 500 on an unrelated `NameError`). This test makes the ordering invariant the
    router module's own comment documents into something CI actually checks, rather than a
    comment a future edit can silently invalidate.
    """

    def test_literal_subscription_paths_precede_the_by_id_route(self) -> None:
        order = _flattened_route_declaration_order()
        get_paths = [path for methods, path in order if "GET" in methods]
        subscription_get_paths = [p for p in get_paths if p.startswith("/subscriptions")]

        self.assertIn("/subscriptions/current", subscription_get_paths)
        self.assertIn("/subscriptions/{subscription_id}", subscription_get_paths)

        current_index = subscription_get_paths.index("/subscriptions/current")
        by_id_index = subscription_get_paths.index("/subscriptions/{subscription_id}")
        self.assertLess(
            current_index,
            by_id_index,
            "GET /subscriptions/current must be declared before GET "
            "/subscriptions/{subscription_id}, or it will never be reached — a "
            "{subscription_id} path parameter matches the literal string 'current' too.",
        )


if __name__ == "__main__":
    unittest.main()
