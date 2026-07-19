"""Domain services for the `billing` module (Backend LLD §5.1).

None are defined here. Every cross-aggregate step in the documented payment workflow (Phase-2
§20.2: create Invoice, charge, then "Mark Invoice PAID, extend Subscription") needs a repository
read to load the second aggregate — an I/O-dependent orchestration, which makes it an
*application*-layer concern (`application/services.py`'s `BillingApplicationService`), not a
domain service, mirroring `transport_ops.domain.services`'s identical reasoning for its own
cross-aggregate orchestration (e.g. `Trip.schedule`'s Driver/Route loading).

**Flagged, not enforced — a genuine judgment call, not a silent decision:** whether
`Plan.billing_scope` must match a `Subscription.subscriber_type` at `Subscription.open()` time
is not cross-validated anywhere in this codebase. Database Design §8.1 documents
`billing_scope`'s *purpose* ("which `SubscriberType` a plan is meant to be purchased by") but no
document states this is an *enforced* invariant, and this phase's own instructions are explicit
about not inventing new business rules. Left unenforced; noted here as a real gap for a future
phase/doc revision to resolve, not decided silently either way.
"""
