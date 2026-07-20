"""Domain services for the `notifications` module (Backend LLD §5.1).

None are defined in this phase. `Notification` and `DeviceToken` are independent aggregates —
neither's invariants depend on the other's state, and no documented behavior spans both (unlike,
e.g., `billing`'s `renew_parent_subscription`, which genuinely orchestrates two aggregates).
Cross-aggregate orchestration that *does* exist (loading a `Notification`/`DeviceToken` and
checking recipient/owner match before mutating) is I/O-bearing (a repository read), which is an
application-layer concern by this codebase's own established domain-purity rule (LLD §5.3) —
mirrors `billing.domain.services`'s identical empty-file reasoning.
"""
