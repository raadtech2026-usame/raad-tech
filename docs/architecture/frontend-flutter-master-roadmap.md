# RAAD Frontend & Flutter — Master Implementation Roadmap

**Author's role for this document:** Lead Software Architect / Lead Frontend Architect review.
**Status:** Planning only — no feature code was written to produce this. `frontend/`'s current
state is exactly the app-shell foundation from the prior phase (routing, auth, API client,
WebSocket hook); `mobile/` is exactly the structural scaffold it always was.
**This document was drafted, then self-critiqued, then revised once before being presented —
see §12 for what that pass changed.**

---

## 0. A blocker I must surface before anything else

You said the UI/UX was "previously created in Claude Desktop" and that I "now have access to"
it. **I do not.** I searched this repository exhaustively for design artifacts — images, Figma
files, exported specs, design-token files, a `design/` folder, git history mentioning "design"
or "Figma" — and found nothing. Claude Desktop and Claude Code are separate products with no
shared memory or file access between sessions; nothing produced there arrives here
automatically.

This is not a small gap. §3.1 and §4 (Phase F0) below depend on it directly. I have **not**
invented a design to fill the space, and I have **not** silently assumed a generic Material/Ant
look. Instead:

- Every part of this roadmap that is independent of the visual design (architecture, phase
  sequencing, dependencies, testing, integration, permissions, deployment, Flutter, shared
  contracts) is complete and does not need the design to be actionable.
- Phase F0's design-system work is planned as a **methodology** — the exact pipeline I will run
  the moment I have the actual screens/tokens — with a clearly marked substitution point.
- I need one of: exported screens/frames (PNG/PDF), a Figma (or equivalent) link, an exported
  design-token set, or at minimum a written style guide (palette, type scale, spacing scale,
  component inventory). Screenshots pasted into the conversation are enough to start.

Everything below is written so that arrival of the design slots into Phase F0 without
reshaping any other phase.

---

## 1. Executive Summary

RAAD's backend is feature-complete against its approved documents across all ten bounded
contexts, including realtime WebSocket delivery (see
`docs/architecture/backend-production-readiness-report.md`). The frontend has a working,
tested app shell (Vite/React/TypeScript, routing, auth, REST client, WebSocket hook) and zero
feature UI. Flutter is an empty structural scaffold. A device-plane service (`services/jt808/`)
is **far more built than the backend's own documentation implied** — transport, session
management, protocol parsing, dispatch, auth/registration, and the full position-ingestion
pipeline are implemented and tested; only the broker wiring and a Business-API-side consumer
are missing (§2.2). This changes how I sequence the Live Monitoring/Maps phase relative to
everything else, and it's the single most consequential finding of this review.

The roadmap that follows is organized around **bounded-context dependency order**, not a
generic "auth → dashboard → CRUD → done" template. Organization comes first because every other
context references `organization_id`. Fleet & Device comes before Transport Operations because
`Trip.vehicle_id` is a live reference. Live Monitoring is gated on a map-provider decision I
cannot make for you. Video is naturally last on the web side because its backend port is
unbound by design. Flutter starts in parallel with, not after, the React work — but only once
the three bounded contexts it actually touches (Transport Ops, Tracking, Notifications) have
proven integration patterns in React first, so mobile doesn't re-discover the same API quirks
twice.

Thirteen phases for React (F0–F13, including production readiness), six for Flutter (M0–M5),
one dedicated shared-architecture section, and a decision log of exactly six things that need
your explicit sign-off before their dependent phase can start. Everything else in this document
is mine to execute without further check-ins, per your instruction.

**Update, 2026-07-23:** a third parallel engineering track now exists alongside React and
Flutter — an independent **Backend Integration** workstream (§4A) closing the JT808 device-plane
gaps §2.2 below identifies, tracked as its own set of sub-phases (B1–B3) rather than folded into
the React sequence. See §4A for the full phasing decision and reasoning.

---

## 2. Current State Assessment

### 2.1 Backend — verified against the repository, not memory

All ten bounded contexts complete end-to-end; RBAC/ScopeResolver/CR-1/D4/D5 real and tested;
pagination/filtering/sorting on every list endpoint; `/ws/tracking` and `/ws/notifications`
implemented. Full detail in the Production Readiness Report — not repeated here. The three
blockers that report named stand: no CI-gated WebSocket e2e test, no live device-plane data
flowing end-to-end, no bound payment provider. The second of those needs updating — see below.

### 2.2 The JT808 device plane is substantially built — a correction to my own prior assessment

