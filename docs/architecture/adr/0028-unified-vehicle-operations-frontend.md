# ADR-0028: Unified Vehicle Operations Frontend (GPS + Video from One Vehicle Selection)

## Status

**Accepted** (direct user decision, 2026-08-16 — approved as drafted, decisions A–H unchanged
from the original proposal). Written per `.claude/rules/workflow.md` #8, at explicit user
direction, as the frontend follow-up ADR-0027 itself named ("Frontend follow-up (future phase,
not this task)"). ADR-0027 (backend, `GET /vehicles/{vehicle_id}/device-assignment` +
`DeviceResponse.is_online`) is **Accepted and implemented** (commit `560580d`) — this ADR is
the design for consuming it. Implementation begins in the same conversation this ADR was
accepted in; see each source file's own reference back to this ADR for the mapping between a
decision letter (A–H) and the code that implements it.

## Context

**Product direction (user-directed, 2026-08-16):** a school bus's MDVR is one physical device
providing two capabilities — JT/T 808 GPS and JT/T 1078 video. The desired experience is: select
one Vehicle, see its live GPS map, its assigned device's online status, and its live video/camera
channels, all from that one selection — not two separately-navigated pages with two separate
pickers.

**What already exists, read directly from the current code, not assumed:**

- `LiveTrackingPage` (`features/live-monitoring/LiveTrackingPage.tsx`) — already the "select one
  vehicle, see its live state" page, shared unchanged across `/platform/tracking` and
  `/org/tracking` (Phase F7's own two-dashboard convention). Vehicle picker
  (`listVehiclesForTracking`), a `getLatestVehiclePosition` snapshot query, a
  `useWebSocketChannel("/ws/tracking", ...)` subscription, an active-trip/route overlay query
  pair, and a `MapView`-backed map with marker/route-layer effects — all inlined directly in one
  component's body today, not extracted.
- `VideoPage` (`features/video/VideoPage.tsx`) — Org-Admin-only (`/org/video`), device-first by
  necessity (its own docstring: "a real, confirmed contract gap, not a design choice" — no route
  resolved vehicle→device before ADR-0027). Device picker → camera picker → `requestLiveVideo`/
  `stopVideoSession` session lifecycle → `useMpegtsPlayer(streamUrl, videoRef)` for playback, all
  inlined in one component's body today as well.
- `useWebSocketChannel` (`shared/hooks/useWebSocket.ts`) is **already** a generic, shared,
  low-level primitive — used independently by `LiveTrackingPage` (`/ws/tracking`),
  `NotificationsPage` (`/ws/notifications`), and `DashboardHomePage`'s
  `LiveOperationsSection.tsx` (its own separate `/ws/tracking` subscription for the dashboard
  preview tile). **Requirement #3 ("do not duplicate the GPS WebSocket implementation") is
  already satisfied structurally** — nothing in this ADR touches this hook. What's duplicated
  today, if a new page were built by copying, would be the *feature-level orchestration* on top
  of it (subscribe-on-select, marker rendering) — that orchestration is what needs extracting,
  not the socket.
- `useMpegtsPlayer` (`features/video/useMpegtsPlayer.ts`) is already a self-contained,
  page-agnostic hook (`streamUrl`, a `videoRef` in; `{state, errorMessage}` out) — reusable
  as-is, zero changes needed.
- `GET /vehicles/{vehicle_id}/device-assignment` (ADR-0027) returns `DeviceAssignmentResponse`
  (`device_id`, `vehicle_id`, …) — **not** a full device record. Resolving a vehicle's cameras/
  online-status/terminal-id still needs a second call, `GET /devices/{device_id}` (existing,
  unchanged) — the same route `VideoPage`'s current device picker already calls per-row, just
  now callable for one known id instead of a list.
- Live-checked RBAC (same method as ADR-0027's own review): `fleet_device.devices.read` is held
  by `founder`, `regional_manager`, `support_staff`, **and** `org_admin`. `video.live.start`/
  `video.playback.start`/`video.sessions.stop` are held by `org_admin` (all three) and, per the
  RBAC seed, `founder` (all three) and `regional_manager`/`support_staff` (two of three — missing
  `.sessions.stop`, a pre-existing gap flagged in the second conversation turn, unrelated to this
  ADR and not fixed here). **The frontend, today, exposes zero video UI to any Platform Admin
  role** — `platformNav` has no video entry, `PLATFORM_BUILT_ROUTES` has no video route
  (`router.tsx`'s own comment: "a deliberate reading of `.claude/rules/api.md` #2… not
  'Org-Admin plus RAAD staff'"). That reading was never revisited or reversed by the user in this
  conversation — only investigated. **Requirement #12 ("preserve /org and /platform role
  boundaries unless the design explicitly proves a change is required") means this ADR must not
  quietly re-open that question by giving Platform Admin a video panel just because the two
  dashboards now share one evolved component.**

## Decision

### A. Route structure — evolve `LiveTrackingPage` in place; no new route

`/platform/tracking` and `/org/tracking` **keep their exact paths, keep being the same shared
component**, and keep their existing nav entries. No new `vehicle-operations`-style route is
introduced.

**Why, not a menu of options:**
- `LiveTrackingPage` already *is* "select one vehicle, see what it's doing right now" — the
  target UX is a superset of what this page already does, not a different page.
- A second, parallel route would immediately violate requirement #8 ("do not maintain separate
  vehicle and device selectors in the final unified view") at the *navigation* level — two nav
  entries, two vehicle pickers, one showing GPS-only and one showing GPS+video, is exactly the
  fragmentation the product direction is trying to eliminate.
- It is the only option that gets requirement #1 (reuse `LiveTrackingPage`'s GPS logic) for
  free by construction, rather than by promise.
- Requirement F (backward compatibility) is satisfied by definition — the URLs do not change at
  all; `LiveOperationsSection.tsx`'s existing `<Link to="/platform/tracking">` and any other
  internal deep link keep working unchanged.

The nav label ("Live Tracking") is left as-is — a one-word label change (e.g. "Live Tracking &
Video") is a trivial, reversible follow-up for whoever implements this, not an architectural
decision this ADR needs to pin down.

### B. `/org/video` and its nav entry — kept, unchanged, demoted in *role* only implicitly

`/org/video` is **not removed, redirected, or hidden** by this design.

**Why:** a device that has not yet been assigned to any vehicle (during onboarding, or a spare/
replacement unit RAAD support is bench-testing) has **no path into the unified flow at all** —
the unified flow starts from a vehicle selection, and `GET /vehicles/{id}/device-assignment`
returns 404 for exactly that device. `/org/video`'s device-first picker remains the only way to
reach such a device. Removing it would be a real capability regression disguised as a UX
simplification — requirement #8's "no separate selectors" governs the **unified view's own**
internal design, not a mandate to delete every other video entry point in the app.

Once the unified view ships and is validated in real use, a small, separate follow-up can decide
whether to relabel/demote `/org/video` in the nav (e.g. "Device Video (Advanced)") — **not
decided here**, flagged as a deliberate deferral, not an oversight.

### C. Vehicle → device resolution and hand-off to the camera picker

Two-step resolution, exactly mirroring ADR-0027's own two-endpoint shape:

1. On vehicle selection, call `GET /vehicles/{vehicle_id}/device-assignment` (new). `404` → "no
   active device" state (below); `200` → `{device_id}`.
2. Call `GET /devices/{device_id}` (existing, unchanged) with that id → the device's
   `terminal_id`, `lifecycle_state`, `is_online` (ADR-0027 Change 2), and `cameras[]`.

Both calls are composed into one new hook, `useVehicleActiveDevice(vehicleId)` (see G), which is
the **only** path by which the camera picker ever learns a `device_id` — there is no manual
device picker anywhere in the unified view, and **`vehicle_id`/`device_id` are never cross-
referenced from a `VehiclePositionResponse.device_id` field** (requirement #7) — that field
answers "which device *sent this specific GPS report*," a different and weaker fact than "which
device is *currently assigned*" (ADR-0027's own Context point 4 already draws this exact
distinction for the backend; this ADR carries the same discipline into the frontend). The GPS
panel and the device-resolution hook are two independent data sources that happen to be shown
together — one is never derived from the other.

### D. Empty/error states

| Condition | Surface | Behavior |
|---|---|---|
| No vehicle selected | Both panels | Existing `LiveTrackingPage` empty state, unchanged. GPS map placeholder; device/video section not rendered at all. |
| Vehicle selected, device-assignment loading | Device/video panel only | `Skeleton`, matching this page's existing loading convention. **GPS panel is unaffected** — it has its own independent loading state and does not wait on the device call. |
| `404` — no active device assignment | Device/video panel only | `EmptyState`: "No device assigned to this vehicle." GPS panel keeps working independently — a vehicle can have position history/live GPS with no *currently* assigned device (e.g. mid-reassignment), and that must stay visible, not be hidden behind the device panel's own empty state. |
| Device resolved, zero cameras | Video sub-panel only | `EmptyState`: "This device has no camera channels configured." Camera picker hidden/disabled; device online-status line still shows. |
| Device resolved, `is_online: false` | Video sub-panel (badge, not a block) | A visible "Last reported offline" badge next to the camera/Start controls — **never disables Start**. `is_online` is a best-effort telemetry mirror (ADR-0020/0027), not an authoritative gate; the real authority is the backend's own `POST /video/live` → JT1078 relay call. Client-side blocking on a soft signal the server doesn't itself enforce is the same anti-pattern `.claude/rules/frontend.md` #2 already forbids for authorization — applied here to availability instead. |
| Video request/connect/connected/stopped/error/unavailable | Video sub-panel | **Unchanged** — reuses `VideoPlayerPanel`'s existing phase states verbatim (see G); zero new states invented. |

### E. Layout

Side-by-side on wide viewports (map left, video right, roughly 60/40 — matching this dashboard's
existing two-column `Card` conventions already used by both source pages), collapsing to a single
stacked column (map, then device/video panel below it) under this codebase's existing responsive
breakpoints. **Not tabs** — the product direction explicitly asks for GPS and video "on the same
operational view," and hiding one behind a tab would contradict that. Both panels can mount
simultaneously without both *streaming* simultaneously: the map already renders continuously once
a vehicle is selected (unchanged), but the video panel's actual session — and the only point at
which meaningful bandwidth/CPU cost begins — still requires an explicit "Start Live" click, the
exact same non-autostart discipline `VideoPage` already enforces today. Simultaneous mounting is
therefore cheap; simultaneous *streaming* stays opt-in.

### F. Backward compatibility

- `/platform/tracking`, `/org/tracking`, `/org/video` — all three keep their exact paths,
  methods, and (for `/org/video`) full existing behavior.
- `LiveOperationsSection.tsx`'s dashboard-preview link to `/platform/tracking` needs no change.
- `LiveTrackingPage.test.tsx`/`VideoPage.test.tsx` (existing) both need updating as part of
  implementation (see H) — not a breaking change to either page's *contract*, but their internal
  structure changes as logic is extracted into hooks/components, so their test mocks
  (`vi.mock("./api", …)`, `vi.mock("./useMpegtsPlayer", …)`) need to track the new module
  boundaries.
- No API client function is removed — `listDevicesForVideoPicker`/`requestLiveVideo`/
  `stopVideoSession` (video), `listVehiclesForTracking`/`getLatestVehiclePosition`/etc.
  (tracking) all keep existing signatures; only new functions are added (`getDeviceAssignmentForVehicle`).

### G. Reusable components/hooks — the exact extraction

**From `LiveTrackingPage` (`features/live-monitoring/`), extracted, not duplicated:**

| New file | Contains | Extracted from |
|---|---|---|
| `useVehiclePosition.ts` | `snapshotQuery` + `useWebSocketChannel("/ws/tracking", …)` subscribe/unsubscribe effect + `livePosition` state → `{ position, wsStatus, lastCloseCode, hasKnownPosition }` | `LiveTrackingPage.tsx` lines ~63-131 (current) |
| `useActiveTripRoute.ts` | `activeTripQuery` + `routeQuery` → `{ routeStops }` | `LiveTrackingPage.tsx` lines ~81-91 (current) |
| `VehicleMapPanel.tsx` (+ `.module.css`) | `MapView`, marker add/update effect, route/stop layer effect — presentational, takes `position`/`routeStops` as props | `LiveTrackingPage.tsx`'s map-card JSX + its three map-mutation effects |
| `useVehicleActiveDevice.ts` | **New** — composes `getDeviceAssignmentForVehicle` + `getDevice`-equivalent (this feature's own minimal copy, matching `listVehiclesForTracking`'s established "own minimal read, no cross-folder import" precedent) → `{ status, device }` | New — this is what ADR-0027 enables |
| `api.ts` (existing file) | + `getDeviceAssignmentForVehicle(vehicleId)`, mapping `404 → null` (same convention `getLatestVehiclePosition` already uses) | Additive |
| `LiveTrackingPage.tsx` | Becomes: vehicle picker + `<VehicleMapPanel/>` (via the two hooks above) + (org_admin only) camera picker + `<VideoPlayerPanel/>` (via `useVehicleActiveDevice` + `useVideoSessionController`) | Refactor of the existing file, not a rewrite |

**From `VideoPage` (`features/video/`), extracted, not duplicated:**

| New file | Contains | Extracted from |
|---|---|---|
| `useVideoSessionController.ts` | `startMutation`, `session`/`manuallyStopped`/`requestError` state, `ensureStopped`/`handleStart`/`handleStop`, `computePhase()` → `{ phase, streamUrl, start, stop, canStart, canStop, requestError }` | `VideoPage.tsx` lines ~55-170 (current) |
| `CameraPicker.tsx` | The camera `<Select>` block — presentational, takes `cameras`/`value`/`onChange` | `VideoPage.tsx`'s camera `FormField`/`Select` block |
| `VideoPlayerPanel.tsx` (+ `.module.css`) | `<video>` + `useMpegtsPlayer` + every phase-based overlay (idle/requesting/connecting/connected/stopped/unavailable/error) — presentational, takes `phase`/`streamUrl`/`requestError`/`player` as props | `VideoPage.tsx`'s player-card JSX |
| `VideoPage.tsx` | Becomes: device picker + `<CameraPicker/>` + `useVideoSessionController` + `<VideoPlayerPanel/>` | Refactor of the existing file, not a rewrite |

**Cross-folder import, one narrow instance, already precedented:** `LiveTrackingPage.tsx`
imports `CameraPicker`/`VideoPlayerPanel`/`useVideoSessionController` from `features/video/` — a
*component* import across feature folders, not a data-fetch reuse. `.claude/rules/frontend.md`
#1's "no cross-folder `api.ts` import" discipline is about data reads specifically;
`StudentAssignmentSection`'s own existing cross-folder component import (flagged explicitly in
CLAUDE.md's Phase F6 notes as "a component import, not a duplicated data read") is the direct
precedent this ADR follows, not a new exception being invented.

**Role gating, presentation-only, server stays the real gate:** the camera-picker/video-player
section of the evolved `LiveTrackingPage` renders only when `principal.role === "org_admin"` —
matching exactly the reading `platformNav`'s own existing comment already gives for why no
platform role sees a video nav entry today (Context, above). This is `.claude/rules/frontend.md`
#2's ordinary "presentation of server-enforced scope" pattern, identical in kind to
`FINANCE_ALLOWED_PATHS` already hiding nav items — `require_permission`/`enforce_d5` remain the
only real gate, unchanged, still invoked exactly where they are today.

**Given to Platform Admin roles, without touching the video boundary at all:** since
`fleet_device.devices.read` is already held by `founder`/`regional_manager`/`support_staff` (not
just `org_admin`), `useVehicleActiveDevice`'s **device-identity/online-status** half (assigned
device's terminal id, lifecycle state, `is_online`) can render for every role that reaches
`/platform/tracking` too — only the *video* half (camera picker, player, start/stop) stays
`org_admin`-only. This uses an already-granted permission for exactly what it already grants,
without deciding the deferred Platform-Admin-video question either way.

### H. Test strategy

Mirrors this codebase's existing convention exactly (Vitest + React Testing Library, `vi.mock`
on sibling modules — no new test tooling, no Playwright/E2E infra, matching
`.claude/rules/workflow.md` #1/#2's "no new dependency without approval").

- **New hook tests** (`useVehicleActiveDevice.test.ts`, `useVehiclePosition.test.ts`,
  `useActiveTripRoute.test.ts`, `useVideoSessionController.test.ts`): mock the relevant `api.ts`
  functions, assert the returned state shape across found/none/404/error cases — the same
  granularity `api.test.ts` files already test at, just for hooks instead of raw fetches.
- **New component tests** (`VehicleMapPanel.test.tsx`, `CameraPicker.test.tsx`,
  `VideoPlayerPanel.test.tsx`): props in, rendered output out, mocking `MapView`/
  `useMpegtsPlayer` exactly as today's `LiveTrackingPage.test.tsx`/`VideoPage.test.tsx` already
  do — cheaper and more precise than only testing everything through the full page.
- **`LiveTrackingPage.test.tsx` (existing, extended)**: add cases proving requirement #7
  directly — selecting a vehicle triggers `getDeviceAssignmentForVehicle`; a resolved device
  populates the camera picker from *its own* `cameras`, never from any WS position frame or
  snapshot payload; clicking Start Live calls `requestLiveVideo` with the **resolved** `device_id`
  (a regression test that would fail if a future change ever reintroduced inferring the device
  from a position field). Add the no-assignment empty-state case, and the role-gating case
  (render as `founder` → no camera picker, no video panel, no video API calls at all — mirroring
  `navConfig.test.ts`'s existing role-filtering test shape).
- **`VideoPage.test.tsx` (existing)**: after extraction, must keep passing with its current
  assertions essentially unchanged — the strongest possible proof the refactor is behavior-
  preserving for the standalone device-first flow, not just for the new unified one.
- **No new integration/E2E layer proposed** — matches this frontend's existing test ceiling.

## Non-goals (explicitly not designed or decided by this ADR)

- Whether Platform Admin roles should ever get a *video* capability in the frontend — investigated
  in an earlier conversation turn, deliberately **not** resolved here (requirement #12).
- Any change to `/org/video`'s own internal implementation, or its removal.
- Any RBAC/permission change (all reused verbatim: `fleet_device.devices.read`,
  `video.live.start`/`.playback.start`/`.sessions.stop`).
- Any change to D5, `VideoAccessPolicy`, ADR-0026 Parent video access, JT808, JT1078, or the relay
  — nothing in this ADR touches the Business API beyond consuming the two already-shipped
  ADR-0027 fields; the entire `/video/*` authorization chain (`enforce_d5` before any
  `VideoApplicationService` call) is invoked exactly where it already is today, with exactly the
  same inputs, just discovered via a different UI path.
- Actual implementation — no frontend file is touched by this ADR.

## Consequences

- `LiveTrackingPage`/`VideoPage` both shrink into thinner composition components once their logic
  is extracted; each extracted hook/component becomes independently testable, and `VideoPage`
  itself needs zero behavioral changes (only an internal reshuffle) to keep working standalone.
- Two dashboards, one evolving component, one new client-side role branch inside it (video
  section, `org_admin`-only) — no new nav entry, no new route, no new permission.
- The Platform-Admin-video question stays open, now flagged in two ADRs (the earlier
  investigation turn and this one) rather than silently decided either way.

## Implementation checklist (implemented 2026-08-16 — not yet committed)

- [x] Extracted `useVehiclePosition`/`useActiveTripRoute`/`VehicleMapPanel` from
      `LiveTrackingPage` (behavior-preserving; the pre-existing 8 tests pass unmodified in
      assertions).
- [x] Extracted `useVideoSessionController`/`CameraPicker`/`VideoPlayerPanel` from `VideoPage`
      (same discipline — `VideoPage.test.tsx`'s 11 pre-existing tests pass with zero test-file
      changes from this phase).
- [x] Added `getDeviceAssignmentForVehicle`/`getActiveDeviceDetails` to `live-monitoring/api.ts`;
      added `useVehicleActiveDevice`.
- [x] Composed the evolved `LiveTrackingPage`: GPS panel (unchanged behavior) + device-status
      panel (all roles reaching the page) + video panel (`org_admin`-only, gated on
      `principal.role` from `useAuthStore`).
- [x] Extended `LiveTrackingPage.test.tsx` (8 original + 6 new = 14 tests); confirmed
      `VideoPage.test.tsx` passes with no changes to its own file.
- [x] New hook/component tests: `useVehicleActiveDevice`, `useVehiclePosition`,
      `useActiveTripRoute`, `VehicleMapPanel`, `CameraPicker`, `VideoPlayerPanel`,
      `useVideoSessionController` — 22 tests across 7 new files.
- [x] Full frontend verification: `tsc -b` clean, `vitest run` 454/454 passing across 73 files
      (zero regressions outside the touched feature folders), `npm run build` succeeds.
- [ ] Manual verification in a real browser — **not performed this phase** (no running dev
      server exercised in this environment); disclosed, not silently skipped. Recommended before
      or shortly after this lands, per this project's own "test the golden path and edge cases"
      standard for frontend work.
- [ ] Not yet committed — held for review per explicit instruction.
