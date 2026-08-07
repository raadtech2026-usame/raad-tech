# ADR-0023: Canonical `/me` Self-Service Identity Resolution

## Status
Accepted (direct user decision, 2026-08-07 — closes `PROJECT_STATUS.md` Known Issue #17).

## Context

Known Issue #17 (`docs/PROJECT_STATUS.md` §10) identified that neither mobile-facing role has a
safe way to resolve its own domain identity from an authenticated `Principal`:

- **Parent**: `GET /parents/{parent_id}/students` (`transport_ops/api/routers.py`) requires
  `transport_ops.student_parents.list` — a permission the seeded RBAC matrix grants to
  `founder`/`regional_manager`/`support_staff`/`org_admin`, never to `parent`. Even if granted,
  the route takes `parent_id` straight from the URL path with **no ownership check at all**
  comparing it to the caller's own linked `Parent.user_id` — granting the permission alone would
  let any parent pass any other parent's `parent_id` and see their children, the same class of
  cross-tenant leak ADR-0021's audit already fixed at the organization level.
- **Driver**: `driver` holds `transport_ops.trips.list`/`.read`/`.start`/`.end` — server-side
  ownership on start/end is already correctly enforced (`_ensure_driver_owns_trip`) — but there
  is no endpoint a `driver` principal can reach to learn its own `Driver.id` at all, so a mobile
  client can only list every trip in the organization, never filter to "assigned to me" even
  though `GET /trips?filter[driver_id]=...` already supports exactly that filter server-side.

Both gaps share one root cause: `core.tenancy.principal.Principal` (`user_id`, `role`, `org_id`)
is `iam`'s own identity concept, but the *domain* identity a client actually needs
(`Parent.id`/`Driver.id`) lives in `transport_ops`, keyed by `Parent.user_id`/`Driver.user_id`
— a cross-module reference only, per `.claude/rules/database.md` #3. No existing route resolves
one from the other safely. `GET /auth/me` (`iam/api/routers.py:326`) already exists but only
returns the raw `iam.User` row — it was never meant to, and does not, reach into `transport_ops`.

Per `.claude/rules/workflow.md` #8, this needs a design decision before implementation, not an
invented fix under time pressure inside a mobile-app task — this ADR is that decision, at the
user's explicit direction to build "a single canonical self-service identity API rather than
isolated endpoints."

## Decision

### 1. One canonical capability, not two unrelated endpoints
`GET /me` resolves the caller's own cross-module identity in one place — role, organization
scope, and whichever domain-specific id(s) apply to that role — so `/me/students` and
`/me/driver-profile` become thin, dedicated views built on the same resolution the root endpoint
already performs, not independent one-off lookups each reinventing "how do I find my own
`Parent`/`Driver` row."

**Response shape** (`MeIdentityResponse`, new — `iam/api/schemas.py`):
```
user_id: str
role: str
organization_id: str | None
parent_id: str | None   # populated only when role == PARENT and a Parent row resolves
driver_id: str | None   # populated only when role == DRIVER and a Driver row resolves
```
**Org Admin (and every RAAD-staff role) needs no separate lookup** — `organization_id` is
already present on `Principal` directly (`core.tenancy.principal.Principal.org_id`), and neither
`Founder`/`Regional Manager`/`Support Staff`/`Finance Staff`/`Org Admin` has a second aggregate
distinct from `iam.User` the way Parent/Driver do. This is closed by construction, not omitted —
flagged here rather than silently assumed, since the user's own request named "Org Admin, etc."
explicitly.

### 2. Ownership: `iam`, composing `transport_ops`'s own application services
`iam` already owns `Principal`/`User` and the existing `/auth/me` "current identity" endpoint —
the natural conceptual home for "who am I, across the whole platform," not just within one
module. A new `MeApplicationService` (`iam/application/services.py`) is constructor-injected
with `transport_ops`'s `ParentApplicationService`, `DriverApplicationService`, and
`StudentParentApplicationService` — exactly the pattern ADR-0020's `PlatformStatsApplicationService`
already established for legal cross-module composition (`.claude/rules/backend.md` #1/#3):
compose via the owning module's own **application-layer** methods, never that module's
`domain`/`infra`. `tests/architecture/test_module_boundaries.py` Rule 1 enforces this
mechanically (flags any `iam` import of `transport_ops.domain`/`transport_ops.infra`; an
`iam.application` import of `transport_ops.application.*` is explicitly legal and unflagged) —
re-run after implementation to confirm, not just asserted clean by construction.

`MeApplicationService` needs **no `IamUnitOfWork` at all** — `Principal` already carries
`user_id`/`role`/`org_id` directly from the verified JWT, no DB round-trip required for the base
fields. Its methods take only a `TransportOpsUnitOfWork` per call, resolved via the module's own
existing, already-scoped `get_transport_ops_uow` (mirrors `platform_audit.api.routers`'s existing
precedent of importing another module's `api/deps.py` function directly, per §3.3 of the research
behind this ADR).

**Two small, additive mirror-methods are needed first**, both already precedented 1:1 by an
existing sibling method:
- `DriverRepository.get_by_user_id` (domain interface) + `SqlAlchemyDriverRepository.get_by_user_id`
  (infra) — `ParentRepository.get_by_user_id`/`SqlAlchemyParentRepository.get_by_user_id`
  already exist and are mirrored exactly (same non-unique `user_id` filter shape, same
  `deleted_at IS NULL` scoping).
- `DriverApplicationService.get_driver_by_user_id` — mirrors
  `ParentApplicationService.get_parent_by_user_id` exactly (returns `DriverDTO | None`, never
  raises for "no Driver profile," since that is an expected, non-exceptional outcome for a
  non-driver caller).

`/me/students` reuses `StudentParentApplicationService.list_students_for_parent` **unchanged** —
`MeApplicationService` resolves `parent_id` server-side first (via `get_parent_by_user_id`), then
calls the existing, already-tested query with that resolved id. The existing
`GET /parents/{parent_id}/students` route is **left exactly as-is** — still gated by
`transport_ops.student_parents.list`, still unreachable by `parent`/`driver` roles today, so this
change introduces no new exposure on that route. Fixing its own missing ownership check is
explicitly **out of scope** for this ADR (flagged, not silently left implied-fixed) — it remains
usable only by roles that can already see any organization's data by design (RAAD staff, Org
Admin), a materially different risk than a `parent`-role caller reaching it.

### 3. Routes: a new top-level `/me` prefix, owned by `iam`, no documented API Contracts row
`GET /me`, `GET /me/students`, `GET /me/driver-profile` — a new `me_router`
(`iam/api/routers.py`), mounted at `/api/v1/me` in `interfaces/http/api_v1.py`. This does not map
1:1 onto a single existing `.claude/rules/api.md` #2 table row (`/me` isn't listed) — flagged
explicitly, the same "no documented API Contracts surface, built directly on schema authority"
posture already established for `/drivers`, `/roles/{role}/permissions`, `/scope-assignments`,
and `GET /billing/payments`. `iam` is the owning module (§2 above); the sub-resources reach
`transport_ops` only through its application-layer facade, never its tables.

### 4. Ownership enforced server-side only — no client-supplied `parent_id`/`driver_id`, anywhere
Every method `MeApplicationService` exposes takes a `Principal` (or its bare `user_id`) as its
**only** identity input — never a path parameter, query parameter, or request body field naming
a `parent_id`/`driver_id`. This isn't a runtime check to bypass; it's structural: the new
endpoints' route signatures have no such parameter to accept in the first place, so there is
nothing for a malicious caller to override. This directly closes the class of bug Known Issue
#17 described in `GET /parents/{parent_id}/students` (a path-supplied id with no ownership
check) by construction, not by adding a comparison after the fact.

