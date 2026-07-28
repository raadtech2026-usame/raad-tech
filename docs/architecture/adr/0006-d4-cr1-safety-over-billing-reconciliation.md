# ADR-0006: D4/CR-1 Reconciliation (Safety-Over-Billing for Live Tracking)

## Status
Accepted. Implemented and verified (Backend Stabilization phase). Resolves Critical finding #1
(CR-1/D5 policies existed as pure decision objects since Phase 14 but were never invoked
anywhere) together with a real, previously-flagged documentation conflict `tracking.domain.
policies`'s own module docstring already surfaced but left unresolved.

## Context
Two approved documents give materially different precedence rules for the same scenario — a
Parent viewing their child's live GPS position during an active trip, where the parent's
subscription has lapsed:

- **D4** (Phase 2 §9.6/§23.2, "safety-over-billing"): parent live-GPS during an active trip is
  *"never revoked by subscription lapse."* Safety capabilities are billing-independent, full
  stop.
- **CR-1** (Backend LLD §5.4, `SubscriptionAccessPolicy`'s own governing business rule): the
  policy's three documented inputs (`assignment_state`, `billing_model`, `subscription_state`)
  are evaluated as one combined gate, and LLD §5.4's own text says CR-1 *"supersedes"* D4 for
  Parent access generally.

Two firm, already-approved rule-file statements — not themselves flagged as open questions —
resolve this the same direction as D4: `.claude/rules/security.md` #6 (*"Safety capabilities are
never billing-gated. Subscription lapse restricts premium/convenience features only — enforced
by one policy object, tested explicitly"*) and `.claude/rules/backend.md` #6 (identical wording).
Both are derivations from the same Phase 2 source D4 itself cites, carrying D4's precedence
forward into this codebase's own binding rules rather than reopening it.

## Decision
`resolve_cr1_decision` (`interfaces/http/policy_guards.py`) evaluates `SubscriptionAccessPolicy`
with a `safety_override: bool` parameter:

- The `assignment_state` gate (CR-1's own highest-precedence business rule) **always applies,
  unchanged** — an inactive/removed/graduated/disabled `StudentAssignment` denies access
  regardless of `safety_override`. This is an eligibility question ("is this still your child's
  active ride"), not a billing one, and D4 never claims otherwise.
- The `subscription_state` gate is **skipped (treated as granting)** only when `safety_override=
  True` — which the caller sets to exactly `is_trip_active` (the trip the requested vehicle
  position belongs to is currently `in_progress`). This is D4's own literal protected scenario:
  *live* position, *during* an active trip.
- `safety_override` is **never** `True` for trip history (`GET /tracking/trips/{id}/positions`) —
  `.claude/rules/flutter.md` #4 (*"Parent live GPS is active-trip-only. Outside active trips, show
  history... only — never a stale/misleading 'live' indicator"*) implies history is not the
  scenario D4 protects; it stays fully CR-1-gated including the subscription check, matching
  CR-1's own literal precedence for every case D4 doesn't specifically carve out.

`TrackingVisibilityPolicy` (`.claude/rules/security.md` #4's four-dimension predicate —
`has_capability ∧ within_scope ∧ has_ownership ∧ within_time_window`) is wired as the actual
enforcement point on both tracking routes, composing: `has_capability`/`within_scope` from RBAC
(ADR-0004, already run by `require_permission` before this executes) + `ScopeResolver`
(ADR-0005); `has_ownership`/`within_time_window` from the CR-1 decision above (Parent callers,
`safety_override=is_trip_active`) or unconditional grant (Org Admin/RAAD staff, API Contracts
§3.2: "Org Admin 24/7"). `VideoAccessPolicy` (D5) is wired identically at `video`'s three routes
via `enforce_d5`, with no CR-1/D4 interaction at all — D5 has no safety-override case; video is
Org-Admin-only by construction, unconditionally, per `.claude/rules/jt1078.md` #1.

## Consequences
- A parent whose subscription is fully expired can still see their child's **live** dot on the
  map during an active trip, but the moment the trip ends, `GET .../positions` history is
  CR-1-gated normally (denied if the assignment is inactive, or — for `PARENT_PAYS` orgs — if the
  subscription itself is not in a granting state).
- This is the one place in `transport_ops`/`tracking`'s combined surface where a policy input
  (`safety_override`) is caller-supplied rather than purely repository-derived — flagged in
  `policy_guards.py`'s own docstring as the resolution mechanism, not left implicit.

## Verification
- `interfaces/http/policy_guards.py`'s `resolve_cr1_decision`/`resolve_tracking_decision`
  docstrings carry this same reasoning inline, so the enforcement code and this ADR cannot drift
  silently apart.
- `tracking.api.routers`: `GET /vehicles/{id}/latest` passes `is_trip_active` (derived from the
  position's own `trip_id` and that trip's `status`); `GET /trips/{id}/positions` passes `False`
  unconditionally (history is never the live-safety-override case) — both call sites verified by
  reading the router source, matching this ADR's decision exactly.
- Full existing unit/architecture suite (802 tests / 10 gates at the time) continued passing
  after both tracking routes were rewritten to call this policy chain.

## References
- `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §9.6, §23.2 (D4)
- `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md` §5.4 (CR-1, `SubscriptionAccessPolicy`)
- `.claude/rules/security.md` #4, #6
- `.claude/rules/backend.md` #6
- `.claude/rules/flutter.md` #4
- `raad/core/policies/subscription_access.py`, `raad/modules/tracking/domain/policies.py`
  (`TrackingVisibilityPolicy`), `raad/interfaces/http/policy_guards.py`,
  `raad/modules/tracking/api/routers.py` (implementation)

## Amendment (2026-07-28): `billing_model` input removed (Organization-Only Billing)

**Status:** Accepted (direct user decision, RAAD business model realignment). Superseding this
ADR's `billing_model`-conditioned branch only — D4's own precedence rule (safety-over-billing
during an active trip, `safety_override=is_trip_active`) and the `assignment_state` gate are
unchanged.

### Context
**ADR-0016** (Organization-Only Billing Model) deletes `PARENT_PAYS`/`Organization.billing_model`
entirely — RAAD bills organizations only. This ADR's original Decision described
`SubscriptionAccessPolicy`'s `subscription_state` gate as conditioned on `billing_model`
(skipped for `ORGANIZATION_PAYS`, evaluated for `PARENT_PAYS`). With only one billing model left,
that conditioning has nothing left to condition on.

### Decision
`SubscriptionAccessPolicy` drops the `billing_model` input entirely. `subscription_state` is now
evaluated as a single, unconditional check against the **organization's own subscription** (never
a parent-owned one — that concept no longer exists per ADR-0016). The `safety_override`
mechanism this ADR already established is otherwise untouched: `assignment_state` still always
applies; `subscription_state` is still skipped (treated as granting) exactly when
`safety_override=True` (live position during an active trip). D5/`VideoAccessPolicy` is
unaffected — it never had a `billing_model` input.

### Consequences
- `SubscriptionAccessPolicy`'s signature loses one parameter; every call site
  (`interfaces/http/policy_guards.py`) simplifies correspondingly — no behavioral change to the
  `assignment_state`/`safety_override` reasoning this ADR's original Decision already recorded.
- No re-litigation of D4 vs CR-1 precedence is needed — that reconciliation stands exactly as
  originally decided; only the now-dead `billing_model` branch is removed.

### Verification
- `tests/unit/test_policy_guards.py`/`SubscriptionAccessPolicyTests` updated to the
  single-branch signature; existing `assignment_state`/`safety_override` test cases must
  continue passing unchanged.

### References (amendment)
- `docs/architecture/adr/0016-organization-only-billing-model.md`
