# ADR-0016: Organization-Only Billing Model

## Status
Accepted (direct user decision — RAAD business model realignment, 2026-07-28).

## Context
The current `billing` bounded context is dual-mode, not organization-only:

- `Organization.billing_model` (`raad/modules/organization/domain/value_objects.py`,
  `BillingModel`) is `ENUM(organization_pays, parent_pays)`.
- `Subscription` (`raad/modules/billing/domain/entities.py`) carries both `organization_id`
  (always required) and a polymorphic `subscriber_type: SubscriberType ∈ {ORGANIZATION, PARENT}`
  + `subscriber_id` — a subscription can be opened directly against a `Parent`.
- `Plan.billing_scope: BillingScope` likewise admits a parent-facing plan.
- `RenewParentSubscriptionCommand`/`BillingApplicationService.renew_parent_subscription`
  (`raad/modules/billing/application/`) is the parent-billing entry point at the application
  layer — it has no HTTP route today, but is real, callable code.
- **ADR-0006 (accepted)** — D4/CR-1 safety-over-billing reconciliation — keys parent tracking/
  video access off exactly this `billing_model` value: `SubscriptionAccessPolicy`
  (`raad/core/policies/subscription_access.py`) only evaluates a subscriber's own
  `subscription_state` when `billing_model == PARENT_PAYS`; `ORGANIZATION_PAYS` organizations
  skip that check by design.

The new RAAD business model is explicit: *"RAAD does NOT care how schools collect money from
parents. RAAD bills only Organizations."* This directly conflicts with the `PARENT_PAYS`/
`SubscriberType.PARENT` path. The user has confirmed (2026-07-28) this path should be **deleted
outright**, not kept dormant — unlike the JT808-for-a-future-compliant-vendor precedent
(ADR-0009), `RenewParentSubscriptionCommand` has zero HTTP routes and zero product need it is
being held in reserve for.

Separately, the new model asks the platform to track (not necessarily price by) organization
*usage*: active users, Monthly Active Users (MAU), active devices, active vehicles. No approved
document gives a formula translating usage into price — `Plan` remains flat-priced
(`price: Money`, `vehicle_limit: int | None`). Inventing a pricing formula here would violate
`.claude/rules/workflow.md` #8 exactly as this codebase's own prior phases have already declined
to invent undocumented formulas (e.g. `ReportType` staying an opaque string rather than a
guessed closed enum).

## Decision

### 1. Delete the parent-billing path entirely
- `SubscriberType` collapses to a single value (`ORGANIZATION`) or is removed outright in favor
  of `Subscription` keying purely on `organization_id` — `subscriber_type`/`subscriber_id`
  columns and fields are dropped, not deprecated in place.
- `RenewParentSubscriptionCommand`, `BillingApplicationService.renew_parent_subscription`, and
  `BillingScope`'s parent-facing value are deleted.
- `Organization.billing_model` (`BillingModel` enum, `organization/domain/value_objects.py`) is
  removed entirely — not kept as a single-value enum forever. `organizations.billing_model`
  column is dropped by migration. `PATCH /organizations/{id}`'s already-unimplemented
  `billing_model` field (flagged in `UpdateOrganizationRequest`'s own docstring as never wired to
  a `change_billing_model` behavior) is removed from the request schema — there is nothing left
  to change.
- A migration drops `organizations.billing_model` and `subscriptions.subscriber_type`/
  `subscriber_id`, backfilling nothing (every existing row is already `ORGANIZATION_PAYS`/
  `ORGANIZATION`-typed in this pre-production codebase).

### 2. ADR-0006 amendment
`0006-d4-cr1-safety-over-billing-reconciliation.md` gets a short **Amendment** section (see that
file) recording that `SubscriptionAccessPolicy`'s `billing_model` input is removed —
CR-1 now evaluates exactly one subscription-state check (the organization's own subscription),
with no `PARENT_PAYS` branch to skip. D4's own precedence rule (safety-over-billing during an
active trip) is unchanged; only the now-dead branch is removed.

### 3. Usage metrics: tracked and exposed, not priced
`Plan`/`Subscription` gain no new columns for pricing. Instead, new **read-only** query methods
are added (implemented as part of ADR-0020's platform-analytics milestone, and separately
surfaced to an Org Admin/Founder viewing a single organization's own billing page):
active users (count of `iam.users` with `organization_id = X`, `status = active`), MAU (count of
those with `last_login_at` within a trailing 30-day window — the only activity timestamp that
already exists on `User`, no new tracking column needed), active devices (`fleet_device` count),
active vehicles (`fleet_device` count). These are computed on demand, not persisted/snapshotted —
no document specifies a retention/snapshot requirement, and computing on demand avoids inventing
one.

## Consequences
- Any org previously modeled as `PARENT_PAYS` (none exist in this pre-production database) would
  need to be manually reassigned — acceptable, this environment has no production data.
- `SubscriptionAccessPolicy` becomes strictly simpler: one input fewer, one branch fewer.
- `TransportFee` (student-level, org-billed, "separate from subscription" per its own module
  docstring) is **unaffected** — it was never part of the parent-subscription path; the new
  model's "RAAD does not care how schools collect from parents" is precisely `TransportFee`'s
  existing job (an organization's own internal parent-facing fee, RAAD has no side of it beyond
  today's already-flagged "no documented API surface" posture).
- Usage-based *pricing* (a formula from these metrics to a price) remains explicitly out of
  scope pending a documented formula — tracked as a real, open gap below, not silently resolved.

## Verification
- Unit: a regression test proving `Subscription.open`/equivalent can no longer be constructed
  with a parent subscriber (the type/field no longer exists — a compile-time/import-time
  guarantee, not just an unreachable runtime branch).
- Unit: `SubscriptionAccessPolicyTests` updated to reflect the single-branch decision.
- `alembic upgrade head` / `downgrade -1` / `upgrade head` round-tripped clean; `alembic check`
  reports no drift.
- Full existing billing/tracking/video unit + architecture suite re-run.

## Open Gap (tracked, not resolved here)
No document gives a usage-based pricing *formula*. If/when RAAD wants price to vary by MAU/
active-devices/active-vehicles, that requires its own documented decision (a Database Design
update to `plans`, e.g. tiered pricing columns) before implementation — this ADR only tracks and
exposes the underlying metrics.

## References
- `docs/business/RAAD_Phase3.2_Database_Design_v1.md` §4.2 (`organizations.billing_model`), §8.1
  (`plans`), §8.2 (`subscriptions`)
- `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md` §5.4 (`SubscriptionAccessPolicy`, CR-1)
- `docs/architecture/adr/0006-d4-cr1-safety-over-billing-reconciliation.md` (amended by this ADR)
- `.claude/rules/workflow.md` #7, #8
- `raad/modules/billing/domain/entities.py`, `value_objects.py`
- `raad/modules/organization/domain/value_objects.py` (`BillingModel`)
- `raad/core/policies/subscription_access.py`
