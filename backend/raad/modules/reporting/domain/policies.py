"""Domain policies for the `reporting` module (Backend LLD §5.1).

None are defined in this phase. No approved document ties report generation/access to
`SubscriptionAccessPolicy` (CR-1) or `VideoAccessPolicy` (D5) — the only two policies this
codebase has (`core/policies`, Phase 14). API Contracts §4.8's role column for both documented
routes (`Org Admin/Finance` for `POST /reports/runs`, `requester` for `GET /reports/runs/{id}`)
describes RBAC-role and resource-ownership concerns, both handled at the application/API layer
(`require_permission`/`ensure_report_run_exists` + an ownership check in `application/
services.py`, mirroring `notifications`'s identical posture) — neither is a domain policy
composing already-resolved facts the way `TrackingVisibilityPolicy`/`SubscriptionAccessPolicy`
are.
"""
