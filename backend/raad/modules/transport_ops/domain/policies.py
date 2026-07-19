"""Domain policies for the `transport_ops` module (Backend LLD §5.1).

None are defined in this phase. Research surfaced no approved document defining a "student
transport eligibility" concept distinct from the CR-1 parent-access gate
(`SubscriptionAccessPolicy`, Backend LLD §5.4) — and that policy lives in `core/policies`
(Backend LLD §17's own module table gives it that "home" explicitly, corrected in Phase 14 after
a dedicated documentation audit found no document ever assigns it to `billing`), evaluated
against `assignment_state` (a `student_assignments` concept, a later phase, out of this phase's
scope per `entities.py`'s module docstring), not an invariant of the `Student` aggregate itself.
Mirrors `organization.domain.policies`'s identical reasoning for why
`SubscriptionAccessPolicy`/`VideoAccessPolicy` aren't domain policies of that module either. Add
a policy here only once an approved document defines a `Student`-owned access-control predicate
that composes already-resolved facts (the `core.policies.Policy` shape `tracking.domain.
policies.TrackingVisibilityPolicy` already establishes).

**Phase 12 (`Trip`):** same reasoning again. `Trip`'s lifecycle-transition legality
(`entities.py`'s `start`/`end`/`interrupt`/`resume`) is a pure function of the aggregate's own
`status` field, enforced directly on the aggregate — not a candidate for a separate policy
object.

**Phase 13 (`StudentAssignment`):** `SubscriptionAccessPolicy` (CR-1) itself was not yet
implemented anywhere in this codebase as of this phase — see this file's own opening paragraph
(corrected in Phase 14: the policy lives in `core/policies`, not `billing`). `StudentAssignment`
only produces the `assignment_state` fact (its own `status` field) and emits the four named
revocation events that policy is documented to consume (Backend LLD §5.4) — it does not evaluate
the policy itself.

**Phase 14 (`core/policies`):** `SubscriptionAccessPolicy` is now implemented
(`raad.core.policies.subscription_access`), taking `AssignmentState` as one of its three
resolved inputs. `transport_ops` still does not call it — wiring `StudentAssignment.status`
into an actual policy evaluation is an enforcement-point concern (a `parent_access_guard`-style
dependency, Backend LLD §16.2) for a later phase, not a domain policy of this module either way.
"""
