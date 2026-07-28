"""Domain services for the `billing` module (Backend LLD §5.1).

None are defined here. Every cross-aggregate step in the documented payment workflow (Phase-2
§20.2: create Invoice, charge, then "Mark Invoice PAID, extend Subscription") needs a repository
read to load the second aggregate — an I/O-dependent orchestration, which makes it an
*application*-layer concern (`application/services.py`'s `BillingApplicationService`), not a
domain service, mirroring `transport_ops.domain.services`'s identical reasoning for its own
cross-aggregate orchestration (e.g. `Trip.schedule`'s Driver/Route loading).

**Superseded by ADR-0016 (RAAD business model realignment).** This module previously flagged an
unenforced "does `Plan.billing_scope` match `Subscription.subscriber_type`" gap — moot now that
`Subscription` no longer has a `subscriber_type` at all (organization-only, ADR-0016) and
`BillingScope` itself lost its `PARENT` value, leaving nothing left to cross-validate.
"""