### 5. Authorization: self-scoping, not RBAC — matching `GET /auth/me`'s existing posture
Confirmed against every RBAC migration in the chain: `parent`/`driver` hold **no**
`transport_ops.parents.*`/`.drivers.*`/`.students.*`/`.student_parents.*` permission today, and
granting one deliberately (per §2's own "insufficient without an ownership check" finding) is not
this ADR's approach. `/me`, `/me/students`, `/me/driver-profile` are gated by
`Depends(get_current_user)` alone — **no** `require_permission(...)` check — mirroring
`GET /auth/me`/`GET /auth/sessions`/`POST /auth/change-password`'s identical existing "self-scoped
by construction, no RBAC grant needed" posture. This is safe specifically because every response
is derived from `principal.user_id` alone: no permission grant could make this endpoint return
anyone else's data even if one existed. **No RBAC migration is needed.**

### 6. 404-over-403 when no linked domain record resolves
`/me/students` and `/me/driver-profile` raise the existing `NotFoundError` (`core/errors/
exceptions.py`, code `NOT_FOUND`, 404) when `get_parent_by_user_id`/`get_driver_by_user_id`
resolves to `None` — covering both "this role has no such profile" (e.g. an Org Admin calling
`/me/driver-profile`) and "a role that should have one doesn't, due to a data inconsistency" with
one honest code path, rather than special-casing on `principal.role` first. This mirrors this
codebase's already-established "never confirm/deny existence with a distinct 403" pattern
(`GET /notifications/{id}`'s non-owner 404, Backend LLD §14.3's own reasoning generalized). `/me`
itself never 404s — it always returns 200 with `parent_id`/`driver_id` simply left `null` when
not applicable, since the root identity (`user_id`/`role`/`organization_id`) is always resolvable
from a valid, already-authenticated `Principal`.

### 7. Migration: none
Zero schema change (`Parent.user_id`/`Driver.user_id` columns already exist), zero RBAC grant
(§5). Purely new application/API-layer code plus two small, additive repository methods.

## Consequences
- `iam.application.services` gains a new import of `transport_ops.application.services`/
  `transport_ops.application.queries` — legal under Rule 1, verified by re-running
  `tests/architecture/test_module_boundaries.py` after implementation.
- `DriverRepository`/`SqlAlchemyDriverRepository` gain one new method each, mirroring
  `ParentRepository`'s existing shape exactly — no behavior change to any existing method.
- Mobile (`mobile/lib/features/parent/parent_home_screen.dart`) can now be wired to a real
  "my children" list and a real driver-side "my trips" filter — **not done as part of this ADR**;
  the mobile app has no Flutter SDK in this environment to verify any change against
  (`PROJECT_STATUS.md`'s already-disclosed Mobile testing limitation), so wiring the client is
  left as a follow-up, tracked in `PROJECT_STATUS.md`, not silently implied done here.
- `GET /parents/{parent_id}/students`'s own pre-existing missing-ownership-check gap is
  unchanged by this ADR — still tracked, still only reachable by roles that can already see
  cross-organization data by design.

## Verification
- Unit: `MeApplicationService`, fakes for `ParentApplicationService`/`DriverApplicationService`/
  `StudentParentApplicationService` (plain constructor-argument fakes, mirroring
  `tests/unit/test_platform_stats_application.py`'s pattern) — asserts the *only* `parent_id`/
  `driver_id` ever passed downstream is the one resolved from the given `Principal.user_id`, for
  every role, including the 404 paths.
- Integration (live Postgres): a new `SqlAlchemyDriverRepository.get_by_user_id` round-trip test
  (mirrors `test_transport_ops_parent_repository.py`), plus a two-parent isolation test proving
  `MeApplicationService.get_my_students` for Parent A never returns Parent B's students — the
  actual security regression proof this ADR exists to establish.
- `tests/architecture/test_module_boundaries.py` and `tests/architecture/
  test_api_layer_boundaries.py` re-run clean.

## References
- `docs/PROJECT_STATUS.md` §10 Known Issue #17 (the gap this ADR closes)
- `.claude/rules/workflow.md` #8 (design before implementation)
- `.claude/rules/backend.md` #1, #3 (module facade, no cross-module DB reads)
- `.claude/rules/security.md` #2 (defense-in-depth: repository-layer tenant scope *and*
  authorization-layer ownership, never only one — `/me`'s server-side-only id resolution is the
  authorization half; `get_transport_ops_uow`'s existing `TenantRegionScope` is the repository half)
- `docs/architecture/adr/0020-platform-analytics-read-model.md` (the cross-module composed
  application-service precedent this ADR mirrors)
- `docs/architecture/adr/0021-tenant-scope-enforcement-at-repository-layer.md` (the same family
  of ownership-check gap, previously fixed at the organization level)
- `raad/interfaces/http/policy_guards.py` (`_resolve_parent_id` — the existing, narrower
  Principal→Parent resolution this ADR generalizes into a reusable, response-returning capability)
