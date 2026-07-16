"""Domain policies for the `transport_ops` module (Backend LLD §5.1).

None are defined in this phase. Research surfaced no approved document defining a "student
transport eligibility" concept distinct from the CR-1 parent-access gate
(`SubscriptionAccessPolicy`, Backend LLD §5.4) — and that policy is itself owned by `billing`/
`core/policies`, evaluated against `assignment_state` (a `student_assignments` concept, a later
phase, out of this phase's scope per `entities.py`'s module docstring), not an invariant of the
`Student` aggregate itself. Mirrors `organization.domain.policies`'s identical reasoning for why
`SubscriptionAccessPolicy`/`VideoAccessPolicy` aren't domain policies of that module either. Add
a policy here only once an approved document defines a `Student`-owned access-control predicate
that composes already-resolved facts (the `core.policies.Policy` shape `tracking.domain.
policies.TrackingVisibilityPolicy` already establishes).
"""
