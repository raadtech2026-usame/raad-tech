"""Domain policies for the `iam` module (Backend LLD §5.1).

None are defined in this phase. The RBAC permission matrix (which permissions each `Role`
holds, Phase 2 §12.2) is authorization *business data* pending formal approval — see
`core.security.permissions.PermissionEvaluator` (Phase 4.3) for why it isn't implemented yet.
`SubscriptionAccessPolicy` (CR-1) and `VideoAccessPolicy` (D5) are cross-context access
policies that live in `core/policies/` (Phase 2 §17, owned by `billing`/`video` once those
modules exist) — not `iam`.
"""
