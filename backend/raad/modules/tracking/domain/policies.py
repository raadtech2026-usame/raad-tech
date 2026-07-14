"""Domain policies for the `tracking` module (Backend LLD §5.1; Phase 2 §23;
`.claude/rules/backend.md` #6: "Safety-over-billing is one policy object... never scattered
`if subscription_active` checks"; `.claude/rules/security.md` #4: "The tracking-visibility
predicate is: capability ∧ scope ∧ ownership ∧ time-window. Every live-tracking surface (web,
mobile, WebSocket, REST) must implement this exact predicate — no surface may take a shortcut
version of it.").

`TrackingVisibilityPolicy` is that single policy object: Phase 2 §23.3's decision flow ("can
user X see live position of vehicle V now?") composed as one `Policy.evaluate(...)` call, so
every tracking surface calls the same object instead of re-deriving the predicate.

**It composes four already-resolved booleans; it does not resolve any of them itself.** Each
dimension requires I/O or belongs to another module's authority, so resolving it here would
either break domain purity (LLD §5.3: no I/O in the domain layer) or duplicate a decision that
belongs elsewhere:
- `has_capability` — role-based capability grant (RBAC permission matrix, pending approval per
  `fleet_device.domain.policies`'s identical deferral) *and* the safety/subscription policy
  (see the D4/CR-1 note below).
- `within_scope` — org/region scope (`.claude/rules/security.md` #3, §17 `effective_org_scope`
  for RAAD staff) — owned by `core/security`/`organization`.
- `has_ownership` — "parent owns this vehicle/trip via their child's assignment" — owned by
  `transport_ops` (student-route-vehicle linkage).
- `within_time_window` — "vehicle has an active trip" for Parent/Driver, or "always" for
  Org Admin/RAAD staff (Phase 2 §23.1's matrix) — owned by `transport_ops`'s `Trip` state.

**Flagged conflict between two approved documents (`.claude/rules/documentation.md` #2: report
rather than silently pick one), not resolved by this policy:** Phase 2 §9.6/§23.2 state the
parent live-GPS-during-active-trip capability is "never revoked by subscription lapse" (D4,
safety-over-billing). Backend LLD §5.4 (CR-1) states the *entire* Parent surface — its own text
says explicitly including live GPS — is gated by `assignment_state`/subscription, and that CR-1
"supersedes" the earlier safety policy. This module does not decide which reading wins: it
receives `has_capability` as an already-resolved boolean from whichever policy the owning
module (`billing`, once built) implements, and applies it uniformly. Confirm the D4/CR-1
reconciliation with an approved doc update before that policy is built, not here.
"""

from __future__ import annotations

from raad.core.policies import Policy, PolicyDecision


class TrackingVisibilityPolicy(Policy):
    """Phase 2 §23.3's authoritative predicate for every live-tracking surface. Evaluated in
    the order §23.3's decision-flow diagram gives — capability, then scope, then ownership,
    then time-window — so the `reason` on a denial always names the *first* failing
    dimension, matching the diagram's short-circuit shape. Overrides the base `Policy.evaluate`
    with this policy's own specific keyword-only signature (the base's `*args/**kwargs` shape
    only exists because different policies' decisions depend on different inputs, per
    `core.policies.Policy`'s own docstring)."""

    def evaluate(  # type: ignore[override]
        self,
        *,
        has_capability: bool,
        within_scope: bool,
        has_ownership: bool,
        within_time_window: bool,
    ) -> PolicyDecision:
        if not has_capability:
            return PolicyDecision(
                allowed=False, reason="role_lacks_live_tracking_capability"
            )
        if not within_scope:
            return PolicyDecision(allowed=False, reason="vehicle_outside_caller_scope")
        if not has_ownership:
            return PolicyDecision(allowed=False, reason="not_owner_of_vehicle_or_trip")
        if not within_time_window:
            return PolicyDecision(allowed=False, reason="outside_permitted_time_window")
        return PolicyDecision(allowed=True)
