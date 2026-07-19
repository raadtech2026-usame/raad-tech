"""Domain policies for the `billing` module (Backend LLD §5.1).

None are defined here. `SubscriptionAccessPolicy` (CR-1) — the one policy this module's data
feeds — lives in `core/policies` (Backend LLD §17's own module table), not `billing`; a
dedicated documentation audit before Phase 14 confirmed no approved document ever assigns it to
this module, and Phase 14 implemented it there accordingly. This module only produces the
`subscription_state` fact that policy consumes (`Subscription.status`) — it does not evaluate
the policy itself, mirroring `transport_ops.domain.policies`'s identical reasoning for
`StudentAssignment.status`/`assignment_state`.
"""
