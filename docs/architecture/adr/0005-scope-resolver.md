# ADR-0005: `ScopeResolver` (Region/Support Assignment Tables)

## Status
Accepted. Implemented and verified (Backend Stabilization phase). Resolves High finding #3's
prerequisite (`interfaces/http/deps.get_scope` had no real `ScopeResolver` bound) and unblocks
`TrackingVisibilityPolicy`'s `within_scope` input (ADR-0006 depends on this).

## Context
Phase 2 §17.4 defines `effective_org_scope(principal) -> TenantRegionScope` precisely: Founder is
unrestricted; Regional Manager gets every organization in their assigned regions; Support Staff
(and, per this ADR, Finance Staff) get their directly-assigned organizations; every tenant role
(Org Admin, Driver, Parent) is scoped to their own single `organization_id`. `core.tenancy.
resolver.ScopeResolver` (the interface) and `core.tenancy.scope.TenantRegionScope` (the resolved
value) already existed as pure types with no implementation — `interfaces/http/deps.get_scope`
called `container.resolve(ScopeResolver)` against a binding that was never made, so every route
depending on scope failed loudly (`LookupError`) by the same "fail loudly, don't fake" convention
`require_permission` used before ADR-0004.

No document specifies the actual assignment mechanism (which table records "Regional Manager X is
assigned to Region Y") — Database Design's module list mentions the *concept* (region/org scope)
without naming the tables. This gap needed a decision, not just an implementation.

## Decision
Two new tables, both owned by `organization` (the module that already owns `Organization`/
`Region`, the entities being scoped over): `region_assignments` (user_id, region_id) and
`support_assignments` (user_id, organization_id) — both composite-PK, in-context FK to
`regions`/`organizations` respectively. `organization.infra.adapters.OrganizationScopeResolver`
implements the four-branch formula exactly as Phase 2 §17.4 states it, reading these two tables
plus the principal's own `role`/`org_id`.

**Finance Staff reuses `support_assignments` — a deliberate, flagged minimal-invention choice.**
No document names a distinct assignment mechanism for Finance Staff's "explicitly granted" ops
scope (API Contracts §3.2's capability table lists Finance Staff with `✅ own org` for
billing-scope rows, structurally identical to Support Staff's own-assigned-orgs shape). Inventing
a third table for an undifferentiated case would be schema no document justifies; reusing the one
already-documented "directly assigned organizations" table for both roles is the smaller,
reversible choice — if a future document distinguishes them, splitting the table later is a
straightforward additive migration, not a redesign.

## Consequences
- Granting/revoking region/support assignments has no HTTP route yet (same "use-case exists, no
  approved endpoint yet" posture as ADR-0004's matrix-editing gap) — `ScopeAssignmentApplicationService`
  is reachable at the application layer only.
- `OrganizationScopeResolver` resolves a fresh `OrganizationUnitOfWork` per call, same
  no-caching-yet posture and same future-revisit condition as ADR-0004's `IamPermissionEvaluator`.
- Every module's own `list_all()` repository method still applies an **unrestricted**
  `TenantRegionScope(organization_ids=None)` internally (a system-wide, already-flagged gap
  predating this ADR, documented in each module's own `infra/repositories.py` docstring) — this
  ADR makes real scope resolution *available* at the HTTP dependency layer
  (`interfaces/http/deps.get_scope`, and the CR-1/D5/tracking policy-guard call sites that use it
  directly), but does not retrofit every existing list endpoint to actually filter by it. That
  retrofit is a separate, larger, cross-cutting change explicitly out of this phase's "prefer
  minimal changes over large redesigns" scope.

## Verification
- Migration `054a850353e7` creates both tables; applied, round-tripped, zero `alembic check`
  drift.
- `tests/integration/test_rbac_and_scope_resolver.py`'s `OrganizationScopeResolverRoundTripTests`:
  Founder unrestricted, tenant own-org-only, Regional Manager region-derived, Support Staff
  directly-assigned, empty-grants case.
- `interfaces/http/policy_guards.resolve_tracking_decision`/`resolve_d5_decision` (ADR-0006,
  the `video`/`tracking` D5/CR-1 enforcement points) both consume this resolver directly, proving
  it composes correctly with the policy layer it was built to unblock.

## References
- `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §17.3/§17.4
- `docs/business/RAAD_Phase3.3_API_Contracts_v1.md` §3.2 (role-capability matrix)
- `.claude/rules/security.md` #2, #3 (tenant isolation defense-in-depth; region scoping as a
  second filter for RAAD staff)
- `raad/modules/organization/infra/adapters.py`, `raad/interfaces/http/deps.py`
  (implementation)