`services/jt808/` (a separate deployable per `architecture.md` #2) has real, tested
implementations of: TCP transport, connection lifecycle, JT/T 808-2013 frame
parsing/escaping/checksum/reassembly, message dispatch, terminal registration & authentication
(with session binding), and — critically — the **position ingestion pipeline**
(`0x0200`/`0x0704` handlers) that publishes a `DevicePositionReported` event with a field shape
deliberately matching `tracking.application.commands.RecordVehiclePositionCommand` one-to-one.

**What's still missing, precisely:** JT808's own `EventPublisher` is a logging stub
(`LoggingEventPublisher`) — no broker technology is chosen or wired on that side either. And on
the Business API side, `tracking/events/subscribers.py` is empty — nothing consumes
`DevicePositionReported` and turns it into a persisted `VehiclePosition` row. **Both halves of
the bridge are unbuilt, not one.** Once a broker is chosen for JT808 (likely the same Redis
Streams the Business API already uses, for zero new infrastructure) and both a publisher and a
consumer are wired, live tracking data starts flowing with no changes needed to `/ws/tracking`
itself — my WebSocket implementation already consumes exactly `DevicePositionReported`.

**A concrete field-name inconsistency I found while checking this, flagged for whoever wires
the bridge (likely me, in a later phase, or the backend track if it continues in parallel):**
JT808's `DevicePositionReported` dataclass uses `latitude`/`longitude`; my `/ws/tracking`
handler's documented wire frame (matching API Contracts §11.2 literally) uses `lat`/`lng`. No
one has serialized either side to an actual wire format yet (both are still in-process
dataclasses/stubs), so nothing is broken today — but this must be reconciled explicitly, not
silently, the moment a real broker payload is defined. I've recorded this so it isn't
rediscovered as a mystery bug later.

**Impact on this roadmap:** Live Monitoring (Phase F7) can be built and demoed against
synthetic/manual data (an operator can call the tracking REST endpoints or hand-publish a test
event) well before the device-plane bridge is complete. The map UI itself is not blocked by the
missing bridge — only _real_ bus data is. I will build F7 to be honest about this (a visible
"no live data source connected" state, never a fake moving dot), matching this codebase's own
"fail loudly / stay honest" discipline throughout the backend.

**Update, 2026-07-23:** this gap is now tracked as its own workstream — see §4A (Backend
Integration Track), specifically B1 (JT808 Provisioning Bridge) and B2 (Live Tracking Pipeline).
It runs in parallel with F5/F6, not before or after either, and is one of F7's two independent
gates (the other being the map-provider decision immediately below in §3.9).

### 2.3 Frontend foundation — what already exists

Vite + TypeScript + React 18, React Router, TanStack Query, Zustand, Vitest + RTL. Real
`POST /auth/login` flow, in-memory-only token storage, a `RouteGuard` component, a generic REST
client matching the backend's exact error envelope with 401-refresh-retry, and a generic
WebSocket hook implementing the documented first-auth-frame protocol with sane reconnect
back-off. 16 tests passing. No feature module has UI.

### 2.4 Flutter/mobile — what already exists

Pure structural scaffold (`main.dart`, empty feature/core/data/shared folders,
`pubspec.yaml` with no dependencies decided). Nothing to build on yet.

### 2.5 Business-requirement details not previously surfaced in any technical doc

Reading `Project_Brief_v1.md` directly (the root document every Phase 2/3.x doc derives from,
not previously re-read in full during backend work) surfaced two things worth recording here
rather than losing:

1. **§11.8 names "ETA Calculation" as a required Maps & Location Services capability.** No
   backend capability computes an ETA anywhere in this codebase today — not a documented gap in
   CLAUDE.md, not a port, nothing. This is a **real, previously unflagged scope item** with no
   current backend support. I am not inventing an ETA algorithm inside the frontend (that would
   put business logic in the wrong layer and violate "frontend renders, backend decides"). This
   needs its own backend design work before Phase F7 can show a real ETA — flagged in the
   Decision Log (§13) and in F7's own dependencies.
2. **§4.8 says Parents may "View live video (if enabled by the organization)" — this directly
   contradicts D5** ("Parents have zero reachable path to video, anywhere, ever" —
   `jt1078.md` #1, `security.md` #5, `backend.md` #7, `flutter.md` #3, all unanimous and all
   _later_, more specific documents than this one Project Brief line). Per `documentation.md`
   #2 I'm recording the conflict rather than silently picking a side — but there's no real
   ambiguity here: D5 is cross-referenced by four independent rule documents and already has a
   tested backend enforcement point (`enforce_d5`); this one Project Brief sentence is the
   outlier. **No frontend or Flutter work will ever give a Parent a video affordance.** This is
   a "business requirement changes" trigger only if you want to actually revisit D5 itself —
   otherwise no action needed, and none is planned.

---

## 3. Architectural Decisions To Finalize Before Feature Coding

These are Phase F0's actual content. Getting each of these right once, before nine feature
modules exist, is the difference between a consistent app and nine slightly-different ones.

### 3.1 Design system extraction methodology (blocked on §0's missing asset)

The moment I have screens/tokens, this is the pipeline:

1. **Inventory pass** — catalogue every distinct UI element across the provided screens
   (buttons, inputs, selects, tables, cards, nav, modals, toasts, badges/status pills, empty
   states, the map chrome). Group by recurrence, not by screen — a "status pill" used on the
   Organizations list and the Trip detail view is one component, not two.
2. **Token extraction** — colors (semantic, not just hex: `color.status.active`,
   `color.role.orgAdmin`, never a bare `#2563eb` scattered through component code), type scale,
   spacing scale, radii, shadows, breakpoints. Written once as data (JSON/YAML), not as
   hardcoded values in either React or Flutter — this is also the seed of the shared-tokens
   piece in §6.
3. **Atomic layering** — primitives (`Button`, `Input`, `Badge`) → composite (`DataTable`,
   `FormField`, `StatusCard`) → templates (`ListPageLayout`, `DetailPageLayout`,
   `DashboardShell`) → pages (feature-specific, thin, composed from templates). Every feature
   phase (F1–F12) consumes templates; none hand-rolls page layout.
4. **Light/dark + multi-tenant theming hook** (`frontend.md` #8.2) — implemented as a theme
   provider over the token set from step 2, not per-component conditional styling.
5. **Accessibility baseline** — semantic HTML, focus management for modals/menus, an
   axe-core-based lint/test gate (decision: `eslint-plugin-jsx-a11y` at lint time,
   `vitest-axe` at test time — both free, no approval needed beyond "yes, add this dev tool,"
   flagged for form only, not blocking).

**Until the design arrives**, Phase F0 can still fully complete items 2 (structure only,
placeholder values), 3 (component API design — a `Button` component's props/variants can be
designed before its exact colors are known), 4 (the mechanism), and 5. Only the _actual_ colors,
type scale values, and pixel-perfect component visuals wait on you.

### 3.2 Data-fetching & mutation conventions

One convention, applied by every feature, decided once:

- **Query keys**: `[resource, 'list', paramsHash]` / `[resource, 'detail', id]` — hashed params
  so a filter/sort/page change is a cache-key change TanStack Query already handles correctly.
- **Pagination consumption**: a `usePaginatedQuery(resource, params)` wrapper over the backend's
  exact `OffsetPage`/`CursorPage` envelopes (already typed in `shared/api/types.ts`) —
  built once in F0, reused by every list-view feature (F1, F3, F4–F6, F8, F9).
- **Mutations**: every create/update invalidates the exact query keys it affects (not a blanket
  `invalidateQueries()`), and every mutation surfaces backend `ApiError.details`/`reason` (the
  CR-1/D4/D5 error codes already carry a `reason`/`requiredAction` — the UI must surface these
  verbatim for Parent-Pays-expired-style denials, not a generic "error occurred").
- **Optimistic updates**: explicitly **not** used for anything CR-1/D4/D5/RBAC-gated (a denied
  mutation must never flash success before the server disagrees) — allowed only for pure
  UI-state actions with no server-authorization dimension (e.g., marking a notification read
  client-side pending confirmation, which the backend contract already treats as idempotent).

### 3.3 Form handling — decision needed, low-stakes

**Proposal: React Hook Form + Zod.** Why: every create/edit screen across nine feature modules
needs the same shape (typed schema, field-level errors, submit-disabled-while-pending) — RHF is
the de facto standard for this in the React ecosystem, Zod schemas double as the runtime
validation _and_ the TypeScript type source (one definition, not two), and both are MIT-licensed
with no server/paid component. This is exactly a "routine technical implementation decision" I'd
normally just make — flagging it once here for visibility since it affects every remaining
phase, then proceeding without asking again per your own instruction.

### 3.4 Data table / list-view strategy — decision needed, low-stakes

**Proposal: TanStack Table** (headless — pairs with whatever the design system's actual table
visuals turn out to be, once §3.1 unblocks). Why: every list-view feature needs sortable
columns, and the backend's own `?sort=field`/`?sort=-field` convention maps directly onto
TanStack Table's sorting state — building this once as a `<DataTable columns sortState
onSortChange />` wrapper in F0 means F1–F9 each write a column definition, not table logic.
Same "routine decision, flagged once" treatment as §3.3.

### 3.5 Notification/toast system

A single global toast/banner system (built in F0, no external dependency needed — a small
Zustand-backed queue + a portal-rendered component is sufficient for this scope) for mutation
success/failure feedback, separate from the in-app Notification _feature_ (C7) — these are two
different things (ephemeral UI feedback vs. the persisted `Notification` domain object) and
must not be conflated.

### 3.6 Permission-aware rendering — a real, flagged limitation

`GET /auth/me` / the login response's `PrincipalResponse` exposes **role and region_ids only —
never a resolved permission list.** The backend's actual authorization unit is a _permission
string_ (`role_permissions` table, e.g. `"iam.users.read"`), and only the backend can correctly
resolve which permissions the current role has (that resolution itself can change without a
frontend deploy, in principle). The frontend therefore can only gate UI by **role**, a coarser
signal, via `RouteGuard`'s existing `allowedRoles` and a small `useHasRole(...)` helper — this is
already how `RouteGuard` is built and I am not changing that design. **This is a real
architectural gap, not a frontend oversight**: a future backend addition (e.g., `GET
/auth/permissions` or embedding a resolved permission list in `PrincipalResponse`) would let the
frontend hide/show controls by exact capability instead of by role approximation. I'm not adding
that endpoint unilaterally — it's a backend API surface change, which is exactly an
architectural decision I should flag rather than build around. Noted in the Decision Log (§13)
as optional, non-blocking (role-based gating is a normal, shippable pattern; this is a
"could be better," not a "currently broken").

### 3.7 Responsive & layout strategy

Founder/Regional Manager/Support/Finance/Org Admin dashboards are **desktop-first, data-dense
admin tooling** (per Project Brief §11.4's own responsibility list: dashboards, device
management, reports — none of that reads as mobile-primary). I will still build every template
mobile-_safe_ (no horizontal scroll traps, tables that collapse to cards below a breakpoint)
because Org Admins plausibly check the dashboard from a tablet on-site, but I am not building a
mobile-first admin experience — that would contradict the product's own stated audience.
Breakpoint values themselves are one more thing that arrives with the design (§0); the
_strategy_ (desktop-first, graceful tablet degradation, no phone-optimized admin UI) does not
need to wait.

### 3.8 Testing pyramid — decision needed, low-stakes

**Proposal:**

- Unit (already decided): Vitest + RTL, per component/hook/store.
- Integration: **MSW (Mock Service Worker)** to mock REST at the network boundary in tests
  (renders real components against a real fetch call intercepted at the network layer, not a
  hand-mocked `apiRequest` — catches serialization mistakes RTL-with-jest-mocks would miss). For
  WebSocket integration tests, a lightweight fake `WebSocket` global (the same pattern the
  backend's own `FakeConnection` used) — no library needed.
- E2E: **Playwright**, added once there's a real page to click through (Phase F1's exit
  criteria, not F0's — no value in an E2E suite with nothing but a login screen). Chosen over
  Cypress for native multi-tab/WebSocket support, relevant to Live Monitoring and Notifications.
- No visual regression tool (Chromatic/Percy) proposed yet — both are paid services; flagged in
  the Decision Log as optional, not assumed.

### 3.9 Map provider — **stop, this needs your decision**

`frontend.md` #6 and Project Brief §11.8 both require the map to stay a pluggable provider
abstraction — meaning whichever provider I pick, it sits behind one `MapProvider` interface
Phase F7 depends on, not hardcoded into feature code. But _which_ provider to integrate first is
exactly a "paid external service must be selected" trigger you named yourself:

| Option                                                        | Cost model                              | Notes                                                                                                                                                    |
| ------------------------------------------------------------- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Mapbox GL JS**                                              | Free tier (50k loads/mo), paid beyond   | Best-in-class vector tiles, smooth realtime marker animation, widely used for fleet-tracking UIs specifically                                            |
| **Google Maps Platform**                                      | Pay-per-load beyond a small free credit | Most familiar to end users; billing setup (a Google Cloud project + card) is a heavier lift than Mapbox's                                                |
| **MapLibre GL + a free tile source (OSM/MapTiler free tier)** | Free                                    | Open-source Mapbox GL fork, zero vendor lock-in, no paid account needed to start — trades off polish/support for zero cost and zero procurement friction |

I am not choosing one of these for you. This blocks Phase F7 only — every other phase proceeds
regardless.

**Update, 2026-07-23 — F7 has a second, independent gate.** Beyond this provider decision, §4A's
B1 + B2 (the JT808 provisioning bridge and live tracking pipeline) must also reach a working state
before F7 can show real data. The two gates are unrelated — one a vendor/product choice, one an
engineering integration task — and can be resolved in parallel; see §4A for the full reasoning.

### 3.10 Shared cross-platform contract strategy — **architectural decision, needs your confirmation**

`shared/api-contracts/` and `shared/event-contracts/` already exist in this repo as empty
placeholders — someone already intended this seam. My proposal (detailed in §6): make the
backend's own FastAPI-generated OpenAPI schema the single source of truth, and generate typed
clients for both React (`openapi-typescript`) and Flutter (a Dart client generated from the same
spec, or a thin hand-written client if codegen quality proves poor — decided empirically in
Phase M0, not pre-committed here) from it. This avoids three hand-maintained copies of every DTO
(Python, TypeScript, Dart) silently drifting apart, which is precisely the class of bug this
whole codebase's own event-contract-conflict flags (§13.2 documentation gaps) already shows
happens when contracts aren't mechanically enforced. This is the kind of decision that
"permanently affects the platform" if wrong, so I'm surfacing it explicitly rather than just
doing it — see Decision Log §13. If you don't confirm it, the fallback is hand-maintained typed
DTOs per platform (what already exists in `frontend/src/shared/api/types.ts` today), which
remains a perfectly workable, just less mechanically-enforced, default.

---

## 4. React Web Dashboard — Phase Roadmap

Each phase lists Objective / Scope / Dependencies / Deliverables / Exit Criteria / Testing /
Complexity / Risks / Why-it's-ordered-here.

### Phase F0 — Design System & Cross-Cutting Infrastructure

- **Objective:** Everything in §3 becomes real code, once, before any feature module exists.
- **Scope:** Token/theme provider, primitive + composite component library (structure now,
  final visuals once §0 unblocks), `DataTable` wrapper, `usePaginatedQuery`, form conventions
  (RHF+Zod wiring), global toast system, `useHasRole`, responsive layout templates
  (`ListPageLayout`, `DetailPageLayout`, `DashboardShell`), MSW test setup, Playwright scaffold.
- **Dependencies:** None beyond the already-built app shell. Partially blocked on §0 for final
  visuals only.
- **Deliverables:** A component library with Storybook-less but test-covered stories (plain
  Vitest + RTL snapshot-free behavioral tests per component — no Storybook dependency proposed
  unless you want one; it's a nice-to-have, not load-bearing for this project's size).
- **Exit criteria:** Every primitive/composite component has a passing test; `ListPageLayout` +
  `DataTable` + `usePaginatedQuery` proven against one real endpoint (`GET /organizations` — the
  simplest list) end-to-end, including filter/sort/pagination round-tripping correctly against
  the live backend.
- **Testing:** Unit (every component), one integration test proving the pagination wrapper
  against a real (or MSW-mocked) `OffsetPage` response shape.
- **Complexity:** L. This is the phase everything else's velocity depends on — worth the
  investment.
- **Risks:** Under-investing here (skipping straight to feature screens) is the single biggest
  way this project ends up with nine inconsistent admin screens instead of one coherent app.
  Over-investing (building a component for every conceivable future need) is the opposite
  failure — I will build only what F1's actual screens need, extending as F2+ reveal new needs,
  not speculatively.
- **Why first:** Every other phase consumes this one's output directly.

### Phase F1 — Organization & Region Management (C2)

- **Objective:** Founder/Regional Manager/Support Staff can view and manage organizations and
  regions; Org Admin can view (not create) their own organization's settings.
- **Scope:** `GET/POST /organizations`, `GET/PATCH /organizations/{id}`, `GET/POST /regions` —
  list (paginated/filtered/sortable, using F0's wrapper), detail, create/edit forms.
- **Dependencies:** F0.
- **Deliverables:** `features/organizations/` — list page, detail page, create/edit modal or
  page (decided against the design once available; a slide-over vs. full-page form is a design
  call, not an architecture one).
- **Exit criteria:** A Founder can create an org, assign it a region, edit its billing model; a
  Regional Manager sees only their region's orgs (proving `RouteGuard`/role-gating end-to-end
  against a real scoped list); an Org Admin sees a read-only view of their own org only.
- **Testing:** Unit (form validation, list rendering), integration (MSW-mocked full CRUD flow),
  first Playwright E2E (login → create org → see it in the list).
- **Complexity:** M.
- **Risks:** Low — this is the most-scoped-down, best-documented context in the entire backend.
- **Why here:** Every other tenant-owned entity (vehicles, students, routes...) needs an
  `organization_id` to exist meaningfully; building this first means every subsequent phase has
  real org data to attach to, not a mocked placeholder ID.

### Phase F2 — User & Access Management (IAM, C1)

- **Objective:** In-scope admins manage user accounts.
- **Scope:** `GET/POST /users`, `GET/PATCH /users/{id}` (status/mfa transitions only, per the
  backend's own documented limits — the frontend must not offer a "change email" field the
  backend has no use-case for).
- **Dependencies:** F0, F1 (a user's organization picker needs F1's org list).
- **Deliverables:** `features/admin/users/` (folds into the existing `admin` feature folder,
  per the scaffold's own naming — there is no separate `iam`/`users` folder in the approved
  structure).
- **Exit criteria:** Founder invites a user, assigns a role + org, disables a user; role
  dropdown is restricted to what the backend's own role-creation rules allow (matching
  `CreateUserRequest`'s validated `role` values, not a hardcoded superset).
- **Testing:** Unit + MSW integration, one E2E (invite → user appears in list with correct role
  badge).
- **Complexity:** S–M.
- **Risks:** Low.
- **Why here:** Needs F1's org picker; nothing later needs this first, so it can also slide
  later without blocking anything if you want to prioritize differently — flagged as the most
  moveable phase in the sequence.

### Phase F3 — Fleet & Device Management (C3)

- **Objective:** Org Admin (+ RAAD staff in scope) manage vehicles and devices, including the
  device↔vehicle assignment lifecycle.
- **Scope:** `GET/POST /vehicles`, `GET/PATCH /vehicles/{id}`, `GET/POST /devices`,
  `GET/PATCH /devices/{id}`, `POST /devices/{id}/activate`, `/assign`, `/reassign`, `/unassign`.
- **Dependencies:** F0, F1 (vehicles/devices belong to an organization).
- **Deliverables:** `features/fleet-devices/` — vehicle list/detail, device list/detail, an
  assignment action (a distinct, explicit UI action — "assign device to vehicle" — not folded
  silently into a form field, matching the backend's own explicit-command modeling).
- **Exit criteria:** Register a vehicle, register a device, assign the device to the vehicle,
  see the one-active-assignment-per-device/vehicle invariant reflected in the UI (attempting a
  second assignment while one is active surfaces the backend's real `ConflictError`, not a
  silent no-op).
- **Testing:** Unit + MSW integration covering the conflict-error display path specifically
  (a safety-adjacent invariant, worth its own explicit test per `testing.md` #3's spirit even
  though this specific one isn't in the four named CR-1/D4/D5/tenant-isolation invariants).
- **Complexity:** M.
- **Risks:** The assignment lifecycle has real state (active/inactive) that must be visually
  unambiguous — a design risk more than a technical one, revisit once §0 unblocks.
- **Why here:** Transport Operations' `Trip.vehicle_id` and `Driver` reference this context;
  building it first means Trip/Route screens (F5–F6) have real vehicles to pick from.

### Phase F4 — Transport Operations, Part A: Students, Parents, Linking (C4)

- **Objective:** Org Admin manages students and parents and the link between them.
- **Scope:** `GET/POST /students`, `/parents`, the `student_parents` link
  (`GET/POST /students/{id}/parents`, `DELETE .../parents/{id}`).
- **Dependencies:** F0, F1.
- **Deliverables:** `features/transport-ops/students/`, `.../parents/`.
- **Exit criteria:** Enroll a student, register a parent, link them, see the link reflected on
  both the student's and parent's detail views.
- **Testing:** Unit + MSW integration; E2E for the link flow specifically (a two-entity
  relationship is the first genuinely relational UI in the roadmap, worth proving early).
- **Complexity:** M.
- **Risks:** Low.
- **Why here, and why split from Part B/C:** `transport_ops` is this codebase's largest bounded
  context (six aggregates) — one phase covering all of it would be the single largest, riskiest
  phase in the roadmap. Splitting by the backend's own aggregate boundaries (Student/Parent →
  Driver/Route → Trip/StudentAssignment) keeps each slice reviewable on its own, mirroring how
  the backend itself was built incrementally per aggregate, not as one `transport_ops` mega-PR.

### Phase F5 — Transport Operations, Part B: Drivers, Routes & Stops (C4)

- **Objective:** Org Admin manages drivers and routes (with ordered stops).
- **Scope:** `GET/POST /drivers`, `GET/POST /routes`, `GET/POST /routes/{id}/stops`.
- **Dependencies:** F0, F1, F3 (a Driver links to an `iam.User`; not strictly to Fleet, but
  sequenced after F3 so the "assign a driver to a vehicle via a trip" mental model in F6 already
  has both sides built).
- **Deliverables:** `features/transport-ops/drivers/`, `.../routes/` (with an ordered
  stop-list editor — drag-to-reorder is a real UX need here, `Route.stops` is
  `sequence_no`-ordered).
- **Exit criteria:** Register a driver, create a route, add stops, reorder them (client-side
  reorder UI — note `Route.move_stop`/`remove_stop` have **no HTTP route yet**, per CLAUDE.md's
  own flagged gap; the frontend can only add stops and view order this phase, not reorder or
  remove — building a reorder UI against a non-existent endpoint would be exactly the kind of
  "invent ahead of an approved backend surface" this project's own discipline forbids. Flagged,
  not silently worked around).
- **Testing:** Unit + MSW integration.
- **Complexity:** M.
- **Risks:** The stop-reorder gap above is a real, user-visible limitation — worth a clear "why
  can't I reorder stops" UI affordance (a disabled/tooltip state) rather than just omitting the
  feature invisibly.
- **Why here:** Routes/Stops are needed by Trips (F6) and by Live Monitoring's route
  visualization (F7).

### Phase F6 — Transport Operations, Part C: Trips & Student Assignments (C4)

- **Objective:** Org Admin schedules trips and manages the CR-1 access gate
  (`StudentAssignment`).
- **Scope:** `GET/POST /trips`, `/trips/{id}/start`, `/end`, `PATCH /trips/{id}/driver`,
  `GET/POST /student-assignments`, `/student-assignments/{id}/end`.
- **Dependencies:** F0, F1, F3, F5 (needs vehicles, drivers, routes to exist first).
- **Deliverables:** `features/transport-ops/trips/`, `.../student-assignments/`. The
  Driver-ownership check the backend added (`_ensure_driver_owns_trip`) has no frontend
  consequence beyond "a Driver never sees this screen at all" (it's Org-Admin-only per API
  Contracts, and Drivers are Flutter-only per Project Brief §4.7 — there is no web-dashboard
  Driver experience to build here at all, confirmed by re-reading the role list).
- **Exit criteria:** Schedule a trip, assign a driver, start/end it via the admin view (distinct
  from the Driver's own Flutter start/end controls — this is the Org Admin's oversight view,
  not a duplicate of the Driver app), create a student assignment (the CR-1 gate), end it.
- **Testing:** Unit + MSW integration; explicit test that the UI correctly displays the CR-1
  gate's current state (active/removed/transferred/graduated/disabled) since this directly
  drives whether a parent will see live tracking — a safety-adjacent display, worth the same
  seriousness `testing.md` #3 gives the backend equivalent.
- **Complexity:** L (the largest single slice — six write actions plus two related aggregates).
- **Risks:** This is where "trip_students roster" (documented as not-built backend-side) would
  have been useful for showing which students are on a given trip — it isn't built, so the Trip
  detail view cannot show a student roster this phase. Flagged, not invented around.
- **Why here:** Completes the bounded context; Live Monitoring (F7) needs real Trips to exist to
  have anything meaningful to track.

### Phase F7 — Live Monitoring & Maps (C5) — **gated on §3.9's map decision**

- **Objective:** Org Admin 24/7 fleet view; Parent live-GPS-during-active-trip view (the Parent
  _web_ experience — re-check: Project Brief and every rule file place Parent tracking on
  **mobile**, not web; the web dashboard's Live Monitoring is Org-Admin/RAAD-staff only,
  confirmed against `frontend.md`/Project_Brief §11.4's responsibility list which names no
  Parent-facing web screen at all). This phase is **Org Admin/RAAD staff only** on the web.
- **Scope:** `GET /tracking/vehicles/{id}/latest`, `GET /tracking/trips/{id}/positions`
  (cursor-paginated), `/ws/tracking` live subscription, route/stop overlay (reusing F5's route
  data), geofence display.
- **Dependencies:** F0, F3 (vehicles), F5 (routes/stops), F6 (trips) for context; the map
  provider decision (§3.9); honest handling of §2.2's "no live data source connected yet" state.
  **Updated 2026-07-23:** also gated on §4A's Backend Integration Track — specifically B1 (JT808
  Provisioning Bridge) and B2 (Live Tracking Pipeline) reaching a working state, so this UI has a
  real data source rather than only synthetic/manual test events. This gate runs in parallel with
  F5/F6, not sequentially before F7, and is independent of the map-provider decision above.
- **Deliverables:** `features/live-monitoring/` — a `MapProvider` abstraction (interface first,
  concrete adapter second, matching the backend's own Ports & Adapters discipline exactly) so
  swapping providers later never touches feature code; live marker updates via the existing
  `useWebSocketChannel` hook; a fleet-wide view and a per-vehicle detail view.
- **Exit criteria:** Subscribing to a vehicle via the WS hook renders position updates on the
  map in real time **when real data exists**; when it doesn't (today, in this environment), the
  UI shows a clear "no live position data" state — never a stale or fabricated marker
  (`flutter.md` #6's honesty principle, applied to web too, since the same safety reasoning
  applies regardless of platform).
- **Testing:** Unit (map component logic, mocked provider), integration (fake WebSocket
  publishing synthetic position events, proving the render pipeline end-to-end without needing
  the real device plane), no E2E against a real map vendor's live tiles (flaky/costly) — E2E
  covers the surrounding chrome (subscribe, connection-status indicator) with a mocked map.
- **Complexity:** L.
- **Risks:** The biggest technical risk in the entire React roadmap — realtime rendering
  performance (many markers, frequent updates), map provider lock-in if the abstraction isn't
  disciplined, and the ETA-calculation gap (§2.5) meaning any "ETA" UI element this phase would
  need to either omit ETA entirely (honest, recommended) or stub it pending a backend design.
- **Why here, not earlier:** Needs F3/F5/F6's data to be meaningful, and needs the map decision
  which only you can make.

### Phase F8 — Notifications Center (C7)

- **Objective:** Any authenticated user sees their own in-app notifications, live via WebSocket.
- **Scope:** `GET /notifications` (cursor-paginated), `GET /notifications/{id}`,
  `POST /notifications/{id}/read`, `/ws/notifications`.
- **Dependencies:** F0. Notably **not** dependent on F1–F7\*\* — this phase is nearly
  self-contained (personal-ownership-scoped, not tenant-scoped) and could run in parallel with
  F3–F7 if you want to reprioritize.
- **Deliverables:** `features/notifications/` — a notification center/inbox, a header bell/badge
  (part of `DashboardLayout`, F0's shell) wired to the live WS channel.
- **Exit criteria:** A `NotificationCreated` event (once the Notification Worker is actually
  running against a real broker — see backend's own known gap) appears live without a page
  refresh; falls back gracefully (poll-free, just quiet) when no broker is configured, matching
  this environment's current honest state.
- **Testing:** Unit + MSW/fake-WS integration; explicit test for the ownership boundary (a
  notification for another user must never render — mirrors the backend's own explicit
  ownership test).
- **Complexity:** S–M.
- **Risks:** Low — the smallest, most self-contained phase after F0.
- **Why here:** Placed after the entities notifications reference (trips) exist, purely for a
  richer demo; technically movable earlier if you want quick, low-risk visible progress.

### Phase F9 — Billing & Subscriptions (C8)

- **Objective:** Org Admin/Finance Staff view plans/subscriptions/invoices; initiate payment.
- **Scope:** `GET /billing/plans`, `/subscriptions`, `/invoices`, `POST /billing/payments`
  (requires the `Idempotency-Key` header — a real frontend responsibility, generate a UUID
  client-side per submit-attempt, not per-render).
- **Dependencies:** F0, F1 (org-scoped).
- **Deliverables:** `features/billing/`.
- **Exit criteria:** View current plan/subscription/invoices; initiate a payment and see it move
  to `PENDING` — **it will never complete**, since `PaymentProviderPort` is unbound backend-side
  by design. The UI must show this honestly (a "payment processing" state that's accurate, not
  a fake success), exactly matching the backend's own "fail loudly, don't fake it" posture.
- **Testing:** Unit + MSW integration, explicit test that the idempotency key is regenerated per
  attempt and reused correctly on a retry of the _same_ attempt (not a new key on every render).
- **Complexity:** M.
- **Risks:** Building a full "payment succeeded" UI flow would be building against a capability
  that doesn't exist — scope this phase to what's real (initiate, see pending, see the
  provider-not-configured failure honestly) and stop there until a `PaymentProviderPort` adapter
  exists.
- **Why here:** Not blocking anything else; could move earlier or later freely.

### Phase F10 — Video (C6)

- **Objective:** Org Admin launches live/playback video sessions.
- **Scope:** `POST /video/live`, `/playback`, `/sessions/{id}/stop`.
- **Dependencies:** F0, F3 (device/camera), and a bound `VideoProviderPort` adapter
  **backend-side** — without one, every call in this phase's scope raises
  `NotImplementedError` by design.
- **Deliverables:** A minimal session-control UI (request/stop) that is honest about "no video
  provider configured" until the backend has one. **Not** a video player component — building a
  real player against a stream URL that will never arrive this phase is speculative work with no
  payoff until the backend side is real.
- **Exit criteria:** UI correctly reflects "video not available" without crashing or faking a
  stream; the moment a real adapter exists backend-side, this phase's own follow-up (adding the
  actual player, likely WebRTC per `jt1078.md` #5) becomes concrete, scoped work.
- **Testing:** Unit (D5 enforcement — a non-Org-Admin role must never even see this route,
  proven at the frontend `RouteGuard` layer as defense-in-depth on top of the backend's own
  unconditional `enforce_d5`).
- **Complexity:** S (deliberately minimal, given the backend gap).
- **Risks:** None if scoped as above; real risk only if someone tries to build the full player
  ahead of the backend capability.
- **Why here, last among "real" feature phases:** Directly gated on a vendor decision that
  isn't mine or yours to make lightly (a real paid vendor contract, almost certainly) — parked
  deliberately, not forgotten.

### Phase F11 — Reporting & Analytics (C9)

- **Objective:** Requesters (role-appropriate) request reports and check status.
- **Scope:** `POST /reports/runs`, `GET /reports/runs/{id}`.
- **Dependencies:** F0, plus every other context (a report is only useful once there's real
  data across the platform to summarize) — hence sequenced late by nature, not by arbitrary
  choice.
- **Deliverables:** A request form (`definition_key` as a free-text/opaque field, matching the
  backend's own deliberate non-invention of a closed report-type enum) and a status poller
  (no list endpoint exists backend-side, so no report history list is possible this phase).
- **Exit criteria:** Request a report, see it reach `failed` honestly (no `ReportRendererPort`
  bound backend-side, by design) — same "no fake success" discipline as F9/F10.
- **Testing:** Unit + MSW integration.
- **Complexity:** S.
- **Risks:** Low; genuinely low-value to build much further until `ReportRendererPort` and the
  `ReportDefinition` documentation gap (CLAUDE.md's own flagged item) are resolved.
- **Why here:** Naturally last of the "real" data-facing features — has nothing to summarize
  until the rest exists.

### Phase F12 — Platform & Audit (C10)

- **Objective:** Founder/in-scope admins view the audit log and manage system settings.
- **Scope:** `GET /admin/audit` (paginated/filterable — a great showcase of F0's `DataTable`
  against a real, data-rich endpoint), `GET/PATCH /admin/settings`.
- **Dependencies:** F0 only, technically — this is one of the most parallelizable phases in the
  whole roadmap (no feature dependency on any other bounded context's data).
- **Deliverables:** `features/admin/audit/`, `.../settings/`.
- **Exit criteria:** Founder filters the audit log by actor/action/entity type, edits a system
  setting.
- **Testing:** Unit + MSW integration.
- **Complexity:** S.
- **Risks:** None notable.
- **Why here, not earlier:** Purely a sequencing convenience (low urgency, not low readiness) —
  genuinely movable to run in parallel with F3–F9 if you want a quick low-risk win alongside the
  bigger phases.

### Phase F13 — React Production Readiness

- **Objective:** CI-gated, deployable web dashboard.
- **Scope:** Fill `.github/workflows/frontend-pipeline.yml` (currently absent — only the
  cross-deployable index `ci-cd/pipelines/frontend-pipeline.yml` exists, empty, mirroring
  exactly how the backend's own real CI lives under `.github/workflows/`, not
  `ci-cd/pipelines/`) with build → typecheck → unit test → E2E-against-a-preview-build. Bundle
  size budget, Lighthouse/perf budget (informational at first, gating once a baseline exists,
  mirroring how the backend's own load tests are "documented, not yet a hard gate"). Error
  tracking (a real "paid external service" decision if Sentry-class tooling is wanted — flagged,
  not assumed) or a minimal self-hosted alternative.
- **Dependencies:** All prior React phases functionally complete enough to be worth gating.
- **Deliverables:** A real, green CI pipeline; a documented deployment target (**none is chosen
  anywhere in this repository today** — same honest gap the backend's own CI file already
  states for itself; choosing a host is its own decision, likely bundled with the
  infrastructure/deployment phase across all deployables, not a frontend-only choice).
- **Exit criteria:** A PR against `frontend/` triggers CI; CI fails on a real regression;
  build artifact is deployable (to wherever is eventually chosen).
- **Testing:** The pipeline _is_ the deliverable here.
- **Complexity:** M.
- **Risks:** Deployment target selection is bigger than "frontend" — likely wants its own
  cross-deployable phase (backend + frontend + mobile + the two device-plane services all need
  a hosting decision eventually). Flagged in §9.
- **Why last among React phases:** No point gating CI on features that don't exist yet.

---

## 4A. Backend Integration Track — JT808 Device-Plane Bridge (Parallel Workstream)

**Update, 2026-07-24 — real hardware analysis changes what B1/B2 actually build, not their
objectives.** `docs/vendor/HARDWARE_ANALYSIS.md` and `docs/architecture/adr/
0009-mdvr-vendor-protocol-device-plane.md` establish that the actually-procured MDVR hardware
(Shenzhen Tianyou / "LSZ", `LSZ-C5804DG-Q-F`) is not JT/T 808/1078-compliant — it speaks its own
proprietary protocol. B1 and B2 below are **retitled in spirit, not in objective**: "a physical
device can authenticate" (B1) and "a device's GPS reports become a persisted row and a live map
update" (B2) still stand exactly as written; what changes is that both are now implemented against
`services/jt808/src/vendors/lsz_mdvr/` (a new, parallel protocol/dispatcher/handlers stack inside
the same `services/jt808/` deployable, per ADR-0009 — the existing JT/T 808 code is kept, dormant,
untouched) rather than literal JT/T 808 message IDs/framing. Every architectural property B1/B2
were already designed around — event-only communication with the business plane, the
`DevicePositionReported` event shape, Redis-backed session state, the outbox/broker publish
pattern — is unchanged. Where this update revises a specific sub-bullet below with real
consequence (the auth-key/credential assumption `DeviceProvisioningPort.verify_auth_code` made,
which this hardware cannot satisfy), it is flagged inline rather than silently reinterpreted.

**Numbered "4A," not inserted as a renumbered §5.** This section sits between §4 and §5 in the
document but is deliberately not a subsection of the React roadmap — renumbering every subsequent
section (§5–§12) to fit it into strict sequence would touch dozens of this document's own existing
`§N` cross-references for no real benefit. "4A" makes its peer (not child) relationship to §4/§5
explicit while leaving every citation elsewhere in this document valid.

**Decided 2026-07-23 (see §11 Decision Log item 7).** The platform runs **three parallel
engineering tracks**, not two: Frontend (§4, React), **Backend Integration (this section)**, and
Mobile (§5, Flutter). This is the same reasoning that already lets Flutter proceed alongside React
(§7's parallelization map): the work in this section has **zero dependency on any React feature
phase**, because the backend bounded contexts it touches (`fleet_device`, `tracking`) are already
complete end-to-end (see CLAUDE.md's own "Repository Status"). This track closes device-plane
_integration_ gaps that CLAUDE.md and the JT808 Technical Design (Phase 3.4) already flagged — it
is not new business logic, and it does not belong inside the React phase sequence.

**This track is explicitly _not_ sequenced before or after F5/F6.** F5 (Drivers, Routes & Stops)
and F6 (Trips & Student Assignments) are frontend CRUD against already-built, already-tested
backend endpoints — nothing in this track blocks them, and nothing in F5/F6 blocks this track. It
runs **concurrently** with both, starting now.

**Phase F7 (Live Monitoring & Maps) has two independent gates, not one:**

1. The map-provider decision (§3.9) — a vendor/product choice, unchanged by this update.
2. **This track's B1 + B2 reaching a working state** — an engineering integration task, newly
   tracked here.

Neither gate depends on the other; both must clear before F7 can show a real, moving bus rather
than its own honestly-labeled "no live data source connected" state (§2.2). Resolving both in
parallel, on separate tracks, gets F7 to a real demo fastest — the same reasoning §2.2 already
applied to justify building F7 against synthetic data rather than waiting.

**B3 (Video Integration) is grouped into this same track for organizational reasons only** — both
B1/B2 and B3 are device-plane integration work — but B3 does **not** gate F7. It gates F10 (Video,
§4) exactly the way B1/B2 gate F7. This distinction is kept explicit below rather than implying B3
blocks live tracking, which it does not.

---

### B1 — JT808 Provisioning Bridge

- **Objective:** A physical device registered through the dashboard can actually authenticate
  against the JT808 service. This closes the single largest gap this codebase's own device-plane
  analysis surfaced: `DeviceProvisioningPort`'s only bound implementation today,
  `NullDeviceProvisioningPort`, is deliberately fail-closed — every registration/authentication
  attempt currently fails, regardless of what's in the `devices` table.
- **Scope:**
  - **Device authentication (auth secret) — revised, 2026-07-24:** `devices.auth_key_hash`/
    `DeviceProvisioningPort.verify_auth_code` assumed a credential the actual procured hardware's
    protocol does not have at all (`docs/vendor/HARDWARE_ANALYSIS.md` §11: no cryptographic
    auth mechanism of any kind — registration trust is serial-number-allowlist only). The
    vendor-specific provisioning port (`vendors/lsz_mdvr/handlers/provisioning_port.py`)
    authorizes by serial number only; the missing cryptographic assurance is a real, accepted,
    flagged gap pending a network-layer compensating control (`.claude/rules/security.md` #9),
    not silently closed. `auth_key_hash` stays in the schema, unused by this vendor's bridge, for
    a future JT/T-808-compliant vendor that can actually satisfy it.
  - **`DeviceProvisioningPort` implementation:** a real adapter answering `authorize_registration`
    only (this vendor's single-step registration has no separate authentication message to
    verify a code against, unlike JT/T 808's `0x0100`/`0x0102` split) — replacing the fail-closed
    Null default.
  - **Device registry synchronization:** the read-model/event feed the device-plane service needs
    to resolve `serial_number → device/vehicle/organization` locally, **without** a forbidden
    synchronous cross-service DB read (`.claude/rules/architecture.md` #3) — a local projection
    kept current by consuming `fleet_device`'s own already-emitted `DeviceRegistered`/
    `DeviceActivated`/`DeviceAssignedToVehicle` domain events. **A real, previously-unflagged gap
    surfaced while implementing this:** `device_registered`'s event payload carries `terminal_id`
    but not `serial_number` — the field this vendor's protocol actually keys on — so the event
    needs a small, additive payload field added before this projection can be populated from it.
  - **Redis session management:** JT808's `DeviceSessionRegistry` is in-memory, single-node only
    today; `.claude/rules/jt808.md` #4 requires Redis as the authoritative, cross-shard session
    store this device-plane service needs for real horizontal scale.
- **Dependencies:** None from the React or Flutter tracks. Depends only on already-complete
  backend work (`fleet_device`'s domain events; ADR-0008's Redis Streams instance being reachable
  from the JT808 deployable).
- **Deliverables:** A bound, real `DeviceProvisioningPort` adapter; a local device-registry
  projection inside `services/jt808/`; a Redis-backed `DeviceSessionRegistry`; the exposed
  auth-secret field, end to end (form → API → domain → DB).
- **Exit criteria:** A device registered in the dashboard, with its auth secret set, can complete
  `0x0100`/`0x0102` registration and authentication against a running JT808 instance and reach
  `Online` state — proven against a real or simulated terminal, not unit tests alone.
- **Testing:** Unit tests for the new provisioning adapter and registry projection, matching
  `services/jt808/tests/`'s existing conventions; an integration test driving a simulated terminal
  through register → authenticate → online, the device-plane equivalent of this codebase's own
  `test_realtime_broker_fanout.py` precedent.
- **Complexity:** M.
- **Risks:** The device-registry-synchronization design (event-consumption vs. a cached
  projection) is the one genuinely open technical question here — flagged, not pre-decided, since
  ADR-808-4 names the requirement without specifying the exact mechanism.

### B2 — Live Tracking Pipeline

- **Objective:** A real, authenticated device's GPS reports become both a persisted history row
  and a live map update. This closes the second gap the same analysis surfaced: JT808's own event
  publisher is `LoggingEventPublisher` (a log-only stub), and the Business API's own
  `tracking/events/subscribers.py` is empty.
- **Scope:**
  - **Event publishing:** a durable local outbox in `services/jt808/` (ADR-808-2) plus an
    approved broker client, replacing `LoggingEventPublisher`, so `device.position_reported`/
    `device.online`/`device.offline`/alarm events are actually delivered, not merely logged.
  - **Redis Streams integration:** publishing onto the **same** Redis Streams instance the
    Business API already uses (ADR-0008), reusing existing infrastructure rather than standing up
    a second broker. Approving a broker-client dependency for the JT808 deployable specifically is
    still a `.claude/rules/workflow.md` #1/#2 checkpoint even though the Business API already has
    precedent — a new deployable's own dependency manifest, not an automatic inheritance.
  - **Tracking consumer:** implementing `tracking/events/subscribers.py` to consume
    `DevicePositionReported` and call `TrackingApplicationService.record_vehicle_position`.
    **A field-name mismatch must be reconciled here, not discovered later:** JT808's
    `DevicePositionReported` dataclass uses `latitude`/`longitude`; the already-built
    `/ws/tracking` handler reads a broker payload using `lat`/`lng` per the documented wire
    contract. Nothing today reconciles these two.
  - **Latest position cache:** JT808 writing `vehicle:{id}:last` directly to Redis (ADR-808-6) —
    a separate write path from the broker publish above, needed for
    `GET /tracking/vehicles/{id}/latest`'s instant reads (e.g. the map's initial center-on-load,
    before any WebSocket event has arrived).
  - **Vehicle position persistence:** the already-built, already-tested `vehicle_positions`
    table/repository simply starts receiving real rows once the consumer above exists — no
    schema or repository work is needed here, only the consumer that calls it.
- **Dependencies:** B1 (a device must be able to authenticate before it can report positions).
  `/ws/tracking`'s own consumer side (the `ws-tracking` `BrokerFanOutWorker`) is **already built**
  and needs no changes — it starts receiving real frames the moment this phase's publish side
  lands.
- **Deliverables:** JT808 outbox + broker client; `tracking/events/subscribers.py` implemented;
  JT808's direct `vehicle:{id}:last` Redis write; the `latitude/longitude` ↔ `lat/lng`
  reconciliation resolved at the one boundary that needs it.
- **Exit criteria:** A simulated or real terminal's `0x0200` location report results in: a
  persisted `vehicle_positions` row, an updated `vehicle:{id}:last` Redis key, and a live frame
  delivered to a subscribed `/ws/tracking` client — proven end-to-end, not stage-by-stage only.
- **Testing:** Unit tests per new component (outbox, consumer); an end-to-end integration test
  simulating a terminal's position report through to a WebSocket frame, extending
  `tests/integration/test_realtime_broker_fanout.py`'s existing pattern rather than inventing a
  new one.
- **Complexity:** M.
- **Risks:** None structural — every consuming component on the Business API side (`/ws/
  tracking`, `vehicle_positions`) already exists and is tested; the risk is entirely in getting
  the publish side (JT808 outbox/broker) correctly durable, the same reliability bar
  `SqlOutboxPublisher` already meets on the Business API side.

### B3 — Video Integration

- **Objective:** Close the device-plane half of Video (C6) that F10 (§4, React) cannot itself
  close — F10 is scoped deliberately thin (session-control UI only, no player) precisely because
  `VideoProviderPort` has no bound adapter today. This phase is where that adapter is built.
- **Scope:**
  - **MDVR vendor API integration:** a bound `VideoProviderPort` adapter — matching the
    already-chosen architecture exactly (CLAUDE.md: "native JT1078 is explicitly not
    implemented... built around a `VideoProviderPort` abstraction (MVP: a hardware/vendor video
    API)"). This is Decision Log item 3 (§11) actually being executed, not a new decision.
  - **Camera management:** an HTTP route for `RegisterCameraCommand` — already implemented at the
    application layer, with **no approved endpoint** yet (flagged in
    `modules/fleet_device/api/routers.py`'s own module docstring). This phase closes that gap.
  - **Live video streaming integration:** wiring the vendor adapter's actual stream
    negotiation/token issuance behind the three existing routes (`POST /video/live`, `/playback`,
    `/sessions/{id}/stop`), which already enforce D5 via `enforce_d5`/`VideoAccessPolicy` — this
    phase supplies the provider behind that gate; it does not touch the gate itself.
  - **Video session management:** largely **already built** — `VideoSession`
    (`request_live`/`request_playback`/`activate`/`end`/`fail`) is a complete, tested aggregate.
    Listed here for completeness, not because new domain work is expected.
  - **Video player integration:** this is F10's own frontend scope (§4), **not** new backend
    work — flagged explicitly here rather than silently duplicated, since building a real player
    only becomes meaningful once this phase's vendor adapter exists. B3 unblocks F10's follow-up
    player work; it does not replace it.
- **Dependencies:** None on B1/B2 or F5–F7 — Video is its own bounded context, genuinely
  independent of the live-tracking half of this track. Bundled into the same parallel workstream
  only because both are device-plane integration work, not because one needs the other.
- **Deliverables:** A bound `VideoProviderPort` adapter; a camera-registration HTTP route (exact
  path per whatever API Contracts eventually documents — none exists today, see `fleet_device`'s
  own flagged gap); live stream tokens flowing through the existing, unchanged D5-gated routes.
- **Exit criteria:** An Org Admin's `POST /video/live` call returns a real, playable stream
  reference from the bound vendor adapter — not `NotImplementedError`.
- **Testing:** Unit tests for the new adapter (mocked vendor API). D5 enforcement is **not**
  retested here — `enforce_d5`/`VideoAccessPolicy` already have coverage and this phase doesn't
  touch them.
- **Complexity:** L — gated on an actual vendor contract/API, the same real-world procurement
  dependency F10 already names as its own biggest risk.
- **Risks:** **Hard-gated on the same vendor decision Decision Log item 3 already names** — this
  sub-phase cannot start in earnest before that choice is made, unlike B1/B2, which have no such
  external blocker. Do not schedule B3 assuming the same start date as B1/B2.

---

## 5. Flutter Mobile — Phase Roadmap

### Phase M0 — Flutter Foundation

- **Objective:** Mirrors F0, for mobile.
- **Scope:** State management decision (**Riverpod**, proposed — more testable than BLoC for a
  two-role app this size, less ceremony, still enforces the same
  presentation→domain→data layering `flutter.md` #5 requires; a routine decision, flagged once).
  Secure token storage (`flutter_secure_storage` — the standard, approved-by-necessity choice
  for "tokens in secure storage" per `flutter.md` #5), networking client, the shared design
  tokens from §3.1/§6 mapped into Flutter `ThemeData`, role-based app shell (Parent vs. Driver
  chrome, `flutter.md` #1).
- **Dependencies:** F0's tokens must exist in an extractable form (§6) — this is the one place
  Flutter genuinely waits on a React-side artifact, not on React _features_.
- **Deliverables:** `mobile/lib/app/`, `.../core/` populated; a role-based shell rendering
  "signed in as Parent/Driver" with no real feature screens yet.
- **Exit criteria:** App builds for both Android and iOS targets (simulator/emulator), real
  login against the backend, secure token storage proven (kill app, relaunch, session concerns
  handled per whatever pattern §6/M0 settles on — likely: refresh token in secure storage,
  access token in memory, mirroring the web's own in-memory-access-token posture as closely as
  a mobile app's different security model allows).
- **Testing:** Widget tests (Flutter's own `flutter_test`) for the shell/auth flow.
- **Complexity:** M.
- **Risks:** iOS build/signing friction is the classic Flutter-foundation risk — budget time for
  it, not code complexity.
- **Why first:** Mirrors why F0 is first for React.

### Phase M1 — Auth + Role Shell

Folded into M0 above in practice (auth IS the shell's first real behavior) — listed separately
here only because the user's own numbered list named authentication as its own topic. No
separate phase; M0's exit criteria already covers it.

### Phase M2 — Driver Experience

- **Objective:** Full Driver role per Project Brief §4.7/§8.4.
- **Scope:** View assigned vehicle/route/students/stops; Start/End Morning Trip; Start/End
  Afternoon Trip. **The app never streams the phone's GPS** (`flutter.md` #2,
  `mobile/README.md`'s own "important clarification") — trip start/end are pure state-machine
  commands (`POST /trips/{id}/start`/`/end`), not location-reporting actions.
- **Dependencies:** M0; React's F6 (Trips) having already proven the trip-lifecycle API
  integration removes most of the integration risk before Flutter touches it.
- **Deliverables:** `mobile/lib/features/driver/`.
- **Exit criteria:** A Driver logs in, sees their assignment, starts a trip, ends it; the trip
  state change is visible on the (React) Live Monitoring view in the same test session,
  end-to-end proof the two clients agree on the same backend state.
- **Testing:** Widget tests, one `integration_test` (Flutter's official on-device/emulator E2E
  package) covering start→end.
- **Complexity:** M.
- **Risks:** Low — smallest, most self-contained role experience.
- **Why before Parent:** Simpler (no live map, no payment status, no notification center) —
  proves the mobile networking/auth/state-management stack on the easier role first.

### Phase M3 — Parent Experience

- **Objective:** Full Parent role per Project Brief §4.8/§8.5.
- **Scope:** Assigned children list, live GPS map **during active trips only**
  (`flutter.md` #4), trip history (outside active trips), transport-payment status, in-app
  notification center + FCM push. **No live video, ever** (§2.5's D5 confirmation).
- **Dependencies:** M0, M2 (shares map/notification patterns first proven simpler on Driver
  where applicable), React's F7 (map provider decision + `MapProvider` abstraction pattern —
  reused conceptually, not literally, since Flutter needs its own map package, but the _same_
  provider choice for brand/data consistency) and F8 (notification integration pattern).
- **Deliverables:** `mobile/lib/features/parent/`.
- **Exit criteria:** Parent sees children, sees live GPS only while a trip is active (and a
  clear "not tracking — no active trip" state otherwise, never a stale marker —
  `flutter.md` #6), sees trip history and payment status, receives a push notification.
- **Testing:** Widget tests, `integration_test` for the active-trip-gating logic specifically
  (a safety/privacy-adjacent behavior worth its own explicit test, mirroring `testing.md` #3's
  spirit).
- **Complexity:** L — the most feature-rich mobile screen (map + history + payment + notifs).
- **Risks:** The CR-1/D4 access-decision UX (a denied Parent-Pays parent) needs the same honest
  "here's why, here's what to do" treatment the web's error-envelope surfacing gives it (§3.2) —
  don't let mobile silently show nothing when React shows a clear reason.

### Phase M4 — Push Notifications (FCM) — Cross-Cutting, Folds Into M2/M3

Not a separate phase — FCM registration (`POST /notifications/tokens`) and foreground/
background/terminated-state push handling are built as part of whichever of M2/M3 needs them
first (Parent, realistically, per §4.8's explicit "FCM push" requirement — Drivers have no
documented push requirement). Listed separately here only to answer the user's own numbered
topic list explicitly.

### Phase M5 — Offline Resilience & Mobile Production Readiness

- **Objective:** Graceful degradation (`flutter.md` #6, Project Brief §10.2 offline
  requirements) and a real CI/release pipeline.
- **Scope:** Cached last-known state with visible "last updated / stale" indicators; local
  cache for offline trip history; `.github/workflows/mobile-pipeline.yml` (build → widget tests
  → `integration_test`), app store / Play Store release process (a real logistics/account
  decision, not a code one — flagged, not assumed).
- **Dependencies:** M0–M3 functionally complete.
- **Deliverables:** A green mobile CI pipeline; documented (not necessarily executed, pending
  real store accounts) release process.
- **Exit criteria:** CI gates a mobile PR; offline mode demonstrably degrades visibly, never
  silently.
- **Testing:** The offline-degradation behavior gets its own explicit `integration_test` (kill
  network mid-session, verify the stale-indicator appears, never a silent stall).
- **Complexity:** M.
- **Risks:** App store review timelines are outside engineering control — budget calendar time,
  not just engineering time, once this phase is reached.
- **Why last:** Same reasoning as F13 — no point gating CI/release process on features that
  don't exist yet.

---

## 6. Shared Architecture Between React and Flutter

Dart and TypeScript share no runtime — genuine code-sharing (the way two React-based clients
might share a package) isn't possible. What's real, and what I'm proposing for each:

1. **API contract shape** — pending your confirmation (§3.10/§13): generate typed clients for
   both platforms from the backend's own FastAPI-generated OpenAPI schema, rather than
   hand-maintaining matching DTOs in three languages. `shared/api-contracts/` (already scaffolded,
   currently empty) becomes the landing spot for the generated/exported spec artifact itself.
   Fallback if not confirmed: continue hand-maintaining typed DTOs per platform, as today.
2. **Design tokens** — genuinely shareable as data. Once §3.1 produces a token set (JSON/YAML:
   colors, type scale, spacing, radii), React consumes it via a theme provider (§3.1 item 4) and
   Flutter consumes the _same file_ via a build-time or run-time mapping into `ThemeData` (a
   small, one-way generator script, not a runtime dependency on a JS toolchain from Dart). One
   source of truth, two renderers — the single most valuable, lowest-risk piece of cross-platform
   sharing available here, and the reason §3.1's methodology explicitly produces data, not just
   styled components.
3. **Domain vocabulary & business-rule parity** — CANNOT be mechanically shared (no shared
   runtime), but MUST be documented once. Proposal: a `shared/domain-glossary.md` (or extend
   `shared/README.md`, currently a stub) capturing exactly what "active trip," "CR-1 decision
   reasons," and the D1 notification catalogue mean for _display_ purposes — both
   implementations read the same prose, reducing (not eliminating) drift risk between a
   TypeScript `formatTripStatus()` and a Dart equivalent.
4. **Event contract vocabulary** — `shared/event-contracts/` (also already scaffolded, empty)
   is the natural home for the WebSocket wire-frame shapes (`{"type":"position",...}`,
   `{"type":"notification",...}`) both clients parse — again, documented as data/schema, not
   shared code, given the runtime split.
5. **What is NOT shared, deliberately:** state management (Zustand vs. Riverpod — different
   ecosystems, no benefit to forcing parity), component implementations (a React `Button` and a
   Flutter `Button` share a _token_, never a line of rendering code), routing (React Router vs.
   Flutter's own navigation — no cross-platform router exists that wouldn't be a worse fit for
   both than each platform's own idiomatic choice).

---

## 7. Parallelization Map

**Strictly sequential** (architecture-driven, not arbitrary): F0 before everything; F1 before
F3/F4 (org_id dependency); F3 + F5 before F6 (vehicle/route references); F6 before F7 (needs
real trips); §3.1's token extraction before M0.

**Can run in parallel today, once F0 lands:**

- F1 (Organizations) and F12 (Platform & Audit) — zero shared dependency.
- F2 (Users) can trail F1 by a few days, doesn't block anything downstream.
- F8 (Notifications) can run alongside F3–F6 entirely — it's personal-ownership-scoped, not
  tenant-data-dependent.
- F9 (Billing) has no hard dependency on F3–F7 either, beyond F1.
- **§4A's Backend Integration Track (B1/B2/B3) — added 2026-07-23.** Runs alongside F3–F6 with
  zero shared dependency in either direction, the same way F8/F9 do. Not sequenced before or
  after F5/F6; see §4A for the full reasoning.

**Can run in parallel once its specific prerequisite lands, not waiting for the full sequence:**

- M0 (Flutter foundation) can start the moment §3.1/§6 produce a token set — does not need to
  wait for F1–F13 to finish. This is the single biggest parallelization opportunity in the whole
  roadmap: **Flutter and the bulk of the React feature phases can proceed concurrently**, on
  two different people/sessions, once the shared token/contract seam (§6) is in place. M2/M3
  specifically benefit from F6/F7/F8 having already proven the relevant API integrations, but
  that's a risk-reduction argument, not a hard technical dependency — if you want maximum speed
  over maximum risk-reduction, M2 could start as soon as M0 is done.

**Three parallel tracks overall, as of 2026-07-23:** Frontend (React, §4), Backend Integration
(§4A), and Mobile (Flutter, §5) proceed concurrently once each track's own prerequisites are met
(F0 for React; nothing for §4A; §3.1/§6's token set for Flutter). F7 is the one point in the
roadmap where two of these three tracks' outputs (React's map UI and Backend Integration's B1/B2)
must both be ready before the feature is real — see F7's own entry and §4A for the full
dependency shape.

**Hard-gated on your decisions, not on engineering sequencing:** F7 (map provider), F10 (video
vendor), §3.10 (contract-codegen approach) — these three can sit idle without blocking anything
else in the roadmap. §4A's B3 (Video Integration) is additionally gated on the same F10 video
vendor decision — flagged in B3's own entry rather than repeated here.

---

## 8. Testing Strategy (Consolidated)

| Layer                      | React                                                                                                                                                                                                                      | Flutter                                                            |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Unit                       | Vitest + RTL                                                                                                                                                                                                               | `flutter_test`                                                     |
| Integration                | MSW (REST), fake-WS (realtime)                                                                                                                                                                                             | `integration_test` (on-device/emulator)                            |
| E2E                        | Playwright                                                                                                                                                                                                                 | `integration_test` (Flutter's own E2E story covers this layer too) |
| Contract                   | Codegen-diff against the backend's OpenAPI schema (pending §3.10)                                                                                                                                                          | Same                                                               |
| Safety-critical invariants | CR-1/D4/D5 display-correctness explicitly tested per feature that touches them (F6 assignment states, F7 tracking visibility, F10 D5 route-guard) — mirrors `testing.md` #3's backend requirement, applied to presentation |
| Visual regression          | Not proposed (paid tooling) — flagged in Decision Log as optional                                                                                                                                                          | N/A                                                                |

Every phase's own "Testing" line above states its specific requirement; this table is the
cross-cutting policy those lines instantiate.

---

## 9. Full Production Deployment Preparation

Genuinely cross-deployable, not just frontend/mobile:

- **No hosting target is chosen anywhere in this repository** — `docker/docker-compose.*.yml`
  and `infrastructure/deployment/{compose,k8s}/` are placeholders; the backend's own CI
  explicitly says so about itself. This is the single largest remaining "architectural decision
  that would permanently affect the platform" in the entire project, spanning backend + frontend
  - mobile + both device-plane services. **I will not choose this unilaterally.** It belongs in
    the Decision Log (§13) and, realistically, is its own dedicated planning conversation once
    enough of this roadmap is built to make the choice concrete (self-host vs. managed
    Kubernetes vs. a PaaS — each implies different CI/CD shapes for every deployable).
- Once chosen: F13/M5's CI pipelines gain a real deploy step (currently deliberately absent,
  matching the backend's own honest "no deploy step, no target configured" CI posture); a
  staging environment mirroring prod; secrets management (already partially designed —
  `AuthSettings.jwt_secret_key` etc. — extended to frontend build-time env vars and mobile build
  signing secrets).
- Observability: structured logging exists backend-side; frontend/mobile error tracking is a
  Decision Log item (§13), not assumed.
- The two device-plane services (`jt808`, `jt1078`) need their own deployment target decisions
  too, likely the same one, given `architecture.md` #2's "separate deployable" framing doesn't
  mean "separate hosting provider" — flagged for the same future conversation.

---

## 10. Risk Register (Top Items Only — Full Risk Notes Live Inline Per Phase Above)

| Risk                                                                                               | Phase(s)                 | Mitigation already built into the plan                                                                |
| -------------------------------------------------------------------------------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------- |
| Missing design assets stall Phase F0's final polish                                                | F0, M0                   | Structure/methodology proceeds now; only pixel-perfect values wait                                    |
| Map provider choice delayed indefinitely                                                           | F7                       | Every other phase proceeds regardless; F7 is the only one blocked                                     |
| Live tracking has no real data source yet (device-plane bridge incomplete)                         | F7                       | Built honestly against synthetic/manual data; no fake live indicator                                  |
| `transport_ops` (F4–F6) is large enough to slip                                                    | F4–F6                    | Already split into three reviewable slices along the backend's own aggregate boundaries               |
| Frontend can only gate by role, not fine-grained permission                                        | All RBAC-touching phases | Documented as an accepted, common pattern; upgrade path named (§3.6), not silently accepted as broken |
| Payment/video/report vendor gaps mean three feature phases end in an honest "not configured" state | F9, F10, F11             | Scoped explicitly to what's real; no speculative full-feature builds against nonexistent adapters     |
| Deployment target undecided                                                                        | F13, M5, §9              | Explicitly deferred to a dedicated decision, not silently assumed                                     |

---

## 11. Decision Log — What Needs Your Sign-Off

1. **UI/UX design assets** (§0) — share exports/Figma link/screenshots/style guide.
2. **Map provider** (§3.9) — Mapbox / Google Maps / MapLibre+free-tiles, or another option. F7 has
   a second, independent gate as of item 7 below (§4A's B1/B2) — resolving this item alone is not
   sufficient to unblock F7's real-data state.
3. **Video vendor / `VideoProviderPort` adapter** (F10, backend-side, blocks F10's real build).
   Executed by §4A's B3 (Video Integration) once decided — B3 cannot start in earnest before this
   item is resolved.
4. **Shared cross-platform contract strategy** (§3.10/§6) — OpenAPI-driven codegen, or continue
   hand-maintained typed DTOs per platform.
5. **Deployment/hosting target** (§9) — the largest, most permanent decision in the whole
   remaining project; recommend its own dedicated conversation once more of the roadmap is
   built out and the shape of the answer is more concrete.
6. **Error-tracking/visual-regression paid tooling** (§3.8/§9) — optional; explicitly not
   assumed either way.
7. **JT808 backend-integration phasing** (§4A) — **RESOLVED, 2026-07-23.** Tracked as an
   independent, parallel Backend Integration workstream (B1–B3), explicitly not sequenced before
   or after F5/F6, targeted for completion (B1/B2) alongside F7 rather than gating it sequentially.
   This is the only item in this log that is now closed rather than open — recorded here so the
   decision and its reasoning stay part of the official plan rather than living only in
   conversation history.

Everything else in this document — RHF+Zod, TanStack Table, MSW, Playwright, Riverpod,
`flutter_secure_storage`, the entire phase sequence and every phase's internal scope — I
consider a routine technical decision within the authority you've already given me, and will
proceed on accordingly without further check-ins, flagging only if new information changes the
calculus.

---

## 12. Self-Critique — What Changed on Review

Before presenting, I re-read this document adversarially and made three changes:

1. **First draft sequenced Video (C6) and Reporting (C9) earlier**, treating them like any other
   feature phase. On review: both are gated on backend adapters that don't exist, so building
   full UI ahead of them would be speculative work with no payoff — moved both explicitly to
   "last among real feature phases," scoped down to only what's honestly buildable today, and
   called that out as a deliberate choice rather than leaving it implicit.
2. **First draft didn't mention `services/jt808/`'s real implementation state at all** — I'd
   have written this whole roadmap from CLAUDE.md's own backend-only framing and gotten Phase
   F7's risk assessment wrong (I would have said "no live data, full stop" rather than "the
   bridge specifically is missing, and here's the exact remaining gap on each side"). Reading
   `services/jt808/README.md` directly, rather than trusting my own prior Production Readiness
   Report's characterization, changed §2.2 substantially and is the single most important
   correction this self-review pass produced.
3. **First draft treated "shared architecture between React and Flutter" too casually**,
   defaulting to "just hand-maintain types on both sides" without seriously considering the
   OpenAPI-codegen alternative already hinted at by this repo's own empty
   `shared/api-contracts/`/`shared/event-contracts/` scaffolding. Rewrote §3.10 and §6 to
   present it as a genuine, repo-history-grounded architectural choice requiring your sign-off,
   rather than a throwaway suggestion.

I'm confident this is the right roadmap to execute against, with the six Decision Log items as
the only real open questions.
