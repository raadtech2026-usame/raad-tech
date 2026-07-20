# ADR-0004: RBAC Permission Matrix (Data-Driven `role_permissions`)

## Status
Accepted. Implemented and verified (Backend Stabilization phase). Resolves Critical finding #2
of the pre-production architecture review: `require_permission` unconditionally raised
`NotImplementedError`, so every business route 500'd regardless of caller.

## Context
`core/security/permissions.py`'s own module docstring, since Phase 17, explicitly deferred the
permission matrix: *"the concrete **matrix** (which permissions each role holds) is deliberately
not defined here — it is authorization *business data* that isn't in the approved documentation
yet."* `interfaces/http/deps.require_permission` accordingly always raised, by design, as a
"fail loudly, don't fake" placeholder — every route in every completed module already called
`require_permission(Permission("..."))`, so once a real `PermissionEvaluator` existed, every
route would resolve for real with no router-level code changes needed anywhere.

Database Design §4.4 turns out to already specify the missing piece: `roles`, `permissions`, and
`role_permissions` as real, seedable database tables, *"editable by Founder... without code
change."* This is authorization business data with an approved schema — the review's finding was
that no implementation existed to read it, not that the schema itself was undecided.

## Decision
Build `role_permissions` (composite PK `(role, permission)`) as a real, migrated table, seeded
with the full role × permission matrix, and bind a `PermissionEvaluator` implementation
(`iam.infra.adapters.IamPermissionEvaluator`) that queries it.

**Scoped down from Database Design §4.4's full three-table design — deliberately, not an
oversight.** `roles`/`permissions` (label-metadata tables: human-readable names, descriptions)
are not built; `Role` stays the existing fixed Python enum (`core.tenancy.principal.Role`), and
`permissions` themselves stay implicit — a `role_permissions` row's `permission` column is the
same `Permission = NewType("Permission", str)` string every route already passes to
`require_permission`. Building the two label tables with no consumer (no admin UI reads them,
no approved document names an endpoint that would) would be unused, premature schema — the same
"don't invent it" discipline this phase's own instructions state explicitly. `role_permissions`
alone is sufficient for `require_permission`'s actual need: "does this role hold this permission
string?"

**Seed matrix derivation — grounded, not invented.** Every one of the ~66 `require_permission(
Permission("..."))` call sites already in this codebase (across all eight modules with routes)
was enumerated by exhaustive grep, cross-referenced against API Contracts §3.2's own documented
role-capability table, to produce the seeded grant set per role. No permission string was
invented that isn't already a real, already-written call site's own literal argument.

## Consequences
- Editing the matrix at runtime (Database Design §4.4's "editable by Founder... without code
  change") requires `PermissionApplicationService.grant`/`revoke` to be exposed via an HTTP
  route — no such route is documented in API Contracts today, so this capability is reachable at
  the application layer only this phase, the same "use-case exists, no approved endpoint yet"
  posture already established elsewhere in this codebase (e.g. `Route.remove_stop`).
- `IamPermissionEvaluator` resolves a fresh `IamUnitOfWork` (hence a fresh DB round-trip) on
  every `has_permission` call — no caching layer exists yet. Acceptable for this phase (no
  documented latency budget for authorization checks); a future phase may cache the matrix in
  Redis once that infrastructure exists, revisiting this only if measured load justifies it
  (`.claude/rules/architecture.md` #7: "no premature microservices... driven by measured load").

## Verification
- Migration `5437a5d1651b` creates `role_permissions` and seeds it (Founder=70, Regional
  Manager=26, Support Staff=28, Finance Staff=10, Org Admin=61, Driver=9, Parent=12 distinct
  permission strings); applied, round-tripped, zero `alembic check` drift.
- `tests/integration/test_rbac_and_scope_resolver.py`'s `IamPermissionEvaluatorRoundTripTests`:
  seeded-matrix grants/denials against real routes' own permission strings, grant/revoke round
  trip.
- Full existing unit suite (802 tests at the time) continued passing — no route's own code
  changed, only `require_permission`'s previously-always-failing resolution now succeeds/denies
  correctly per the seeded matrix.

## References
- `docs/business/RAAD_Phase3.2_Database_Design_v1.md` §4.4
- `docs/business/RAAD_Phase3.3_API_Contracts_v1.md` §3.2 (role-capability matrix, the seed
  matrix's source)
- `.claude/rules/security.md` #1 ("least privilege by default... every role's permission set is
  explicit")
- `raad/modules/iam/infra/adapters.py`, `raad/interfaces/http/deps.py` (implementation)
