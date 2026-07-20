"""Domain policies for the `platform_audit` module (Backend LLD §5.1).

None are defined here. `GET /admin/audit` and `GET/PATCH /admin/settings` (API Contracts §4.8)
are gated by RBAC (`require_permission`) and `ScopeResolver` — the same two mechanisms every
other module's admin-facing routes already use — not a module-specific policy object.
"""
