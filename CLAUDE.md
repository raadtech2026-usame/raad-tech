# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Division of labor with `docs/PROJECT_STATUS.md`** (that file's own §14 states this explicitly):
this file is the authority on *why* — architecture, invariants, business rules, permanent
engineering lessons, and pointers to ADRs. `PROJECT_STATUS.md` is the authority on *current state
and what's next* (per-feature ✅/🟡/❌/⏸ status in its §3, the numbered Known Issues in its §10,
sprint-by-sprint history in its §8/§9). Read both before implementing; if they disagree, trust the
running code and fix whichever doc is stale.

## What RAAD Is

RAAD is a cloud-based **School Bus Tracking and Student Transportation Management Platform**.

It exists to solve one problem: giving schools, transport operators, drivers, and parents real-time
visibility and control over school bus operations. Every feature decision should be evaluated against
that single purpose.

## Product Scope

### In scope (this is what RAAD does)

- Real-time GPS tracking of school buses
- Live video streaming from onboard bus cameras (JT1078)
- GPS/vehicle terminal communication (JT808)
- Parent notifications (e.g., bus location, arrival/departure, pickup/drop-off events)
- Fleet management (buses/vehicles as assets)
- Driver management
- Route management
- Student transportation (linking students to routes/buses, boarding/alighting tracking)

### Explicitly out of scope

RAAD is **not** a school ERP. Do not add, extend toward, or casually suggest features from these domains,
even if a request seems adjacent:

- Classroom/school attendance tracking
- General school ERP functionality
- Payroll
- Exams / gradebook / academic records
- Learning Management System (LMS) features

If a request would pull RAAD toward any of the above, say so explicitly and ask for confirmation
rather than implementing it. Scope creep into general school-management territory is the main risk
to design against in this codebase.

## Business Model (Realigned 2026-07-28)

RAAD is a **three-level multi-tenant platform**, in this strict order of authority:

1. **RAAD Platform (Super Admin)** — RAAD's own company dashboard. RAAD manages Organizations,
   Subscriptions/Billing, Devices (hardware onboarding end-to-end), Drivers-as-fleet-assets
   visibility, Live GPS/Video, Fleet Monitoring, Support, and Platform Analytics. **RAAD does not
   manage students or parents directly, and does not run classroom/attendance/ERP functionality**
   — that stays this project's permanent out-of-scope boundary (Product Scope, above).
2. **Organization** — owns all operational data: Vehicles, Drivers, Routes/Stops, Students,
   Parents, Staff Users, Device Assignments. Only reachable after RAAD onboards the Organization
   (below) — an Organization never provisions itself.
