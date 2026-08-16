# ADR-0029: Platform Admin Live-Video Access (Founder, Regional Manager, Support Staff)

## Status

**Accepted** (direct user decision, 2026-08-16). Resolves the question ADR-0027's investigation
turn raised and ADR-0028 explicitly deferred ("whether Platform Admin should ever get a real
video capability... deliberately left open... not touched"). Written per
`.claude/rules/workflow.md` #8, mirroring ADR-0026's own precedent for a fully-specified,
user-directed change: accepted directly rather than proposed-then-reviewed, since the user's own
instruction already fixed every design parameter (which roles, reuse constraint, RBAC gap,
excluded roles, verification requirement).

## Context

ADR-0028 (§ Non-goals) deliberately left open "whether Platform Admin roles should ever get a
video capability in the frontend" — nothing in that design proved it was required, so it wasn't
touched. The user now directs exactly that expansion, narrowly: Founder, Regional Manager, and
Support Staff gain the same live-video capability Org Admin already has on the unified
`/platform/tracking` / `/org/tracking` view (ADR-0028), reusing that view's existing
`VideoPlayerPanel`/`CameraPicker`/`useVideoSessionController` unchanged — no second video
component, no new route.

**Verified before touching anything, not assumed:**

1. **D5 (`core.policies.video_access.VideoAccessPolicy`) already lists all three roles as
   eligible.** `_VIDEO_ELIGIBLE_ROLES` has included `FOUNDER`, `REGIONAL_MANAGER`,
   `SUPPORT_STAFF`, and `ORG_ADMIN` since D5 was first wired up (pre-dating this entire
   conversation) — confirmed by reading the policy source directly, not inferred. This ADR
   changes **zero** lines of `VideoAccessPolicy`, `resolve_d5_decision`, or `enforce_d5`.
2. **RBAC (layer 2) had a real, pre-existing gap**, confirmed live against the running
   `role_permissions` table before writing any migration: `founder` held all three `video.*`
   permissions (`_ALL_PERMISSIONS`); `regional_manager`/`support_staff` held
   `video.live.start`/`video.playback.start` but **not** `video.sessions.stop` — a gap already
   flagged twice earlier in this conversation (the original architecture-investigation turn, and
   the manual review before committing ADR-0027). Without closing it, either role could start a
   session but would 403 attempting to stop their own.
3. **Tenant/region scope is unaffected.** `resolve_d5_decision` resolves `org_scope` via the
   same `ScopeResolver` every other route already uses — Founder unrestricted, Regional
   Manager/Support Staff limited to their assigned regions/orgs, unchanged. Confirmed by running
   `OrganizationScopeResolverRoundTripTests` (unchanged, all passing) alongside this change.
4. **The frontend gate is a single boolean** in `LiveTrackingPage.tsx`
   (`isOrgAdmin = principal?.role === "org_admin"`, ADR-0028's own deliberately narrow
   `org_admin`-only presentation gate) — changing it to check the same role set D5 already
   allows is the entire frontend surface of this change; `VideoPlayerPanel`/`CameraPicker`/
   `useVideoSessionController`/`useVehicleActiveDevice` need no changes at all, since none of
   them contain any role logic — they only take a resolved `device_id`/`camera_id`.

## Decision

### 1. RBAC: grant `video.sessions.stop` to `regional_manager` and `support_staff`

Migration `50261534916f` (`iam grant video.sessions.stop to regional_manager/support_staff`),
`down_revision = 1470274175d8` (current head at the time of writing). Additive only — no schema
change, no column, mirrors the existing `_role_permissions_table` bulk-insert pattern every prior
RBAC-correction migration in this codebase already uses (`22e94bc4e924`, `7eb581884c39`).
`founder`/`org_admin`/`parent` unaffected (already held it); `finance_staff`/`driver` unaffected
(hold no `video.*` permission before or after).

### 2. Frontend: widen the presentation gate, reuse every existing piece unchanged

`LiveTrackingPage.tsx`'s `isOrgAdmin` boolean is replaced by a `canSeeVideo` check against the
same role set D5 already treats as eligible **on the web dashboard specifically** (D5's own
`_VIDEO_ELIGIBLE_ROLES` also includes `PARENT`, but Parent has no web login at all —
`.claude/rules/frontend.md` #4 — so it's correctly excluded from this frontend check; that
exclusion is structural, not a new decision):

```
founder | regional_manager | support_staff | org_admin
```

**No new component.** The exact same `CameraPicker`, `VideoPlayerPanel`, and
`useVideoSessionController` (ADR-0028 §G) already render/operate identically regardless of which
eligible role is signed in — none of the three contains a role branch to begin with, so widening
`canSeeVideo` is the entire change. The device-status panel (terminal id/online badge) already
rendered for every role reaching the page (ADR-0028) and is unaffected.

**`finance_staff`, `driver`, `parent` are unchanged** — `finance_staff` was never in
`_VIDEO_ELIGIBLE_ROLES` and holds no `video.*` RBAC permission (unaffected by the migration
above); `driver`/`parent` have no reachable path to this page at all (mobile-only,
`.claude/rules/flutter.md` #1).

## Authorization / Security — explicitly verified, not just asserted unchanged

- **D5 (`VideoAccessPolicy`, `enforce_d5`, `resolve_d5_decision`): zero lines changed.** Full
  D5 unit suite (`test_core_video_access_policy.py`, `test_policy_guards.py` — 46 tests) run
  after this change: all pass, unmodified.
- **Tenant/region scope (`ScopeResolver`): zero lines changed.**
  `OrganizationScopeResolverRoundTripTests` (4 tests: Founder unrestricted, Regional
  Manager region-derived, Support Staff directly-assigned, tenant-role own-org-only) run after
  this change: all pass, unmodified.
- **RBAC layer 2 gap closed, proven against the live database, not just the migration's own SQL**
  — a new integration test (`test_rbac_and_scope_resolver.py`,
  `test_seeded_matrix_grants_regional_manager_and_support_staff_video_sessions_stop`) calls the
  real `IamPermissionEvaluator` against the live-migrated `role_permissions` table and confirms
  both roles now pass, while `finance_staff`/`driver` still correctly fail.
- **`/video/*` route-level authorization is unchanged** — `require_permission(Permission(...))`
  on all three routes, `enforce_d5` before any `VideoApplicationService` call: identical code
  path, now reachable by two more roles because RBAC (not D5, not the routes) previously blocked
  them.
- **No new authorization model, no new permission name** — reuses
  `video.live.start`/`video.playback.start`/`video.sessions.stop` verbatim.

## Consequences

- Founder/Regional Manager/Support Staff can now start, view, and stop a live video session for
  any vehicle within their existing scope, from the same `/platform/tracking` page they already
  use for GPS — no new nav entry (the existing "Live Tracking" entry already reaches this page
  for these roles).
- `/org/video` is unaffected — still Org-Admin-only, still the device-first fallback ADR-0028 §B
  already established reasons to keep.
- The Platform-Admin-video question ADR-0028 left open is now closed, narrowly: Founder/Regional
  Manager/Support Staff, not Finance Staff, not Driver, and Parent's own ADR-0026 grant model is
  untouched.

## Implementation checklist (implemented 2026-08-16 — not yet committed)

- [x] Migration `50261534916f`: grant `video.sessions.stop` to `regional_manager`/`support_staff`
      — applied, round-tripped (upgrade → downgrade → upgrade), live-verified.
- [x] New integration test proving the RBAC grant against the live evaluator.
- [x] Confirmed D5/`ScopeResolver` test suites pass unmodified (46 + 4 = 50 tests).
- [x] Widened `LiveTrackingPage.tsx`'s presentation gate from `org_admin`-only to a
      `VIDEO_ELIGIBLE_WEB_ROLES` set (`founder`, `regional_manager`, `support_staff`,
      `org_admin`) — `Role.PARENT` (D5-eligible but mobile-only) structurally excluded, not a
      new decision.
- [x] `LiveTrackingPage.test.tsx`: replaced the stale "non-org_admin is excluded" case (now
      `finance_staff`, since founder is no longer excluded) and added three `it.each` suites
      across Founder/Regional Manager/Support Staff — visibility, Start, and Stop — 9 new tests,
      23/23 in the file passing.
- [x] Full backend verification: `tests/unit` 1402/1402, `tests/integration` 280 tests with only
      the two already-documented, pre-existing `test_realtime_broker_fanout.py` failures
      (unrelated, confirmed via `git stash` in an earlier phase of this same work).
- [x] Full frontend verification: `tsc -b` clean, `vitest run` 463/463 across 73 files (+9 vs.
      the prior phase, zero regressions), `npm run build` succeeds.
- [ ] Not yet committed — held for review per this conversation's established rhythm.
