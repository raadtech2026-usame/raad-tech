"""Domain policies for the `organization` module (Backend LLD §5.1).

None are defined in this phase. The region/support scope filter (`effective_org_scope`, Phase 2
§17.4) and the operator/campus admin scope filter (§18.4) are *authorization*-layer concerns —
they gate what a RAAD-staff or org-admin principal may query, evaluated against the requesting
`Principal` (`core.tenancy`), not an invariant of the `Organization`/`Region` aggregates
themselves. They belong in `core/policies/` or the authorization layer once that scoping is
implemented, not here — same reasoning `iam.domain.policies` gives for why the RBAC matrix and
`SubscriptionAccessPolicy`/`VideoAccessPolicy` aren't domain policies of `iam` either.
"""
