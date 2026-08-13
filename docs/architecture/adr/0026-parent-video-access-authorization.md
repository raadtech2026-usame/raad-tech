# ADR-0026: Parent Video Access Authorization

## Status

**Accepted, 2026-08-12, at explicit user direction** (`.claude/rules/workflow.md` #7/#8's
"never implement business logic without an approved design" — this ADR *is* that approval,
written before any implementation, mirroring ADR-0022/0023's identical "user gives an explicit
product requirement mid-session, formalize before coding" precedent).

## Context

D5 (`.claude/rules/jt1078.md` #1, `.claude/rules/security.md` #5, `.claude/rules/backend.md` #7,
`.claude/rules/flutter.md` #3) has read, since this platform's earliest architecture, as an
absolute: "Parents have zero reachable path to video, anywhere, ever." `core/policies/
video_access.py`'s own `_VIDEO_ELIGIBLE_ROLES` set excludes `Role.PARENT` unconditionally, and
`docs/architecture/frontend-flutter-master-roadmap.md` §2.5 point 2 already recorded — during
frontend planning, before any Flutter code existed — that this contradicts the platform's own
root business requirement: **`docs/business/Project_Brief_v1.md` §4.8 states Parents may "View
live video (if enabled by the organization)."** That roadmap document deliberately did not
resolve the conflict in Project Brief's favor, reasoning that D5 was cross-referenced by four
*later*, more specific rule documents and had a real, tested enforcement point, while the Project
Brief line was an unimplemented outlier — but it explicitly named the escape hatch: *"This is a
'business requirement changes' trigger only if you want to actually revisit D5 itself — otherwise
no action needed, and none is planned."*

The user has now triggered exactly that: organizations must be able to grant individual, named
parents live and/or playback video access, off by default, server-enforced, never a client-only
toggle. This ADR is that formal D5 revisit — resolving Project Brief §4.8 in its favor, narrowly,
under conditions that keep every property the four later rule documents actually protect.

**What this ADR is not.** It does not weaken D5's structural enforcement mechanism (`enforce_d5`
still runs, still server-side, still before any `VideoApplicationService` call). It does not
change the default parent experience (GPS + notifications, unchanged, ADR-0006/`flutter.md` #4).
It does not grant Driver any video reachability (out of scope — the user's own instruction names
Parent only). It does not implement HLS, and it does not perform physical MDVR testing.

## Decision

### 1. Two explicit, per-parent, boolean permissions — not a role, not a new RBAC system

`video_live_access` and `video_playback_access` (the user's own vocabulary) are modeled as two
boolean flags **directly on the `Parent` aggregate** (`transport_ops.domain.entities.Parent`),
not as RBAC grants. This is a deliberate reuse of an *existing* pattern in this exact codebase,
not a new permission system:

- RBAC (`role_permissions`, ADR-0004) grants capabilities **per role**, not per instance — every
  Org Admin holds the same permission set. A parent-by-parent grant cannot be expressed there at
  all; inventing a per-user RBAC override table would be exactly the "parallel permission system"
  the user's own instruction warned against building.
- `Parent.status` (`active`/`inactive`, existing), `StudentParent.is_primary` (existing),
  `devices.is_online` (ADR-0020) are all precedent for "a boolean capability/state flag directly
  on the owning aggregate, mutated by a dedicated domain method, audited automatically via the
  existing `DomainEvent` -> outbox -> `audit_entries` pipeline (ADR-0007)." This ADR applies that
  identical, already-proven shape — nothing new architecturally, a new instance of an old pattern.
- **Naming**: the literal field/column is `has_video_live_access`/`has_video_playback_access` —
  `.claude/rules/naming.md`'s "Booleans: `is_`/`has_` prefix" applies at every layer (domain, DB,
  DTO, API JSON), matching this codebase's overwhelming existing convention (`is_primary`,
  `is_active`, `is_password_change_required`, `is_backfill`). The user's own two permission
  *names* remain the vocabulary used in prose, the grant/revoke endpoint path, and this document.

**Storage**: two new `BOOLEAN NOT NULL DEFAULT false` columns on `parents`
(`has_video_live_access`, `has_video_playback_access`) — a new Alembic migration, since Database
Design §6.3 (the schema authority) predates this requirement and does not name them; this is a
disclosed, approved-by-this-ADR departure from that document, not a silent one.

**Default, enforced at three independent layers, not just one**: the domain factory
(`Parent.register`) always constructs a new `Parent` with both flags `False`; the migration's
`server_default` is `false` for any pre-existing row; and the D5 policy (below) treats an absent/
unresolvable flag as denial, never as grant. A newly-registered parent is never granted video
access by any code path.

### 2. Grant/revoke: Org Admin only, a dedicated endpoint and RBAC permission

`PATCH /parents/{parent_id}/video-access` (new route, `transport_ops` module), body
`{has_video_live_access?: bool, has_video_playback_access?: bool}` (at least one field, mirroring
`UpdateParentRequest`'s own "at least one of..." validation precedent), gated by a **new**
permission `transport_ops.parents.grant_video_access` — deliberately not reusing
`transport_ops.parents.update` (the existing profile-edit permission), because granting access to
a child's live video feed is a materially more sensitive action than editing a phone number
(`.claude/rules/security.md` #1: "least privilege by default... nothing is inherited
implicitly"). Granted **only** to `org_admin` in the seed RBAC matrix — the user's own instruction
scopes this to "organization administrators," not RAAD staff, and RAAD staff already hold zero
`transport_ops.parents.*` permissions in the current matrix (Founder is the sole exception via
`_ALL_PERMISSIONS`, unchanged).

Four new domain methods on `Parent` (`grant_video_live_access`/`revoke_video_live_access`/
`grant_video_playback_access`/`revoke_video_playback_access`), each idempotent same-state no-ops,
each recording a `DomainEvent` (`ParentVideoLiveAccessGranted`/`...Revoked`/
`ParentVideoPlaybackAccessGranted`/`...Revoked`) — mirroring `Parent.activate`/`disable`'s
identical shape verbatim. **Audit coverage is automatic, not a separate mechanism**: every
`ParentApplicationService` method commits through the existing `TransportOpsUnitOfWork`, whose
`commit()` (via the shared `core.db.unit_of_work.SqlAlchemyUnitOfWork` base, ADR-0007) writes
every recorded event to `audit_entries` in the same transaction — the identical, already-proven
path `Parent.activate`/`disable` already use. No new audit code is written for this.

**Tenant scope**: no new check is needed. `uow.parents.get(ParentId(parent_id))` is already scoped
by the caller's `TenantRegionScope` at the repository layer (ADR-0021) — an Org Admin from another
organization gets `None`/404 for a `parent_id` they don't own, the same protection
`activate_parent`/`disable_parent` already rely on with no explicit `_enforce_own_organization`
call of their own.

### 3. The authorization flow — the exact chain the user specified, each link independently enforced

```text
Parent (Principal, role=parent)
  -> D5 role gate (existing VideoAccessPolicy, now parent-conditional — see below)
  -> self identity: Principal.user_id -> Parent.id (reuses policy_guards._resolve_parent_id,
     the existing /me-style resolution CR-1 already uses — no new lookup invented)
  -> organization/parent ownership: implicit in "self identity" above — a Parent can only ever
     resolve to *their own* Parent row; there is no code path that accepts a client-supplied
     parent_id for this flow at all (mirrors ADR-0023's own "no client-supplied parent_id -
     structural, not a runtime check" precedent)
  -> explicit permission check: has_video_live_access (for /video/live) or
     has_video_playback_access (for /video/playback), read off that resolved Parent
  -> child/device/camera ownership: is any of this Parent's children currently assigned to the
     vehicle this device_id belongs to (reuses policy_guards.find_owned_student_id_for_vehicle's
     existing CR-1 resolution logic, extended from vehicle_id to device_id via fleet_device's
     existing Device -> vehicle_id link, no new cross-module read pattern)
  -> VideoSession (existing VideoApplicationService.request_live_video/request_playback_video,
     unchanged)
  -> VideoProviderPort -> JT1078 relay (existing Jt1078RelayAdapter, unchanged)
```

Every link is independently, server-side enforced in `interfaces/http/policy_guards.py` (new
`resolve_parent_video_decision`/function, composed into `enforce_d5`) — **before** any
`VideoApplicationService` call, exactly the existing precedent `enforce_d5` already established
for Org Admin/RAAD staff. A parent failing *any* link receives `403 VideoForbiddenError` (reusing
the existing `VIDEO_FORBIDDEN` code — no new error taxonomy) and never reaches
`VideoApplicationService`, `VideoProviderPort`, or a viewer token. **A parent who does not own the
device/child at all gets `404`, not `403`** (this codebase's established cross-tenant-probing-
avoidance convention, `find_owned_student_id_for_vehicle`'s own existing behavior) — only a parent
who owns the child but lacks the explicit permission gets `403`.

**`VideoAccessPolicy` (D5) itself is extended, not bypassed**: `_VIDEO_ELIGIBLE_ROLES` gains
`Role.PARENT` — a parent may now *reach* the policy's scope check, but `evaluate()` alone is no
longer sufficient for a Parent caller; `policy_guards.resolve_d5_decision` additionally requires
the new parent-specific chain above to pass. Non-parent roles are entirely unaffected — their
existing `org_scope.allows(...)`-only check is unchanged. **D5's own text is updated** (`.claude/
rules/jt1078.md` #1, `security.md` #5, `backend.md` #7) from an unconditional "zero reachable path,
ever" to "zero reachable path by default, and only ever through an explicit, individually granted,
server-enforced permission — never a role-wide grant, never a client-side toggle." This is judged
a narrowing, not a weakening: the *default* is unchanged (still zero), the *mechanism* is still
100% server-side, and the new path requires four independent facts to all be true, not one flag.

**Live and playback stay separate, structurally**: `resolve_d5_decision` takes a `purpose:
Literal["live", "playback"]` (or two call sites), reading only the matching flag —
`has_video_live_access=True, has_video_playback_access=False` genuinely cannot reach
`POST /video/playback`, and vice versa. No shared "video enabled" boolean exists anywhere.

### 4. RBAC: Parent role gains the three existing video permissions

`_PARENT_PERMISSIONS` (RBAC seed matrix) gains `video.live.start`, `video.playback.start`,
`video.sessions.stop` — the *same* three permissions Org Admin/Regional Manager/Support Staff
already hold. This is the RBAC **layer 2** gate (API Contracts §3.1's four-layer model:
Authentication -> RBAC -> Tenant/region scope -> Domain policies) — it only lets a Parent
*attempt* the route at all; it grants no capability by itself, exactly mirroring how Parent
already holds `tracking.vehicles.read_latest` today while CR-1 (a domain policy, not RBAC) further
restricts what that permission actually yields. **This is the same architectural shape CR-1
already established for exactly this "role can attempt, policy decides per-instance" split** — no
new RBAC mechanism, a second application of the existing one.

`POST /video/sessions/{id}/stop` for a Parent additionally requires the stopping parent to be the
session's own `requested_by` (or, more simply, resolves ownership via the same device/child chain)
— a parent must not be able to stop another parent's, or an Org Admin's, video session. Enforced
in `policy_guards` alongside the live/playback checks, not left to RBAC alone.

### 5. Mobile surface: Flutter only, `flutter.md` #3 narrowly amended

Per the user's own explicit choice (surface-decision `AskUserQuestion`, this session): the video
player lives in the Flutter mobile app, not the React web dashboard — the web dashboard has no
Parent login at all (`MobileOnlyPage`), so a web-only player would be permanently unreachable by
any parent. `.claude/rules/flutter.md` #3 ("No live video anywhere in the mobile app, for either
role") is narrowly amended: **Driver still has zero video reachability, unconditionally** (out of
this ADR's scope — the user's instruction names Parent only); **Parent has video reachability
only when both the explicit permission is granted server-side and the same D5 chain above passes
on every request** — the mobile client shows/hides the affordance based on `GET /me`'s own
response (a new `has_video_live_access`/`has_video_playback_access` pair surfaced there, mirroring
`.claude/rules/frontend.md` #2's "presentation of server-enforced scope, never a second
authorization system") but **the server-side chain in §3 is what actually protects the media
relay** — a compromised or modified mobile client that skips its own UI gating still gets `403`/
`404` from the API, and a call with no permission still cannot mint a viewer token or reach
`services/jt1078` at all.

**New dependency**: `media_kit`/`media_kit_video` (MIT license), for FLV decode/render — approved
by the user (dependency-choice `AskUserQuestion`, this session) after the required explain-before-
install step (`.claude/rules/workflow.md` rule 1). The already-approved `web_socket_channel`
(`pubspec.yaml`, M0) handles the WS-FLV transport itself; the app re-serves received bytes over a
local loopback `dart:io.HttpServer` (no new dependency) that `media_kit` opens as an ordinary
network URL — `media_kit` is not asked to speak this relay's bespoke WS protocol directly.

### 6. Relay-issued viewer tokens — formalized, amending ADR-0024 §5 point 2 in place

**ADR-0024 §5 point 2's literal text** ("a... signed viewer token minted by the **backend**") is
corrected in place, same-document, mirroring this ADR's own §1's precedent for revising a prior
ADR rather than leaving a stale contradiction on record. The implementation (JT1078
backend-integration phase, already shipped) has the **relay** mint the token — the backend never
holds `JT1078_RELAY_VIEWER_TOKEN_SECRET` at all, so it is structurally incapable of minting one.
This is accepted here, formally, as the correct design: the security property §5 point 2 actually
protects — no session-authorization decision happens outside the backend's own D5/RBAC/(now)
per-parent-permission check, which runs before the relay is ever asked to mint anything — is fully
preserved; only *which process computes the token bytes* differs from the original wording.

### 7. Relay lifecycle events reconciled with `VideoSession` state — closes a real, previously disclosed gap

`VideoApplicationService.request_live_video`/`request_playback_video` currently call
`session.activate()` **eagerly**, immediately after the provider RPC returns — before the relay
has any real signal that media is flowing (ADR-0024 §5 point 3's actual condition). This ADR
corrects it: **the eager `activate()` call is removed.** `VideoSession` starts and stays
`REQUESTED` until a new backend event subscriber (`video/events/subscribers.py`, mirroring
`fleet_device`'s `DeviceConnectivityProcessor`/`DeviceAuthCodeProcessor` shape exactly) consumes
the relay's own `VideoSessionActivated`/`VideoSessionEnded`/`VideoSessionFailed` events (already
published, `services/jt1078/src/events/redis_session_event_publisher.py`) and calls
`session.activate()`/`.end(reason=...)`/`.fail(reason=...)` through `VideoUnitOfWork`, resolving
the session by `event.aggregate_id` (the relay's own `session_id`, which **is** the Business API's
`VideoSession.id` — the existing session-id passthrough design, JT1078 backend-integration phase —
needs no new correlation lookup). `stream_url` is still returned in the `POST /video/live`/
`/playback` response immediately (unchanged — it doesn't depend on `status`), only the persisted
`status` field now reflects reality with a short, expected delay rather than a synchronous lie.

**Not closed by this ADR, disclosed not silently assumed**: ADR-0024 §16's own "defensive
reconciliation timeout" for a `VideoSession` stuck in `REQUESTED`/`ACTIVE` with **no** lifecycle
event ever arriving (e.g., the relay process crashed) — that needs a new scheduled job (mirroring
`prune_vehicle_positions`/`sweep_expired_subscriptions`) this ADR does not build, out of the
user's own explicit "do not perform unrelated work" scope for this phase.

### 8. Concurrency ceilings — `SessionManager`, configurable, per Phase 2 §13.1

`services/jt1078/src/session/session_manager.py`'s `SessionManager.create_session` gains two
optional constructor limits: `max_global_sessions` (default `50`, directly citing
`docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §13.1's own "e.g., start 50 global")
and `max_sessions_per_organization` (default `None`/unconfigured — no approved document names a
per-org number, so none is invented; the mechanism exists and is configurable the moment one is
decided). Both are env-var-configurable (`JT1078_RELAY_MAX_GLOBAL_SESSIONS`/
`JT1078_RELAY_MAX_SESSIONS_PER_ORGANIZATION`, `RelayConfig`), `0`/negative meaning "no limit" for
either. Exceeding either raises a new `SessionCapacityExceededError`, already correctly surfaced
as `{"ok": false, "error": "..."}` by `SessionRequestServer._process_one`'s existing generic
exception handling (no new plumbing needed there) — which `Jt1078RelayRpcClient.call` already
turns into `Jt1078RelayError`, propagating uncaught through `VideoApplicationService` exactly as
every other unbound-provider/relay failure already does today (`services.py`'s own documented "no
try/except around the provider call, deliberately").

## Consequences

- **A parent can, for the first time, reach a video session — narrowly, by explicit design, never
  by default.** Every other role's video access is entirely unaffected.
- **Four independent server-side checks gate a Parent's video request**, not one — role,
  ownership, explicit permission, child/device ownership — matching the user's own specified
  chain exactly, each individually testable.
- **`.claude/rules/jt1078.md` #1, `security.md` #5, `backend.md` #7, `flutter.md` #3** all need
  updating to state the *narrowed*, no-longer-unconditional rule — done alongside this ADR, not
  deferred.
- **`docs/architecture/frontend-flutter-master-roadmap.md` §2.5 point 2's own "no action needed,
  and none is planned" is now superseded** — this ADR is the "business requirement changes"
  trigger that section named. That document is not rewritten (historical record of its own
  drafting-time reasoning); this ADR is where a reader following it forward should land.
- **A new RBAC permission, a new migration, four new domain events, and a new route** — the
  smallest surface that satisfies the user's explicit "reuse existing patterns, do not invent a
  parallel system" instruction while still being genuinely server-enforced end to end.
- **Mobile player work is real, Dart code, still categorically unverified** — no Flutter SDK in
  this sandbox, the same disclosed limitation every prior mobile phase carries; "written and
  carefully reviewed," not "run."

## Verification

- Unit: `VideoAccessPolicy` extended-role tests; the new `resolve_parent_video_decision` chain
  (each of the four links independently denying); `Parent`'s four new domain methods
  (idempotency, event payloads); the RBAC seed matrix's new Parent grants; `SessionManager`'s
  ceiling enforcement (global and per-org, independently).
- Integration: a live-Postgres round trip proving a granted parent's request reaches
  `VideoApplicationService` and a non-granted parent's does not (mirrors `TenantIsolationRepositoryTests`'
  existing pattern); the new relay-event subscriber against a real broker fixture.
- Architecture-gate: unaffected — no new module, no new cross-module import.
- **Not verified, disclosed**: the Flutter player, against any real device or Flutter SDK; the
  relay ceilings and event reconciliation, against a physical MDVR.

## References

- `docs/business/Project_Brief_v1.md` §4.8 — the root requirement this ADR formally reinstates,
  narrowly.
- `docs/architecture/frontend-flutter-master-roadmap.md` §2.5 point 2 — the prior, deliberate
  deferral this ADR is the named trigger for.
- `docs/architecture/adr/0024-jt1078-video-relay-architecture.md` §5 point 2 (amended in place by
  this ADR, §6 above), §5 point 3/§16 (relay lifecycle reconciliation, §7 above), §13.1-citing
  concurrency figures (§8 above).
- `docs/architecture/adr/0023-canonical-me-identity-resolution.md` — the "no client-supplied
  parent_id, structural" precedent this ADR's §3 extends to video.
- `docs/architecture/adr/0021-tenant-scope-enforcement-at-repository-layer.md` — the repository-
  layer scoping this ADR's §2 relies on for grant/revoke, unchanged.
- `docs/architecture/adr/0004-rbac-permission-matrix.md` — the RBAC layer this ADR's §4 extends.
- `.claude/rules/jt1078.md` #1, `.claude/rules/security.md` #5, `.claude/rules/backend.md` #7,
  `.claude/rules/flutter.md` #3, `.claude/rules/frontend.md` #2/#4 — all updated alongside this
  ADR.
