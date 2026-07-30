# ADR-0021: Tenant Scope Enforcement at the Repository Layer

## Status
Accepted (direct user decision — tenant isolation security audit & fix, 2026-07-30).

## Context
Live verification during the previous phase (ADR-0017 amendment / onboarding gap closure)
reproduced a real, confirmed cross-tenant data leak: a brand-new Org Admin's `GET /vehicles`
returned other organizations' vehicles. A full audit (four parallel investigations covering
every bounded context, every layer, background jobs, both WebSocket channels, and the frontend)
found the same root cause present system-wide, already self-documented in this codebase's own
"Known gaps" section as "a separate, larger, cross-cutting change" — this ADR is that change.

**The root cause, confirmed once, present everywhere except `tracking`/`video`/`notifications`/
`reporting`:** `SqlAlchemyRepositoryBase` (`backend/raad/core/db/repository.py`) has two
relevant methods:
- `list_page`/`list_all`/`list_cursor_page` **correctly** apply a `TenantRegionScope` filter
  when given one — but every concrete repository in every affected module calls them with a
  hardcoded `TenantRegionScope(organization_ids=None)` (unrestricted), never the caller's real
  scope.
- `get_by_id` (the single-resource fetch every module's `get(id)` delegates to) has **no scope
  parameter and no organization filter at all** — a bare `WHERE id = :id`. Since every `PATCH`/
  status-transition/lifecycle route loads its aggregate via this same `get()` before mutating,
  this is a read **and write** IDOR (Insecure Direct Object Reference), not only a list leak.

The correct mechanism already exists and is proven correct in production: `ScopeResolver.
effective_org_scope(principal)` (`core/tenancy/resolver.py`, concrete `OrganizationScopeResolver`
in `organization/infra/adapters.py`) resolves a `TenantRegionScope`
(`core/tenancy/scope.py`) — `organization_ids: frozenset[str] | None`, `None` meaning
unrestricted (Founder), otherwise the caller's real allow-set (Regional Manager's assigned
regions' orgs, Support Staff's assigned orgs, a tenant role's own single org). A FastAPI
dependency, `get_scope` (`interfaces/http/deps.py:69-76`), already resolves this per-request.
`tracking` (`interfaces/http/policy_guards.py`'s `resolve_tracking_decision`) and `video`
(`enforce_d5`) already use exactly this mechanism correctly — independently re-verified during
the audit, not just asserted. Every other module simply never wires it in, despite
`.claude/rules/backend.md` #4 already mandating: "Tenant context is resolved once at the edge
... and injected into every repository query automatically — never rely on a call site
remembering to filter by `organization_id`."

Full per-module audit findings (list-leak + get/update/delete IDOR + any module-specific
bridging bugs) are recorded in the security report accompanying this ADR's implementation, not
duplicated here.

## Decision

**Inject `TenantRegionScope` once, at Unit-of-Work construction, so every repository applies it
automatically — not by threading an explicit `scope` parameter through every application-service
call site.** This is the literal shape `.claude/rules/backend.md` #4 already mandates, and it
collapses an entire class of "a call site forgot to pass scope" bugs into a single, narrow,
reviewable choke point.

1. `SqlAlchemyRepositoryBase.__init__` gains `scope: TenantRegionScope | None = None`, stored as
   `self._scope`, defaulting to unrestricted when omitted — a safe default for CLI scripts,
   background workers, and tests that construct repositories directly, outside an HTTP request
   (these are system-level contexts that legitimately need unrestricted access, matching their
   current behavior exactly; only HTTP request contexts get newly restricted).
2. `get_by_id`, `list_scoped`, `list_page`, `list_cursor_page` drop their explicit `scope`
   parameter and read `self._scope` instead. `get_by_id` gains the identical
   `organization_id.in_(scope.organization_ids)` predicate the list methods already apply when
   the model has that column — a resource outside the caller's scope now simply doesn't exist
   from that caller's point of view (`None`, not a permission error).
3. **This one change makes every existing `_get_x_or_raise`-shaped helper in every module
   automatically correct, with no business-logic changes.** They already do `if x is None: raise
   NotFoundError(...)`. This is deliberate — 404-over-403 (never confirm existence of another
   organization's data via an explicit 403), the exact posture `notifications`/`reporting`
   already established for personal-ownership scoping, generalized here to organization scoping.
4. A repository whose model **is** the tenant root (`Organization`) needs the inverse predicate
   (`model.id.in_(scope.organization_ids)`, not `model.organization_id...`) — a `scope_by_own_id:
   bool = False` class flag on the base, set `True` only on `SqlAlchemyOrganizationRepository`.
5. Each module's `SqlAlchemy<Module>UnitOfWork.__aenter__` (which already constructs repositories
   fresh per request) passes `self.scope` into each repository's constructor.
6. Each module's `get_<module>_uow` FastAPI dependency gains `scope: TenantRegionScope =
   Depends(get_scope)` and sets it on the resolved-but-not-yet-entered UoW instance before
   returning it. Confirmed safe: every `get_<module>_uow` today returns the UoW **un-entered**
   (`container.resolve(XUnitOfWork)`, no `async with`) — each application-service method opens
   its own `async with uow:` block internally, which is where repositories actually get
   constructed (`__aenter__`). Setting `.scope` at the dependency-function boundary, before that
   later `__aenter__` call, is therefore sufficient and doesn't double-enter anything.
7. **Client-supplied `organization_id` on create commands** (`Trip.schedule`,
   `StudentAssignment.assign`, `StudentParent.link`, and any future one): for a tenant-scoped
   caller (`org_admin`/`driver`/`parent`), the command's `organization_id` must equal
   `principal.org_id` — reusing the exact shape `iam`'s existing `_enforce_creation_scope`
   (`iam/application/services.py`) already established for user creation, not a new pattern.
   This closes a distinct gap the audit found: these three flows validate that the *referenced
   aggregates* are mutually consistent with each other and with a client-supplied
   `organization_id` field, but never validate that field against the authenticated caller's own
   organization — internally consistent, not caller-owned.
8. **`fleet_device.assign_device_to_vehicle`/`reassign_device`**: add an explicit
   `device.organization_id == vehicle.organization_id` domain-level invariant, independent of
   caller scope — a device bound to a vehicle in a different organization is nonsensical
   regardless of who is asking, not solely a security question.
9. **`StudentParent`** (the student↔parent link table) doesn't extend
   `SqlAlchemyRepositoryBase` (composite primary key, no base-class hook) — its `list_by_student`/
   `list_by_parent` finders get an explicit organization filter; `link`/`unlink` already load the
   Student/Parent through their own (now-scoped) repositories first, so they inherit the fix once
   items 1-3 land for `Student`/`Parent` — verified at implementation time, not assumed.
10. **Filter-whitelist safety**: `Vehicle`/`Device` already whitelist `organization_id` as a
    client-facing filter field. Once the base query carries the scope predicate, SQLAlchemy
    composes `.where()` calls as `AND` — a client-supplied `filter[organization_id]=<other-org>`
    naturally intersects with the scope filter and returns zero rows, not a bypass. Verified by
    construction; also covered by an explicit regression test rather than left to reasoning
    alone.
11. **Error semantics**: single-resource access outside scope → `NotFoundError` (HTTP 404). List
    endpoints return fewer/no rows with no new error path. No route in scope for this ADR uses a
    403 for this specific failure mode — that stays reserved for `tracking`/`video`'s own
    deliberately-explicit, safety-motivated denial responses (`PARENT_ACCESS_DENIED`,
    `VIDEO_FORBIDDEN`), which are a different, already-approved UX decision this ADR does not
    revisit.

## Consequences
- Every module's `api/deps.py` (`get_<module>_uow`), `infra/repositories.py` (constructor +
  `list_page`/`list_all`/`get`/`list_cursor_page` call sites), and `infra/repositories.py`'s
  `SqlAlchemy<Module>UnitOfWork.__aenter__` change — mechanically, module by module, following
  one pattern established once in `core/db/repository.py`/`core/db/unit_of_work.py`.
- No `application/services.py` business-logic changes are needed for the list-leak/get-update-
  delete-IDOR class of bug — it collapses entirely into the repository/UoW/DI layer. The three
  exceptions (item 7's client-supplied `organization_id`, item 8's device/vehicle org match,
  item 9's `StudentParent` bespoke filter) are narrow, targeted, application/domain-layer
  additions, not a rewrite.
- No frontend changes are required for the fix itself — the audit confirmed no frontend code
  anywhere performs client-side organization filtering that masks (or would need to stop
  masking) this gap; the leak was identical in the UI and via direct API calls.
- `Region` scoping is fixed as a natural side effect of fixing `organization`'s repository (same
  module, same mechanism) — it corrects Regional Manager's own assigned-region visibility, not
  the primary Organization-A-vs-Organization-B concern this ADR exists to close.
- `Trip.vehicle_id`/`StudentAssignment.vehicle_id` existence/ownership validation against
  `fleet_device` remains out of scope — an already-documented, already-user-confirmed
  architectural limitation (`.claude/rules/database.md` #3: cross-context references are by ID
  only, no cross-module DB read). This ADR does not reopen that decision; it does reduce its
  practical severity, since `organization_id` on the referencing aggregate is now itself
  caller-derived rather than client-supplied (item 7).

## Verification
- Unit tests for the base-class scope predicate (`core/db/repository.py`).
- Per-module integration tests (live DB, two real organizations) proving: Organization A cannot
  read, modify, delete, or search Organization B's data for every affected resource, and cannot
  reach it by substituting Organization B's ids into a request.
- Live, manual two-organization verification across REST and both WebSocket channels
  (`/ws/tracking`, `/ws/notifications` — the latter already correct, re-verified not re-fixed).
- Full existing backend/frontend suites re-run to confirm no regression.

## References
- `.claude/rules/backend.md` #4 (the already-mandated design this ADR finally implements)
- `.claude/rules/database.md` #2 (multi-tenancy: `organization_id` on every tenant-owned table)
- `.claude/rules/security.md` #2, #4 (tenant isolation as defense-in-depth; the tracking-
  visibility predicate this ADR generalizes the ownership dimension of)
- `raad/interfaces/http/policy_guards.py` (`resolve_tracking_decision`/`enforce_d5` — the
  existing, proven precedent this ADR generalizes rather than reinvents)
- `raad/modules/iam/application/services.py` (`_enforce_creation_scope` — the existing precedent
  item 7 reuses)
- `raad/modules/notifications/application/services.py` (the 404-over-403 precedent item 11
  generalizes)
