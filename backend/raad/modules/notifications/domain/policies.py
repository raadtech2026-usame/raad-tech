"""Domain policies for the `notifications` module (Backend LLD §5.1).

None are defined in this phase. `SubscriptionAccessPolicy` (CR-1) lives in `core/policies`
(Backend LLD §17's own module table, corrected in Phase 14 — not owned by `billing`, and
certainly not by `notifications`). This module is the one place in the whole architecture where
that policy's documented consumer actually sits (Backend LLD §11.3: "Subscription-access
enforcement in the notification worker (CR-1): for parent recipients, the worker evaluates
`SubscriptionAccessPolicy` and withholds transport notifications from denied parents") — but
the Notification *Worker* itself (event consumption, recipient resolution, broker wiring) is
explicitly out of this phase's scope. `Notification.create()` (`domain/entities.py`) is
therefore an unconditional persist; it does not call `SubscriptionAccessPolicy.evaluate(...)`
itself, for the identical reason `transport_ops.domain.policies`/`tracking.domain.policies`
already give for their own modules:

- Evaluating the policy needs `assignment_state` (a `transport_ops.StudentAssignment` fact) and
  `billing_model`/`subscription_state` (an `organization`/`billing.Subscription` fact) already
  resolved — this module's own repositories can only query its own tables
  (`.claude/rules/backend.md` #3, no cross-module DB reads), so it has no independent way to
  resolve those facts itself even if it wanted to.
- Wiring `SubscriptionAccessPolicy.evaluate(...)` into an actual call site is "an
  enforcement-point concern... for a later phase" (`transport_ops.domain.policies`'s own Phase
  14 note) — specifically, the future Notification Worker's own orchestration, which would
  resolve the three inputs from already-consumed events/read-models and decide *whether to call*
  `create_notification` at all for a denied parent, rather than `create_notification` re-deriving
  the decision after the fact.

This mirrors `transport_ops.domain.policies`/`tracking.domain.policies`'s identical, already-
established posture — `notifications` is not an exception to a pattern this codebase has already
applied consistently three times.
"""