3. **Parent / Driver** — mobile-only (`.claude/rules/flutter.md` #1), scoped to exactly one
   Organization, created only by that Organization.

This realignment added five ADR-driven changes on top of the architecture documented below, each
formalized as an ADR before implementation (`.claude/rules/workflow.md` #7/#8). **All five have
now landed** — full verification detail (test counts, live-verification steps, exact bugs found
during implementation) lives in `PROJECT_STATUS.md`, not duplicated here:

- **Organization Onboarding** (`docs/architecture/adr/0017-organization-onboarding-orchestration.md`,
  reusing ADR-0003's provisioning-port pattern, now **Accepted** — previously "Proposed, not
  accepted"): RAAD creates the Organization, selects its Plan, and creates the first Org Admin —
  handing off a username/phone + one-time temporary password — in one orchestrated flow. The same
  provisioning-port pattern also backs Driver registration.
- **Organization-only billing** (`docs/architecture/adr/0016-organization-only-billing-model.md`,
  amending ADR-0006): direct parent billing is removed **outright, not deprecated in place** —
  `SubscriberType.PARENT`, `Organization.billing_model=parent_pays`,
  `RenewParentSubscriptionCommand` are all deleted. RAAD bills Organizations only. Usage-metrics
  tracking (active users, MAU, active devices, active vehicles) ships with **no pricing formula**
  — none is documented anywhere, so only tracking/display exists.
- **Device inventory** (`docs/architecture/adr/0018-device-inventory-and-allocation.md`,
  formalizing the previously-draft-only `docs/architecture/RAAD_DevicePlane_Architecture_v0_1_draft.md`
  §3.5): Supplier → RAAD registers into `device_inventory` (platform-scoped, **no**
  `organization_id`, like `regions`/`plans`) → RAAD allocates to an Organization (creates the
  `devices` row via the existing `Device.register()`, unchanged shape) → the Organization can now
  **read** (never manage) devices allocated to it — a narrow, explicit, flagged reversal of the
  Device Domain Overhaul's original zero-device-visibility posture for `org_admin`, granting only
  `fleet_device.devices.read`, no other `.devices.*` permission.
- **Account-sharing protection** (`docs/architecture/adr/0019-account-sharing-session-cap.md`): a
  concurrent-session cap on `refresh_tokens`, not device attestation — a deliberate lightweight
  tier (no fingerprinting; blocked on the Flutter app existing beyond scaffold). **Implementation:**
  `core.policies.session_limit.SessionLimitPolicy` enforced inside `AuthApplicationService.login`/
  `.refresh` — oldest non-revoked/non-expired `RefreshToken`s are revoked once a per-role cap is
  exceeded; a refresh's own rotated token is deliberately excluded from that count (a 1:1
  replacement, not a net-new session — counting it would make every ordinary refresh spuriously
  evict an unrelated session). The cap lives in **one** `SystemSetting` row (`key="session_cap"`,
  value `{role: max_sessions}` dict) rather than one row per role, because `SystemSettingKey`'s
  26-character max can't fit a per-role key like `session_cap.regional_manager`. Read via a new
  `SessionCapPort` abstraction that `iam` depends on only abstractly, with its concrete adapter
  placed in `core/di/` (the composition root, not `iam` itself) — **this is the reference pattern**
  for any future case of one module reading another module's `SystemSetting` value
  (`.claude/rules/backend.md` #3); confirmed clean against the architecture-gate module-boundary
  test. Self-service `GET`/`DELETE /auth/sessions` returns a **masked** `ip_address`. A "login from
  an unrecognized device" signal is visibility-only (`.claude/rules/security.md` #8, no automated
  block) and is deliberately skipped on a genuinely first-ever login (a flagged interpretive
  choice — the ADR's own "not seen in the last N sessions" leaves N undefined).
- **Platform Analytics dashboard** (`docs/architecture/adr/0020-platform-analytics-read-model.md`):
  a new `platform_audit.PlatformStatsApplicationService` (distinct from
  `PlatformAuditApplicationService`), constructor-injected with `organization`/`iam`/
  `fleet_device`/`billing`'s own application services plus the existing `HealthCheckService` —
  legal per the architecture-gate Rule 1 (application-layer imports only, never `domain`/`infra`).
  Closes the previously-fabricated Online/Offline Devices KPI via a new `devices.is_online`
  boolean, populated by the *existing* `DeviceConnectivityProcessor` extended in place (no new
  event consumer needed). New `admin.platform_stats.read` permission (Founder/Regional
  Manager/Support Staff/Finance Staff) rather than reusing `admin.audit.read`, since
  `finance_staff` doesn't hold that grant. "Live Vehicle Locations" and "Active Drivers" KPIs are
  a flagged scope cut, not silently dropped (no safe cheap Redis aggregate for the former; neither
  module is in the ADR's own decision scope for the latter).

## Core Technical Domains

RAAD's real-time capabilities target two vehicle telematics protocols — these terms recur across
GPS ingestion, video, and device-communication code:

- **JT808** (JT/T 808) — protocol between the bus's onboard terminal and the platform: GPS
  positioning, terminal registration/auth, status, alarms/events, and commands sent to the device.
- **JT1078** (JT/T 1078) — protocol for transmitting live audio/video from onboard cameras to the
  platform over the public network.

Treat both as first-class architectural concerns: most "real-time tracking" and "live video" work
in this codebase is ultimately about correctly implementing, parsing, or relaying JT808/JT1078
traffic — for a device-plane vendor that is genuinely JT/T 808/1078-compliant. **The first
procured hardware vendor is not** — see below before assuming either protocol applies to the
actual current integration.

**Real hardware vendor decision (ADR-0009), device gateway rename (ADR-0010).**
`docs/vendor/HARDWARE_ANALYSIS.md` (tracing only to the vendor's own documentation, `mdvrdocs/`)
found that the actually-procured MDVR hardware (Shenzhen Tianyou Security Technology Co., Ltd,
brand "LSZ", model `LSZ-C5804DG-Q-F`) does not implement JT/T 808 or JT/T 1078 at all — it speaks
its own proprietary ASCII/binary protocol (different framing, different message-identity scheme,
no checksum/escaping, different media transport), confirmed against the codebase's existing,
tested JT/T 808-2013 parser, which cannot parse a single frame this hardware sends.
`docs/architecture/adr/0009-mdvr-vendor-protocol-device-plane.md` records the resulting decision:
RAAD terminates this vendor's protocol directly, in the same device-plane deployable, via a new,
parallel protocol/dispatcher/handlers stack — not a patched JT/T 808 "dialect," and not by
integrating through the vendor's own separate CMS server product. **That deployable was
subsequently renamed `services/jt808/` → `services/device-gateway/` and reorganized into
`src/vendors/{jt808,lsz,teltonika,queclink,ruptela}/` behind a common `DeviceProtocolAdapter`
interface (ADR-0010)** — a single multi-vendor entry point for every GPS/MDVR integration, not a
JT808-specific service; `teltonika`/`queclink`/`ruptela` are structural placeholders only (no
hardware procured, no vendor docs, no code invented ahead of either). ADR-0010 also wires a real
Redis-backed event bus (`RedisEventPublisher`, shared by every vendor adapter) and a
broker-driven device registry projection, replacing the interim in-memory stand-ins ADR-0009 had
explicitly deferred. The existing JT/T 808 implementation (`src/vendors/jt808/`) is kept,
untouched, dormant, for a possible future genuinely-compliant vendor; the architectural
principles below (separate plane, event-only communication with the business plane, same
`DevicePositionReported`/`DeviceOnline`/`DeviceOffline`/`DeviceAlarmRaised` event contract, now
all real, published events per ADR-0010) apply identically regardless of which vendor adapter is
active. `.claude/rules/jt808.md`/`.claude/rules/jt1078.md` remain this architecture's *target*
framing for device-plane work in general; they no longer describe the currently-integrated
hardware specifically — see ADR-0009/ADR-0010 (and ADR-0015 for how device-plane trust/auth is
adapted for a vendor with no credential mechanism) for the full reasoning.

**Unresolved verification point — flagged per `.claude/rules/documentation.md` #2, do not
silently resolve.** The supplier has confirmed that standalone JT808 and JT1078 documentation
will be provided for this hardware. Until that documentation is received and reviewed, ADR-0009's
non-compliance finding is the only verified fact about this vendor's protocol. Do not assume the
forthcoming documentation will change that conclusion, and do not build or plan against JT/T
808/1078 compliance for this vendor before that documentation exists and has actually been
reviewed against the codebase, the same way `HARDWARE_ANALYSIS.md` was.

## Domain Vocabulary

- **Fleet** — the set of buses/vehicles operated by a school or transport operator.
- **Route** — a defined path a bus follows, with an ordered set of stops.
- **Driver** — the operator assigned to a bus/route.
- **Student transportation record** — the association between a student and the route/bus they ride.
- **Parent notification** — an alert sent to a parent/guardian about their child's bus (e.g., approaching stop, boarded, dropped off).

## Repository Status

The Business API backend (`backend/`) is a running FastAPI modular monolith with **all ten**
bounded contexts implemented end-to-end (domain → application → infra → API → database
migration), backed by a live PostgreSQL schema. Cross-cutting RBAC (seeded permission matrix),
tenant/region `ScopeResolver`, CR-1/D5 policy enforcement, the `audit_entries` write
architecture, the Redis Streams event broker, both background workers, and three scheduled jobs
are implemented and verified. A real CI/CD gate and contract-test suite exist for all four
deployables (backend, frontend, mobile, device-gateway). **Current per-feature status
(✅ Complete / 🟡 Partial / ❌ Missing / ⏸ Deliberately deferred) lives in `PROJECT_STATUS.md`
§3** — this section covers only the architectural facts, cross-module rules, and non-obvious
invariants a future change must not violate, not a status snapshot that will drift.

### Tech stack (decided)

- **Language/framework:** Python, FastAPI (async, modular monolith — `.claude/rules/architecture.md`).
- **Database:** **PostgreSQL** via the `asyncpg` driver (ADR-0002, superseding an earlier MySQL 8.x
  decision — see `.claude/rules/database.md`). **Redis** backs `tracking`'s read-only
  `RedisLatestPositionPort` and, independently configurable (`RAAD_BROKER__URL`), the event
  broker (ADR-0008: Redis Streams) plus its `LockPort`/`DeadLetterQueue`.
- **ORM/migrations:** SQLAlchemy 2.x async + Alembic, revisions in `backend/migrations/versions/`.
- **Dependency injection:** a small hand-rolled composition root (`backend/raad/core/di/`), not a
  third-party DI framework.
- **Dev tooling** (pytest, ruff/mypy): still **not formally approved** — `backend/pyproject.toml`'s
  own comments track this as an open item. `black` is applied inconsistently across the codebase
  — don't assume every file is currently `black`-clean.

### Completed bounded contexts

Each has the fixed `api/application/domain/infra/events` module shape
(`.claude/rules/backend.md` #1), registered in `core/di/bootstrap.py` and
`interfaces/http/api_v1.py`. The notes below cover durable architectural facts only — what's
deliberately *not* built, cross-module id-handling rules, and non-obvious invariants — not
implementation history (see `PROJECT_STATUS.md` §3 for current per-feature status).

- **IAM** — users, JWT auth, seeded RBAC (`role_permissions`, ADR-0004) — `require_permission`
  resolves for real on every route. `users` starts empty on every fresh deployment, deliberately —
  no migration/seed creates an account, since every documented way to create a `User`
  (`POST /users`) requires an already-authenticated in-scope admin caller. `python -m
  raad.interfaces.cli.bootstrap_founder` is the one-time, operator-invoked bootstrap CLI (never a
  seeded row or an unauthenticated HTTP endpoint) — see `docs/runbooks/founder-bootstrap.md`.
  **ADR-0023** adds `GET /me`/`/me/students`/`/me/driver-profile` — see "Canonical `/me`" below.
- **Organization** — organizations, regions, tenant hierarchy, `region_assignments`/
  `support_assignments` backing a real `ScopeResolver` (ADR-0005).
- **Fleet Device** — vehicles, devices, cameras, device↔vehicle assignment lifecycle. RAAD owns
  and manages all GPS/MDVR hardware; schools never register, configure, or view device internals.
  `org_admin` holds **zero** `fleet_device.devices.*` permissions except the single ADR-0018
  `.read` grant below — `fleet_device.vehicles.*` stays fully granted, since vehicles are
  legitimately school fleet data. `devices` carries `imei`/`iccid`/`serial_number` (nullable,
  globally unique like `terminal_id`) for hardware-intake theft/fraud/RMA workflows.
  `VehicleApplicationService.get_vehicle_by_id` embeds only `tracking_status.last_seen_at` —
  deliberately no derived `is_connected` boolean, since no source in this module can answer
  "online right now" honestly — this is the *only* device-derived data an Org Admin session can
  ever reach; `list_vehicles` leaves it `null` to avoid an N+1 lookup per page. **ADR-0018**
  added `device_inventory` — a platform-scoped, pre-tenant pool with deliberately **no**
  `organization_id` column, "like `regions`/`plans`" — via a `DeviceInventoryItem` aggregate
  (`manufactured/in_stock/allocated/scrapped`). Two RAAD-only routes: `POST /device-inventory`
  (receive stock) and `POST /device-inventory/{id}/allocate` (allocates to an Organization,
  creating the `devices` row via the existing `Device.register()` in the same transaction,
  linked back by `devices.inventory_id`). **No `GET /device-inventory` list/detail route
  exists** — ADR-0018 documents only the two `POST` routes (routes are contract-driven here, not
  capability-driven) — a flagged real usability gap, not silently invented around. Allocation
  reuses the inventory item's own `serial_number` as the new device's `terminal_id` (confirmed
  with the user: LSZ has no real JT808 `terminal_id` concept; `serial_number` is already its wire
  identity — grounded in ADR-0009/0010/0015). `device_status_log` (Database Design §7.3) remains
  documented-but-not-built.
- **Tracking** — vehicle positions, geofence crossings. `RedisLatestPositionPort` is read-only;
  the JT808 Technical Design names the device-plane service itself, not this backend, as the
  writer of `vehicle:{id}:last` — `TrackingApplicationService.record_vehicle_position` persists
  history only, never also writes Redis. Both routes enforce `TrackingVisibilityPolicy`
  (`.claude/rules/security.md` #4's four-dimension predicate) via
  `interfaces/http/policy_guards.resolve_tracking_decision` — ADR-0006 resolves the D4-vs-CR-1
  conflict (safety-over-billing wins for genuinely live position during an active trip; trip
  history stays fully CR-1-gated).
- **Transport Operations** — `Student`, `Parent`, `student_parents` M:N link, `Driver`,
  `Route`+`Stop` child entity, `Trip`, and `StudentAssignment` ("the CR-1 access gate"). Only
  `trip_students` (the roster snapshot, Database Design §6.9) remains unbuilt — its data source,
  `student_assignments`, only recently landed, so `Trip` ships as vehicle+driver+route only, no
  student roster. The `/drivers` REST resource has no documented row in API Contracts §4.3 — built
  anyway on Database Design §6.1/ADR-0001's table ownership, the same uniform-CRUD precedent
  `student_parents` established. `Route.remove_stop`/`move_stop` and `Trip.interrupt`/`resume` are
  implemented and unit-tested but have no approved HTTP route this phase — the same
  "use-case-exists-no-endpoint-yet" posture `fleet_device`'s `RegisterCameraCommand` established.
  **`Trip.vehicle_id`/`StudentAssignment.vehicle_id` are opaque, format-validated-only
  cross-module ids with no existence check** — `transport_ops` cannot perform a cross-module DB
  read (`.claude/rules/backend.md` #3), and ADR-0003 (the only cross-module coordination design in
  this codebase) covers a write workflow, not read/validation; this mirrors the existing
  `Parent.user_id`/`Driver.user_id` precedent. **Known, unresolved event-catalog collision:**
  `StudentAssignment`'s four revocation events (`StudentAssignmentRemoved`/`StudentTransferred`/
  `StudentGraduated`/`StudentDisabled`) share three exact `event_type` strings with `Student`'s
  own status-change events — distinguishable only by `aggregate_type`, never disambiguated in the
  LLD's event catalog.
- **Billing (C8)** — `Plan`, `Subscription`, `Invoice`, `Payment` (no `retry()` — a retry is a
  brand-new `Payment.initiate(...)` with a fresh idempotency key), `TransportFee` (no HTTP route,
  no documented API surface). `Plan`/`Subscription` have no documented write routes at all.
  **Permanent gotcha:** `payments.idempotency_key` is `CHAR(64)` per the schema authority, and
  PostgreSQL blank-pads `CHAR(n)` storage on `SELECT` (unlike `VARCHAR`) — `infra/mappers.py`'s
  `model_to_payment` strips the padding before it reaches the domain layer; any future `CHAR(n)`
  column needs the identical treatment. A declined payment marks `Payment` `failed` and leaves the
  invoice unchanged (a resolved documentation conflict: `invoices.status` has no `failed` value in
  Database Design §8.3, despite Phase-2's narrative saying to mark the invoice failed). **Superseded
  by ADR-0022** — see "Payment Provider Architecture" below for the current design. ADR-0016
  removed the parent-billing path outright — see Business Model above.
- **Notifications (C7)** — `Notification` (create/mark_read, the in-app store) and `DeviceToken`
  (FCM registration). **`GET /notifications`/`GET /notifications/{id}` are scoped by personal
  ownership** (`recipient_user_id = principal.user_id`), **not tenant** — the first endpoints in
  this codebase scoped that way; a non-owner request 404s, never 403s, generalizing Backend LLD
  §14.3's "404-over-403 avoids confirming existence of out-of-scope data" from cross-tenant to
  cross-user. `notification_preferences` (Database Design §7.7) is unbuilt — no document gives it
  a route. **Real, unresolved event-contract conflict:** API Contracts §13.2 documents a single
  `student.assignment_changed` wire event with a `new_status` payload field; the actually-shipped
  `transport_ops` events are the four separate ones above, with no `new_status` field and no
  translation layer anywhere in this codebase. `notifications.data_json` established this
  codebase's first `JSONB` column (ADR-0002).
- **Reporting (C9)** — `ReportRun` (request/start/succeed/fail) is the only aggregate built.
  **Real, unresolved documentation gap:** `ReportDefinition` (Phase 2 §2/§10.1's conceptual
  pairing with `ReportRun`) has no table anywhere in Database Design (the schema authority) and no
  API route manages one. `ReportType` is therefore an opaque, non-empty, length-validated string
  (`report_runs.definition_key`), not a closed enum — no document gives exact wire-format values.
  No list route is documented, so none exists. Actual report rendering (PDF/Excel) is out of
  scope — `ReportRendererPort` is unbound (see Known gaps below).
- **Video (C6)** — `VideoSession` (`request_live`/`request_playback`/`activate`/`end`/`fail`) is
  the only aggregate built — `playback_requests` is read as descriptive elaboration of
  `window_start`/`window_end`, not a second aggregate. **Native JT1078 is explicitly not
  implemented** — built around an unbound `VideoProviderPort` abstraction (MVP: a hardware/vendor
  video API). All three routes call `interfaces/http/policy_guards.enforce_d5`
  (`.claude/rules/jt1078.md` #1: "Parents have zero reachable path to video, anywhere, ever")
  before any application-service call, resolving `organization_id` via `fleet_device` (no
  cross-module DB read). `video_sessions` carries no `stream_url`/token column — that stays
  Redis-owned by the (not-yet-built) JT1078 service; a bound provider's return value is surfaced
  only in the API response, never persisted.
- **Platform & Audit (C10)** — `AuditEntry` (`GET /admin/audit`, read-only) and `SystemSetting`
  (`GET`/`PATCH /admin/settings`) are built; `Integration` (Database Design §8.9) is not — no
  document gives it any lifecycle verbs or route. **`AuditEntry` is never created through this
  module** (ADR-0007): `audit_entries` is a shared-kernel table, written transactionally by every
  *other* module's own `UnitOfWork.commit()` via `core.audit.writer.AuditWriter`. `platform_audit`
  is purely the read side.

### Architecture patterns in use

All ten completed contexts apply the same patterns identically, enforced by an automated
`tests/architecture/` gate suite (ten tests: domain purity, layer dependency direction, module
boundaries, API-layer boundaries), not just asserted:

- **Clean Architecture / layered dependency direction:** `api → application → domain`; `infra`
  implements interfaces `domain` defines; domain never imports FastAPI or SQLAlchemy
  (`.claude/rules/backend.md` #2).
- **DDD:** aggregates with buffered domain events (`_AggregateRoot._record()` /
  `pull_domain_events()`, deliberately duplicated per module rather than shared), value objects,
  domain-owned invariants.
- **Repository pattern:** one `SqlAlchemy<Entity>Repository` per aggregate, composing
  `core.db.repository.SqlAlchemyRepositoryBase`; every repository keeps an in-memory identity map
  so in-place aggregate mutations get re-projected onto their ORM row via
  `flush_tracked_changes()` immediately before commit.
- **Unit of Work:** `core.db.unit_of_work.SqlAlchemyUnitOfWork`, extended per module to bundle
  that module's repositories onto one transaction boundary; `commit()` always flushes tracked
  changes, then delegates to the base class's outbox-write-then-session-commit.
- **Domain events + transactional outbox + transactional audit trail:** every state change
  buffers `DomainEvent`s on the aggregate; `commit()` writes them to the `outbox` table **and**
  the `audit_entries` table, in the *same* transaction as the business rows
  (`core/events/outbox.py`, `core/audit/writer.py` — ADR-0007) — no event without a committed
  change, no committed change silently missing its event or audit row. The outbox's publish/relay
  side is bound whenever a broker is configured (ADR-0008); `audit_entries`' read side
  (`GET /admin/audit`) has no such dependency and is fully live regardless.
- **Dependency injection:** one composition root, `core/di/bootstrap.py`; unbound dependencies
  fail loudly (`LookupError`/`NotImplementedError`) rather than resolving to a fake.
- **RBAC + tenant/region scope + domain policies (ADR-0004/0005/0006):** `require_permission` and
  `get_scope`/`ScopeResolver` both resolve for real on every route in every module.
  `interfaces/http/policy_guards.py` (outside any single module, since it orchestrates multiple
  modules' application services) is the CR-1/D5 enforcement point — `TrackingVisibilityPolicy` on
  both `tracking` routes, `VideoAccessPolicy` on all three `video` routes.

### Project structure (current)

```
backend/
├── raad/
│   ├── main.py            # ASGI app factory / composition root wiring
│   ├── core/               # cross-cutting kernel: config, security, tenancy, db, events, audit,
│   │                       # errors, logging, di, ids, time, workers
│   ├── modules/             # one package per bounded context, each:
│   │   └── <context>/
│   │       ├── domain/      # entities, value objects, domain events, repository interfaces
│   │       ├── application/ # commands, queries, DTOs, application services, ports
│   │       ├── infra/        # SQLAlchemy models, mappers, concrete repositories, UnitOfWork
│   │       ├── api/          # FastAPI routers, request/response schemas, DI deps
│   │       └── events/       # publishers/subscribers
│   └── interfaces/http/     # api_v1 router aggregation, shared deps, middleware, error handlers
├── migrations/               # Alembic env.py + versions/
└── tests/                    # unit/, integration/ (live-DB round trips), contract/, architecture/
```

### Migration status

- **Engine:** PostgreSQL (ADR-0002). Single linear Alembic chain, no branches, in build order:
  `iam → organization → fleet_device → tracking → transport_ops (student → parent →
  student_parents → driver → route → trip → student_assignment) → billing → notifications →
  reporting → iam (role_permissions, ADR-0004) → organization (region/support_assignments,
  ADR-0005) → video → core (audit_entries, ADR-0007) → platform_audit (system_settings)` (head,
  plus the RBAC-grant/payment/session-cap/analytics/`/me` migrations layered on since — see each
  ADR for its own revision).
- **Verified zero drift:** `alembic check` reports clean against the live schema; the full chain
  round-trips (`upgrade → downgrade → upgrade`) with no orphaned objects. **Permanent rule:**
  every migration introducing a PostgreSQL native `ENUM` type must include an explicit
  `DROP TYPE` in `downgrade()` — `alembic revision --autogenerate` never emits this itself, and
  omitting it breaks re-upgrade after a downgrade.
- `migrations/env.py` imports `infra/models` from all ten modules plus `core.audit.writer` — keep
  this in sync 1:1 with which modules/shared-kernel packages have a model-bearing source file.

### Known gaps (tracked, not hidden)

Full history of every closed phase (Final Backend Completion, Pagination/Filtering/Sorting,
WebSocket, Tenant Isolation Security Audit, and others) lives in `PROJECT_STATUS.md` §9. What
remains here is what's still genuinely open, plus two flagged, unresolved documentation
conflicts (do not silently pick a side on either):

- **`PaymentProviderPort` is resolved (ADR-0022, Stripe)** — see "Payment Provider Architecture"
  below. `VideoProviderPort`/`ReportRendererPort` remain unbound — no vendor/hardware video
  adapter and no report-rendering engine exist yet, both "fail loudly, don't fake it." Load
  tests (`docs/business/...Phase2...` §13.1 NFR targets) are not yet written —
  `testing/load/` is scaffolding only.
- **`ReportDefinition`** (Reporting, above) has no schema-authority table — will need an approved
  documentation update before report content generation can be meaningfully implemented.
- **The `student.assignment_changed`-vs-four-separate-events conflict** (Notifications, above) —
  will need an approved documentation update, not code-level invention, before the Notification
  Worker's event-contract handling can be reconciled with API Contracts §13.2.
- RBAC (`role_permissions`) and `ScopeResolver` grants are editable only via Founder-only routes
  (`POST /roles/{role}/permissions`(`/revoke`), `POST /scope-assignments/regions`/`/support`
  (`/revoke`)) — reachable at the application layer only before this, the same
  "use-case-exists-no-endpoint-yet" posture as `Route.remove_stop`/`Trip.interrupt`.
- **Event broker: Redis Streams (ADR-0008)**, bound whenever `RAAD_BROKER__URL` is configured.
  Notification Worker and Report Worker are both built (`interfaces/workers/`); three scheduled
  jobs run under `RedisLockPort` (`prune_vehicle_positions`, `sweep_expired_subscriptions`,
  `reconcile_expired_payments`). **Trip generation is deliberately not registered** — no document
  gives a schedule/recurrence data model to generate a `Trip` from.

## Permanent Engineering Lessons

Bugs found during implementation that represent a durable rule for future code, not just history
— apply these proactively rather than rediscovering them:

- **Tenant scope is enforced centrally, at the repository layer (ADR-0021) — this is the
  mandatory pattern for any new tenant-owned resource.** `SqlAlchemyRepositoryBase` takes the
  caller's `TenantRegionScope` at construction and applies it inside `get_by_id`/`list_page`/
  `list_all`/`list_cursor_page` via `_apply_scope` (`scope_by_own_id=True` only for
  `Organization`, the one aggregate that *is* the tenant root). **Never rely on a call site
  remembering to filter by `organization_id`** (`.claude/rules/backend.md` #4) — a live-reproduced
  vulnerability (a brand-new Org Admin's `GET /vehicles` returning other organizations' vehicles)
  found this exact mistake repeated across every module before the fix. Out-of-scope
  single-resource access 404s, never 403s. Any creation command that accepts a client-supplied
  `organization_id` needs an explicit `_enforce_own_organization`-style check too — the repository
  fix alone doesn't close a write-side IDOR on a command with no cross-aggregate reference to
  transitively validate against.
- **Aggregate-less domain events must pass `aggregate_id=None`, never a composite string.** A
  composite id like `f"{role}:{permission}"` reliably exceeds `outbox.aggregate_id`'s `CHAR(26)`
  and raises `StringDataRightTruncationError` in production despite passing every fake-backed
  unit test (a fake repository can't catch a real column-width constraint). `RolePermission`/
  `ScopeAssignment`-style "pure grant/revoke reference data" aggregates have no real minted ULID
  identity to begin with — `DomainEvent.aggregate_id` is `str | None` specifically to allow this.
- **Any datetime read back from Postgres and later compared against `Clock.now()` (tz-aware) must
  go through this codebase's existing `_aware_utc`/`_naive` helpers on *every* datetime field on
  that mapper, not just the one that first crashed.** `model_to_user` originally missed this on
  three of four datetime fields even after the crash on the fourth was fixed and understood.
- **Any *optional* hardening layer bound to Redis (rate limiting, caching) must fail open on
  `RedisError`** — logged once, never cascade-failing the endpoint it protects. Proven necessary
  when a configured-but-unreachable Redis took down `/auth/login` entirely until the middleware
  was fixed to distinguish "unbound" from "bound but down."
- **The broker and the cache share one `maxmemory` budget in this MVP topology, so
  `maxmemory-policy` is `noeviction`, never `allkeys-lru`.** An unconsumed outbox Stream entry is
  a lost domain event forever, not reconstructable state (unlike the cache side — latest
  position, geofence state, rate-limit counters), so silent eviction under memory pressure is
  never acceptable while broker and cache share one Redis instance. Splitting them onto separate
  processes so the cache side could safely use `allkeys-lru` is a documented future step, not
  attempted (`.claude/rules/architecture.md` #7: no premature microservices).
- **Any `CHAR(n)` column needs its padding stripped on read**, the same way `model_to_payment`
  strips `payments.idempotency_key`'s blank-padding — PostgreSQL pads `CHAR(n)` on `SELECT`
  (unlike `VARCHAR`), and the domain layer must never see the padding artifact.
- **Changing `--requirepass` on the shared Redis service requires updating its healthcheck in the
  same change.** A plain `redis-cli ping` healthcheck starts failing with `NOAUTH` the instant a
  password is added, marking every container in the stack "unhealthy" — the fix needs
  `CMD-SHELL` (not `CMD`, which never expands shell variables) plus `redis-cli -a
  "$REDIS_PASSWORD" --no-auth-warning ping`.
- **Prometheus counters must be labeled by the matched route *template*, never the raw request
  path** — labeling by raw path creates one time-series per resource ID (unbounded cardinality).
  `RequestLoggingMiddleware` reads `request.scope["route"].path` (populated by Starlette's own
  routing by the time `call_next` returns), falling back to the raw path only for a genuine 404.
- **Never log a database/cache connection string with its credential in plaintext** — redact
  `user:PASS@` down to `user:***@` on every log line, including inside operational shell scripts
  (`scripts/db/backup.sh`/`restore.sh` both originally logged the real password until this was
  caught during live verification).
- **A vendor-supplied field must be clamped/validated at the adapter boundary before it reaches
  domain logic that assumes it's already in range.** The LSZ vendor adapter
  (`services/device-gateway/src/vendors/lsz/handlers/position_handler.py`) was passing
  out-of-range `heading_deg`/`alarm_flags` straight through, silently failing *every* real
  position event (both of the vendor's own documented worked examples triggered it) until this
  was caught by live verification, not by any unit test.

## Frontend Implementation Status

The React web dashboard (`frontend/`) follows `docs/architecture/frontend-flutter-master-roadmap.md`
(phases F0–F13 for React, M0–M5 for Flutter). Design source: `docs/architecture/RAAD Console
(Standalone).html` (the approved interactive mockup) and `docs/architecture/logo-raad.png`
(shield + location pin, brand blue `#1E63FF` / brand green `#2FBF4F`). The mockup was **extracted
into a design system, not converted 1:1** — three flagged departures: (1) ad-hoc pixel values
rationalized into one scale (`styles/tokens.css`); (2) the smallest label text raised to an 11px
legibility floor; (3) several interactive elements with no real accessibility semantics (a
non-interactive settings toggle `<div>`, a drawer with no dialog role/Escape handling) rebuilt
with real ARIA/keyboard support. `Skeleton`/`EmptyState` components exist because every
real network-backed view needs both — the mockup itself depicts neither.

**Two-dashboard architecture, not one app with a role switcher** (the mockup's "tap role to
switch view" was a demo convenience only — a `Principal` has exactly one role per session):

- **Platform Dashboard** (`/platform/*`) — Founder, Regional Manager, Support Staff, Finance
  Staff. Manages the whole platform, including tenant provisioning (`/platform/organizations`).
- **Organization Dashboard** (`/org/*`) — Org Admin only, scoped server-side to their own
  organization; no "Organizations" nav item.
- Driver/Parent have **no web dashboard** — both are mobile-only (`.claude/rules/flutter.md` #1);
  `MobileOnlyPage` shows a clear redirect message if either reaches the web login.

This mapping lives in `shared/auth/dashboard.ts`; per-role nav trees in `app/layout/navConfig.ts`.
**Live Video is absent from every platform role's nav**, not just hidden from Parents — a
deliberate reading of `.claude/rules/api.md` #2 ("Org-Admin only," not "Org-Admin plus RAAD
staff"). Finance Staff's nav is pruned to Dashboard/Organizations/Billing/Reports
(`.claude/rules/security.md` #3's "billing scope only") — presentation only
(`.claude/rules/frontend.md` #2); the backend's RBAC matrix remains the real gate regardless.

**Phase F0** (design tokens, component library, app shell, routing, `PlaceholderPage` for every
unbuilt route) is complete. New deps this phase: `lucide-react` (the mockup's icon set is Lucide's
exact names), `@fontsource/manrope`/`sora`/`jetbrains-mono` (self-hosted, replacing the mockup's
Google Fonts CDN calls), `@tanstack/react-table` (headless table logic; sorting/pagination stay
server-driven per API Contracts §7/§8), `clsx`. **The dashboard home page shows no fabricated
KPI numbers** — no aggregate summary endpoint existed at the time, and fabricating numbers would
break this project's "fail loudly, don't fake it" posture (closed later by ADR-0020, above).

**Phases F1–F5 and the Device Domain Overhaul are complete** (Organizations/Regions, Users,
Vehicles/Devices, Students/Parents/linking, Drivers/Routes/Stops) — each entity gets one shared
component pair reused across both `/platform/*` and `/org/*` where both dashboards need it.
`/org/devices` was **removed entirely**, matching the backend's `org_admin`-holds-zero-device-
permissions posture — `VehiclesPage`'s own "Tracking" drawer section (`last_seen_at` only) is the
only device-derived data an Org Admin session can reach.

**Phase F6 — Trips & StudentAssignment** is complete. **A real backend whitelist gap was found
while building this, not silently worked around:** `Driver`/`Route` repositories (`transport_ops`)
whitelist only `status` as a filter — no `organization_id` — while `Vehicle` (`fleet_device`)
does whitelist it. `ScheduleTripForm`'s vehicle picker is therefore organization-scoped for real;
its driver/route pickers are deliberately global, with a hint that a cross-organization pick will
be rejected server-side (the backend's own `DomainError`, surfaced verbatim, is the real safety
net — never a client-side filter that can't be built honestly). **`StudentAssignment` — "the CR-1
access gate" — deliberately has no dedicated nav page**, matching the approved mockup: built as a
second section on `StudentsPage`'s own detail drawer, a flagged, narrow exception to
`.claude/rules/frontend.md` #1's "no cross-folder `api.ts` import" discipline (a component import,
not a duplicated data read). Shows only the current active assignment, not a history list — the
response carries no `assignedAt`/`endedAt` to order past rows by.

**Map provider: Mapbox GL JS (ADR-0011, user-confirmed)**, behind a pluggable
`shared/map/MapProvider.ts` interface (`.claude/rules/frontend.md` #6 requires this). New deps:
`mapbox-gl`/`@types/mapbox-gl`. `tracking`'s existing REST/WebSocket contracts already expose
plain decimal-degree `lat`/`lng` — no backend change was needed.

**Phase F7 — Live Monitoring & Maps** is complete, but deliberately the "per-vehicle detail view"
half of live tracking, **not** an always-every-vehicle fleet map — `/ws/tracking` supports exactly
one active vehicle subscription per connection (a documented backend simplification), so the page
is a vehicle picker plus one live map. No ETA anywhere (no backend capability exists). Explicitly
out of scope: simultaneous multi-vehicle live markers, and trip position history/playback
(`GET /tracking/trips/{id}/positions`, a distinct scrubber feature).

**Phase F8 — Notifications** is complete. `GET /notifications` is scoped by personal ownership,
not tenant (see Notifications, above) — there is no "every notification in this organization"
admin view. First cursor-paginated page in this frontend (`useInfiniteQuery`, matching the
backend's cursor-only contract — no client-chosen sort). Live-updated over `/ws/notifications` by
**refetching**, not merging WS fields into the cache, since the push frame deliberately carries no
`status`/`read_at`/`data`. `AppShell`'s topbar bell badge goes live for the first time
(`useUnreadCount`, capped at the most recent 50 notifications — a disclosed real limitation, not a
fabricated total).

**Phase F9 — Billing** is complete, **read-only by design** — no `Plan`/`Subscription`/`Invoice`
write route exists this phase, confirmed before writing any UI. **`POST /billing/payments` has no
client function at all** (`features/billing/api.ts`'s own documented decision) — with no
`PaymentProviderPort` bound at the time, every click would both show a broken action *and* leave a
real, permanently-`PENDING` database row behind; this extends the "fail loudly, don't fake it"
posture from *data* to *affordances* (don't offer a control guaranteed to fail). Superseded at
`/org/billing` specifically by ADR-0022 below; `/platform/billing` is unchanged. First tabbed page
in this frontend (`shared/components/Tabs/`, distinct from `FilterChips`). A confirmed RBAC gap
shapes the tab switcher: Regional Manager/Support Staff hold `billing.plans.list` alone, not
`.subscriptions.list`/`.invoices.list` — the tab switcher is omitted for that pair, mirroring the
Founder Dashboard's "omit what would 403" precedent.

**Development Redis environment (ADR-0008/ADR-0010 made runnable):** `docker/docker-compose.yml`'s
`redis` service is real now (`redis:7-alpine`, AOF, healthcheck); the Business API broker and the
Device Gateway's event bus share one local Redis instance by convention
(`redis://localhost:6379/0`). Live verification of this environment found and fixed a real bug —
see the LSZ clamping lesson in Permanent Engineering Lessons above.

**Device onboarding readiness audit** (`docs/architecture/device-onboarding-readiness-audit.md`,
run before F7): confirmed registration and GPS→Postgres ingestion genuinely work end to end;
found gaps outside F7's own scope — no writer anywhere for the Redis `vehicle:{id}:last` key
(neither this backend nor the device-gateway — since resolved for the online/offline half by
ADR-0020's `devices.is_online`, the position-cache half remains open), the geofence pipeline fully
coded but never invoked from the live position-ingestion path, and no boarding/alighting/
overspeed/SOS/ignition implementation anywhere. None of these gate F7 itself.

## Production Readiness Hardening (Priority 1)

A read-only production-readiness audit (`PROJECT_STATUS.md` §9) found nine concrete gaps between
this repository and a real VPS deployment — `PROJECT_STATUS.md` §5's Priority 1 list. Items 1–4
were worked strictly one at a time (architecture review → implementation → tests → live
verification → docs → `PROJECT_STATUS.md` update); Items 5–9 were directed to run back to back
without per-item approval, per explicit user instruction, still each getting its own review/
tests/verification/docs. **All nine are now complete, live-verified, or correctly
audited-and-left-unbuilt pending an external dependency** — full verification detail (exact test
counts, live-verification transcripts, bug-hunt narratives) lives in `PROJECT_STATUS.md` §5/§15,
not duplicated here. What follows is only what a future change must know:

1. **Backups** — a `backup` Compose service runs `pg_dump --format=custom` on a schedule (chosen
   specifically because it enables `pg_restore --clean --if-exists`, which a plain-SQL dump
   can't). `restore.sh` requires an explicit `--target-url` and `--confirm` — never an implicit
   "current database" — so a mistyped invocation can't silently wipe the wrong one. Off-site copy
   via `rclone` is a deliberately pluggable, **not-yet-configured** hook (`BACKUP_RCLONE_REMOTE`
   unset — no cloud storage account provisioned; `PROJECT_STATUS.md` Known Issue #12). The live
   drill (seed → backup → restore into a throwaway DB → assert round-trip) is CI-enforced
   (`testing/backups/test_backup_restore.sh`). Runbook: `docs/runbooks/backup-and-restore.md`.
2. **TLS/HTTPS** — mechanism complete, **not yet live-tested against a real domain** (no Docker
   daemon in this sandbox). Two-phase bootstrap avoids the chicken-and-egg cert problem:
   `prod.conf` (plain HTTP + ACME webroot, the safe always-bootable default) → get a certificate →
   flip to `prod-tls.conf`. `${DOMAIN_NAME}` substitution uses nginx's own official templating
   mount, not a custom render step. `certbot` reloads nginx via shared PID namespace
   (`pid: "service:nginx"`), deliberately not a Docker-socket mount (which would grant
   effectively-root host access for the same outcome). Runbook:
   `docs/runbooks/tls-setup.md` (first live test is a Let's Encrypt **staging** request, so no
   rate-limit consequence on the first real exercise).
3. **Auth rate limiting + account lockout** — account lockout lives on the `User` aggregate
   (`record_failed_login`/`is_locked`, default 5 attempts / 15 minutes, both configurable) and is
   identity-based (locks the account regardless of source IP); rate limiting is IP-based (Redis
   `INCR`+`EXPIRE` fixed window, `LoginRateLimiter`, scoped only to `POST /auth/login` — not a
   general per-route framework). Live-verified end to end against real HTTP/Postgres.
   Rate-limiting's own counting logic is unit-tested only against a fake Redis — no reachable
   Redis in this sandbox (`PROJECT_STATUS.md` Known Issue #14).
4. **Redis production hardening** — mechanism complete, **not yet live-tested against a running
   Redis process**. `--requirepass` now required (`REDIS_PASSWORD`); broker and cache split onto
   separate logical Redis DBs (0 cache / 1 broker) sharing one `maxmemory` budget under
   `noeviction` (see Permanent Engineering Lessons above for why). New `RedisConnectionSettings`
   makes connect/socket timeouts and health-check interval explicit for both clients (previously
   relying on undocumented library defaults). Runbook: `docs/runbooks/redis-operations.md`.
5. **Real health checks + minimum monitoring** — `/health/ready` now runs real, timeout-bounded
   checks (Postgres `SELECT 1` mandatory; each Redis client's `PING` only gating if actually
   configured). New hand-rolled `/metrics` (no new dependency — the actual need doesn't justify a
   full Prometheus client library), labeled by route *template* (see Permanent Engineering Lessons
   above). Grafana/Sentry/OpenTelemetry deliberately not built — each needs a real external
   account/target this session cannot obtain or fabricate meaningfully
   (`docs/runbooks/monitoring.md`).
6. **RBAC grant/revoke routes** — Founder-only routes now expose the previously
   application-layer-only `PermissionApplicationService`/`ScopeAssignmentApplicationService`. See
   the `aggregate_id=None` lesson in Permanent Engineering Lessons above — the bug this item found
   and fixed.
7. **Deployment & rollback runbooks** — `docs/runbooks/vps-deployment.md` (provisioning, firewall,
   Docker, `.env` walkthrough) and `docs/runbooks/rollback.md` (application-code rollback vs.
   migration rollback — the latter names ADR-0016's billing cutover as this codebase's own real
   precedent for a genuinely destructive migration, not a blanket "every migration is safely
   reversible" claim). Necessarily unverified against a real running VPS.
8. **Payment provider integration** — audited, genuinely blocked on two external dependencies at
   the time (no real EVC Plus merchant account/API docs; no documented webhook signature scheme
   or a `Principal` shape for a non-human caller). **A real, still-unresolved documentation
   conflict, flagged not resolved:** Phase 2 §20 describes a **Parent-Pays** EVC Plus workflow
   that ADR-0016 (Organization-only billing) removed outright — no later document redesigns the
   *payment* workflow for the model that replaced it. **Superseded for Stripe specifically by
   ADR-0022** below; EVC Plus/Zaad remain unresolved per this same conflict.
9. **Mobile App MVP** — built directly against the approved
   `docs/architecture/frontend-flutter-master-roadmap.md` §5 (M0–M5). M0 (Foundation) and M2
   (Driver) are code-complete. **M3 (Parent) was partially blocked** on a real backend gap found
   while wiring it: `GET /parents/{parent_id}/students` has no ownership check on the
   path-supplied `parent_id` — since closed by ADR-0023's `/me` endpoints below, though the mobile
   client itself is not yet rewired to them (a follow-up, not done in that pass). M4 (FCM push)
   and M5 (offline resilience + store release) were not attempted — both need real external
   accounts (Firebase; Play Store/App Store Connect). **The one categorical, disclosed limitation
   for this entire item:** no Flutter/Dart SDK exists in this sandbox — every Dart file written is
   "written and carefully reviewed, not yet verified" (parsed/compiled/run) until a real `flutter
   analyze`/`flutter test`/`flutter run` actually succeeds against it, unlike every other Priority
   1 item, which retained some independent verification path despite an incomplete environment.

## Payment Provider Architecture + Organization Billing (ADR-0022, 2026-08-06)

Direct continuation of the program above, at explicit user directive: Organization Billing needed
a real, self-scoped UI, and "no placeholder payment functionality should ship... leaving only real
provider credentials... to be added after VPS deployment," targeting **Hostinger VPS via
Coolify**. Full design record: `docs/architecture/adr/0022-payment-provider-architecture.md`.
Four genuinely blocking design forks were resolved via `AskUserQuestion` before implementing (all
"(Recommended)" options accepted): (1) **Stripe** gets a real, verified adapter now; EVC
Plus/Zaad stay interface-complete stubs (no real merchant docs exist for either, and Phase 2
§20's own EVC Plus workflow describes the Parent-Pays flow ADR-0016 removed — flagged, not
silently picked around, same as Priority 1 Item 8 above). (2) Secrets are environment variables,
composition-root only (`core/di/bootstrap.py`) — **never** `SystemSetting`, since `org_admin`
holds `admin.settings.read`/`.update` too, which would let any Org Admin read/tamper with a
platform-wide secret. (3) The webhook authenticates via a per-provider HMAC signature (Stripe's
own `Stripe-Signature` scheme) over a shared secret — no `Principal`/RBAC involved at all;
`SYSTEM_PRINCIPAL` (now a shared constant in `core/tenancy/principal.py`) represents the caller
for the audit trail only. (4) Coolify owns reverse-proxy/TLS for its own deployment path — this
stack's own `nginx`/`certbot` stay the alternative generic-VPS path, never both running together.

**`PaymentProviderPort` redesign.** Three findings from reading the actual code first: the
previous port was shaped entirely around mobile money, with no way to carry a client-tokenized
card `payment_method_id`; `Payment.mark_paid`/`mark_failed` had no same-state idempotency guard
(a real bug — every provider retries a webhook until it gets a `200`, and a duplicate "paid"
callback would have re-run `subscription.renew(...)` a second time, double-advancing the billing
period — fixed at both the entity level and a service-level short-circuit, with a regression test
proving a replayed callback doesn't move `current_period_end` twice); `infra/adapters.py` was
empty. Now three methods (`charge`, `verify_webhook_signature`, `parse_webhook_event`).
`StripePaymentAdapter` (new `httpx` dependency, chosen over the official `stripe` SDK — matching
this codebase's "hand-roll a narrow need" pattern) calls the real Payment Intents API
(`confirm=true`, no 3D Secure/SCA flow — a deliberate v1 scope cut) and implements Stripe's
documented HMAC-SHA256 webhook scheme, verified against self-constructed test vectors (no live
Stripe account exists in this environment). `EvcPlusPaymentAdapter`/`ZaadPaymentAdapter`
implement the full interface but raise a clear "no merchant API documentation exists" error.

**Webhook route, wired for real.** `POST /billing/payments/callback` has **no**
`Depends(require_permission(...))` — the HMAC signature check *is* this route's authentication; a
missing/invalid signature is a `401`, logged (no `audit_entries` row — no aggregate mutation
happens for a rejected request). New `GET /billing/payments` (payment history — no list route
existed for `Payment` before) behind a new `billing.payments.list` permission. **Permanent
lesson:** a route with no `Depends(require_permission(...))` can still transitively need a
`Principal` through its UoW dependency — `get_billing_uow_unscoped` (mirroring `iam.api.deps.
get_iam_uow`'s `login`/`refresh` precedent) was needed because `get_billing_uow` otherwise
resolves scope from an authenticated caller that doesn't exist for a signed webhook.

**Frontend — `OrgBillingPage` + a real "Pay Invoice" flow.** `/org/billing` is a dedicated,
`principal.organizationId`-scoped page; `/platform/billing` (the shared, cross-organization
`BillingPage`) is untouched. `InvoicesSection` mounts only once a subscription id is known,
since `GET /billing/invoices` is not tenant-scoped server-side (a real, pre-existing gap) — an
unfiltered call at mount time would leak every organization's invoices for a moment. New
`shared/components/ConfirmDialog/` — this frontend's first genuinely consequential/hard-to-reverse
action (charging a real card) gets a real confirm step, distinct from every prior mutation's
"loading button + toast" convention. Stripe Elements (`@stripe/stripe-js` +
`@stripe/react-stripe-js`, new dependencies, required for PCI-compliant client-side tokenization —
the raw card number never reaches this backend) mounts inside it, gated by a
`getBillingProviderConfig()` read against the existing `GET /admin/settings`.

**Deployment — a Coolify overlay, alongside the existing generic-VPS path.** Coolify already runs
its own Traefik reverse proxy with automatic TLS, so this stack's `nginx`/`certbot` must not also
run. `nginx`/`certbot` are gated behind a new `gateway` Compose profile, defaulted **on** via
`docker/.env.example` so every existing dev/generic-VPS command is unaffected — Coolify simply
never activates it. Runbook: `docs/runbooks/coolify-deployment.md` (mechanism-verified only, not
live-tested against a running Coolify instance).

**What remains, genuinely external:** a real Stripe (or EVC Plus/Zaad, once real merchant
documentation exists) merchant account's live credentials, and a real Hostinger VPS + Coolify
instance.

## Canonical `/me` Self-Service Identity Resolution (ADR-0023, 2026-08-07)

At explicit user direction, closes `PROJECT_STATUS.md` Known Issue #17 (discovered while building
the Mobile App MVP): neither `parent` nor `driver` had any safe way to resolve its own domain
identity (`Parent.id`/`Driver.id`) from an authenticated `Principal`, and
`GET /parents/{parent_id}/students` took `parent_id` straight from the URL path with **no
ownership check** comparing it to the caller's own linked `Parent.user_id` — a real cross-parent
privacy leak in waiting. Per `.claude/rules/workflow.md` #8,
`docs/architecture/adr/0023-canonical-me-identity-resolution.md` was written and accepted before
any implementation.

**One canonical capability.** `GET /me` resolves the caller's own cross-module identity in one
place (`user_id`/`role`/`organization_id`, plus `parent_id`/`driver_id` only when the role
matches and a linked row resolves); `GET /me/students` and `GET /me/driver-profile` are thin views
built on that same resolution. Org Admin (and every RAAD-staff role) needs no separate lookup —
`organization_id` is already on `Principal` directly.

**Ownership: `iam`, composing `transport_ops`'s application services** — the same legal
cross-module shape ADR-0020's `PlatformStatsApplicationService` established (application-layer
only, confirmed against the architecture-gate module-boundary test). `iam` was chosen as the
owning module because it already owns `Principal`/`User`/`GET /auth/me` — the natural home for
"who am I, across the whole platform." New mirror methods, each already precedented 1:1 by an
existing sibling: `DriverRepository.get_by_user_id`/`DriverApplicationService.
get_driver_by_user_id` (mirroring `Parent`'s existing equivalent, added during Backend
Stabilization for CR-1 enforcement).

**No client-supplied `parent_id`/`driver_id` — structural, not a runtime check.** Every method
`MeApplicationService` exposes takes only a `Principal` as its identity input; the route
signatures have no `parent_id`/`driver_id` parameter to accept, so there is nothing for a caller
to override — this directly closes the IDOR class Known Issue #17 described, by construction, not
by adding a check that could later be forgotten on a new route. The pre-existing
`GET /parents/{parent_id}/students` (still Org-Admin-reachable) was **not** fixed by this ADR —
explicitly out of scope, a materially different risk since it's usable only by roles that can
already see any organization's data by design.

**Authorization: self-scoping, not RBAC** — matching `GET /auth/me`'s existing posture. `/me`
routes are gated by `Depends(get_current_user)` alone, no `require_permission`, safe specifically
because every response derives from `principal.user_id` alone. **Zero RBAC migration, zero schema
migration.** 404-over-403 when no linked domain record resolves (`/me/students`/
`/me/driver-profile`); `/me` itself never 404s.

**One real, previously unflagged RBAC finding, recorded not silently corrected:**
`transport_ops.student_parents.list` is not actually Org-Admin-only, as earlier documentation
claimed — `founder`/`regional_manager`/`support_staff` also hold it (a later RBAC migration
revoked `.students.*`/`.parents.*` from RAAD-staff roles but never touched
`.student_parents.list`). `parent`/`driver` still hold neither, so this ADR introduces no new
exposure either way.

**What remains:** wiring the mobile app's Parent/Driver screens to these endpoints — no Flutter
SDK in this environment to verify any such change against, the same disclosed limitation Priority
1 Item 9 above carries.

## CI Hardening — Frontend + Device Gateway CI (2026-08-07)

`PROJECT_STATUS.md` §14's own process (re-verify the repo, read this file, continue only the next
approved roadmap item) led here after every Priority 1 item was complete or externally blocked:
the next actionable Priority 2 backlog item was CI hardening (the other five Priority 2 items are
each blocked on an unresolved architecture/documentation gap, a new-dependency decision needing
`.claude/rules/workflow.md` #1/#2's explicit go-ahead, or a real external account — recorded as
such in `PROJECT_STATUS.md` §5, not silently skipped).

New `frontend-pipeline.yml` and `device-gateway-pipeline.yml` (`.github/workflows/`), mirroring
`backend-pipeline.yml`'s exact scope discipline — build/install → test only, **no lint/
security-scan gate**, since `eslint` has no config anywhere in `frontend/` yet and `ruff`/`mypy`
remain formally unapproved (`backend/pyproject.toml`'s own tracked-as-open comment) — and using
only already-approved tooling (`npm`/Vitest; stdlib `unittest` + the already-approved `redis>=5.0`).
**Zero new dependencies, zero new external accounts.** `jt808-pipeline.yml`'s filename is
deliberately left as-is, not renamed — the original JT/T 808 code still lives on, dormant, inside
`services/device-gateway/src/vendors/jt808/` (ADR-0009/0010). Not live-tested against a real
GitHub Actions run — no way to trigger one in this sandbox, the same disclosed posture every other
workflow file in this repository already carries.
