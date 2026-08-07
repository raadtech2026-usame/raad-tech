# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

This realignment changed or added five things relative to the architecture already documented
below, each formalized as an ADR before any implementation (`.claude/rules/workflow.md` #7/#8) —
implementation itself proceeds in milestones and is tracked here as each one lands:

- **Organization Onboarding is RAAD-only and one guided workflow, not two disconnected steps**
  (`docs/architecture/adr/0017-organization-onboarding-orchestration.md`): RAAD creates the
  Organization, selects its Plan, and creates its first Org Admin user — handing off a
  username/phone + one-time temporary password — in one orchestrated flow. Reuses
  **ADR-0003** (now **Accepted**, previously "Proposed, not accepted" — see that ADR's own
  "Extension" section), the same cross-context provisioning-port pattern now also backing
  Driver registration.
- **Billing is Organization-only** (`docs/architecture/adr/0016-organization-only-billing-model.md`,
  amending **ADR-0006**): direct parent billing (`SubscriberType.PARENT`,
  `Organization.billing_model=parent_pays`, `RenewParentSubscriptionCommand`) is removed
  outright — RAAD bills Organizations only, based on tracked usage (active users, MAU, active
  devices, active vehicles; no pricing *formula* is documented, so only tracking/display ships).
- **Device onboarding gains a pre-tenant RAAD inventory**
  (`docs/architecture/adr/0018-device-inventory-and-allocation.md`, formalizing the
  previously-drafted-only `docs/architecture/RAAD_DevicePlane_Architecture_v0_1_draft.md` §3.5):
  Supplier → RAAD registers into `device_inventory` (platform-scoped, no `organization_id`) →
  RAAD allocates to an Organization (creates the `devices` row, unchanged from today's existing
  `Device.register()` shape) → the Organization can now **read** (not manage) devices allocated
  to it — a narrow, explicit, flagged reversal of the Device Domain Overhaul's original
  zero-device-visibility posture for `org_admin`.
- **Account-sharing protection**
  (`docs/architecture/adr/0019-account-sharing-session-cap.md`, **landed**): a concurrent-session
  cap on the existing (previously dead) `refresh_tokens` table, configurable per role via the
  existing `SystemSetting` store, plus self-service session list/revoke. Lightweight tier only,
  by explicit user choice — no device fingerprinting/attestation this phase (blocked on the
  Flutter app existing beyond its current empty scaffold). **Implementation:** `core.policies.
  session_limit.SessionLimitPolicy` (a pure threshold check, mirroring `SubscriptionAccessPolicy`'s
  existing shape) is enforced inside `AuthApplicationService.login`/`.refresh` — after resolving
  the caller's currently-active (non-revoked, non-expired) `RefreshToken`s, the oldest are
  revoked until back under the cap; a refresh's own rotated token is deliberately excluded from
  that count (a 1:1 replacement, not a net-new session — an early design mistake here would have
  made every ordinary token refresh spuriously evict an unrelated session). **Two real gaps
  between the ADR's own text and the actual repository, found by reading the code rather than
  assumed from the ADR:** (1) `SystemSettingKey`'s enforced 26-character max
  (`platform_audit/domain/value_objects.py`) cannot fit a per-role key like
  `session_cap.regional_manager` — resolved by seeding a single row (`key="session_cap"`) whose
  value is a `{role: max_sessions}` dict, rather than one row per role; `SystemSetting.value` was
  already typed as an arbitrary dict, so this needed no schema change. (2) The ADR's own cited
  precedent for "an org-configurable value already living in `SystemSetting`"
  (ADR-0014's `approaching_distance_m`) turned out, on inspection, to actually be a column on
  `Organization` itself, not a `SystemSetting` row at all — there was no existing example of one
  module reading another's `SystemSetting` value live to copy the mechanism from. Resolved by
  applying `.claude/rules/backend.md` #3 directly rather than inventing a new pattern: a new
  `SessionCapPort` (`iam/application/ports.py`) that `iam` depends on only abstractly, with its
  concrete adapter (`SystemSettingSessionCapAdapter`) placed in `core/di/session_cap_adapter.py`
  — the composition root, not `iam` itself — specifically so it, not `iam`, is the thing reaching
  into `platform_audit`'s application-layer facade
  (`PlatformAuditApplicationService.get_system_setting`). `tests/architecture/
  test_module_boundaries.py`'s existing Rule 1 gate (a module may reach another module's
  application facade, never its `domain`/`infra`) independently confirms this design stays
  clean — re-run after this change and still green, not just asserted clean by construction.
  Previously-dead `refresh_tokens.user_agent`/`ip_address` columns (added before this ADR,
  never populated) are captured for the first time; a new `device_label` column (migration
  `4ef3fefb5e8d`, chained after `f3d8b1a4e6c2`) holds a short parsed label derived from
  `user_agent` (`core/security/user_agent.py` — a small hand-rolled regex heuristic, no new
  dependency per `.claude/rules/workflow.md` #1/#2; caught and fixed one real bug in its own
  OS-detection ordering during testing: a genuine iOS Safari user-agent string contains the
  literal compatibility token "like Mac OS X," so iOS/Android must be checked before the plainer
  Mac OS X/Linux patterns they'd otherwise also match first). Self-service `GET`/
  `DELETE /auth/sessions` return a **masked** `ip_address` (new `core/security/ip_mask.py`) —
  never the raw value. A "login from an unrecognized device" signal (`SuspiciousLoginDetected`
  domain event, visibility-only per `.claude/rules/security.md` #8, no automated block) is
  deliberately skipped on a genuinely first-ever login — the ADR's own "not seen in the user's
  last N sessions" leaves N undefined, and flagging the single most common, entirely legitimate
  case (everyone's first login) would be noise, not signal; this is a flagged interpretive
  choice, not silently invented. **Live-verified, not just unit-tested**: the migration
  round-tripped (`upgrade`/`downgrade -1`/`upgrade`, `alembic check` clean); the *real*
  `SystemSettingSessionCapAdapter` (not a test double) was confirmed reading the actual
  migration-seeded values for every role against live Postgres; a live-Postgres integration test
  proves a login past the cap revokes the oldest session in the database (re-fetched via a fresh
  session/UoW, not just in-memory state) and that `GET`/`DELETE /auth/sessions` round-trip for
  real. 1278 unit + 10 architecture-gate tests pass with zero regressions. Zero changes to any
  other bounded context, RBAC, or tenant-isolation code.
- **Platform Analytics dashboard**
  (`docs/architecture/adr/0020-platform-analytics-read-model.md`, **landed**): a new, `platform_
  audit`-owned, cross-module (but never cross-module-DB-reading) stats read-model backing the
  Super Admin dashboard's KPI grid — including closing the previously-missing Online/Offline
  Devices gap so that number is real, not fabricated. **Implementation:** a new `platform_audit.
  PlatformStatsApplicationService` (a distinct class from `PlatformAuditApplicationService`, per
  the ADR's own §1 naming), constructor-injected with `organization`/`iam`/`fleet_device`/
  `billing`'s own application services plus the existing `HealthCheckService` (Priority 1 Item
  5, reused verbatim for "System Health" — no new observability code) — legal per
  `.claude/rules/backend.md` #3/the architecture-gate Rule 1 (a module may import another
  module's *application-layer* symbols, never `domain`/`infra`), confirmed by re-running
  `tests/architecture/test_module_boundaries.py` after the change, still green. **Three real
  gaps between the ADR's own text and the actual repository, found by reading the code rather
  than assumed from the ADR — the identical discipline ADR-0019 established the day before:**
  (1) the ADR's own §3 was stale, and `PROJECT_STATUS.md` Known Issue #9 had already flagged
  it — `DeviceConnectivityProcessor` (`fleet_device/events/subscribers.py`) already consumed
  `DeviceOnline`/`DeviceOffline` and populated `devices.last_seen_at`; no new event consumer
  was needed, only a new `devices.is_online` boolean (migration `b288c2e44aa5`) on the
  *existing* processor, extended in place — Known Issue #9 is now marked resolved, not just
  described. (2) The ADR names `interfaces/http/policy_guards.py` as "the precedent reused
  here," but that file lives outside any bounded-context module specifically because CR-1/D5
  have no single owning module across three unrelated routes — Platform Stats *does* have one
  (`platform_audit`, the ADR's own §1 Decision), so the four-module composition correctly
  lives inside a new application service in that module instead, not a second `interfaces/
  http/`-level file. (3) `finance_staff` does not hold `admin.audit.read` in the seeded RBAC
  matrix, contradicting the ADR's claim that all four RAAD-staff roles already hold the
  `GET /admin/audit` grant — resolved with a new, dedicated `admin.platform_stats.read`
  permission (Founder/Regional Manager/Support Staff/Finance Staff), the ADR's own anticipated
  fallback ("plus a new dedicated permission if the existing grant proves too coarse"), not a
  workaround. New, additive count/sum query methods land in all four modules with no existing
  method's behavior changed (`organization.count_by_status`/`count_created_since`; `iam.
  count_by_status`/`count_last_login_after` (MAU) /`count_created_since`, with a new `ix_users
  __last_login_at` index since that column had none; `fleet_device.Vehicle.count_total`,
  `Device.count_total`/`count_online`; `billing.count_by_status`/`count_expiring_between`/
  `sum_paid_amount_between` — deliberately a real SQL query, not a mirror of `sweep_expired_
  subscriptions`'s existing unfiltered `list_all()` scan, which doesn't belong in a KPI hot
  path). **Two KPIs from the ADR's own Context wishlist are a real, flagged scope cut, not
  silently dropped**: "Live Vehicle Locations" (`tracking`'s Redis state has no safe/cheap
  aggregate count — `KEYS`/`SCAN` over live position keys is exactly the kind of production-
  risk operation this platform avoids) and "Active Drivers" (`transport_ops.Driver` — neither
  module is named in the ADR's own §1 Decision scope). Frontend: `DashboardHomePage.tsx`'s
  pre-existing six-tile stopgap (`PlatformStatsRow`, already self-documented in-code as "a
  deliberate stopgap... superseded by ADR-0020 whenever that milestone lands") had its
  organizations/vehicles/devices tiles replaced by a new `PlatformAnalyticsSection` — one query
  backing status breakdowns, online/offline, MAU, revenue, and system health the old flat-total
  tiles never could show; drivers/students/parents tiles are untouched, correctly outside this
  ADR's scope. **Live-verified, not just unit-tested**: migration round-tripped clean
  (`upgrade`/`downgrade -1`/`upgrade`, `alembic check` clean); the *real*
  `DeviceConnectivityProcessor` (not a fake) confirmed flipping `is_online` in the database on a
  real `DeviceOnline`/`DeviceOffline` event; the *real*, DI-wired `PlatformStatsApplicationService`
  confirmed running the full four-module composition against real Postgres without error. 1294
  unit + 10 architecture-gate tests pass (backend), 344 frontend tests pass, zero regressions.
  Zero changes to any bounded context's existing behavior, RBAC, or tenant-isolation code.

**Implementation status:** architecture accepted; milestone implementation (IAM provisioning
port → org onboarding → billing cutover → device inventory → session cap → platform analytics)
is in progress. **IAM provisioning port, org onboarding, and billing cutover have landed** — see
the Billing (C8) bounded-context entry below for the billing cutover's own full writeup (parent
billing deleted outright: `SubscriberType`/`SubscriberId`/`RenewParentSubscriptionCommand`/
`Organization.billing_model`/`BillingScope.PARENT` all removed, not deprecated in place;
`SubscriptionAccessPolicy` (CR-1) amended per ADR-0006's own Amendment section; a migration
drops `organizations.billing_model` and `subscriptions.subscriber_type`/`subscriber_id`).
**Device inventory has landed** — see the Fleet Device bounded-context entry below for the full
writeup. **Session cap has landed** (2026-08-04, ADR-0019) — see this section's own
"Account-sharing protection" bullet above for the full writeup. **Platform analytics has
landed** (2026-08-05, ADR-0020) — see this section's own "Platform Analytics dashboard" bullet
above for the full writeup. Every milestone in this originally-planned sequence is now
complete.

## Core Technical Domains

RAAD's real-time capabilities are built on two vehicle telematics protocols — these are the terms
you'll see across GPS ingestion, video, and device-communication code:

- **JT808** (JT/T 808) — the protocol used for communication between the bus's onboard terminal and
  the platform: GPS positioning data, terminal registration/auth, status, alarms/events, and commands
  sent to the device.
- **JT1078** (JT/T 1078) — the protocol used for transmitting live audio/video from onboard cameras
  to the platform over the public network.

Treat these two protocols as first-class architectural concerns: most "real-time tracking" and
"live video" features in this codebase are ultimately about correctly implementing, parsing, or
relaying JT808/JT1078 traffic between bus terminals and the platform — for a device-plane vendor
that is genuinely JT/T 808/1078-compliant. **The first procured hardware vendor is not** — see the
note immediately below before assuming either protocol applies to the actual current integration.

**Real hardware vendor decision (ADR-0009), device gateway rename (ADR-0010).**
`docs/vendor/HARDWARE_ANALYSIS.md` (tracing only to the vendor's own documentation, `mdvrdocs/`)
found that the actually-procured MDVR hardware (Shenzhen Tianyou Security Technology Co., Ltd,
brand "LSZ", model `LSZ-C5804DG-Q-F`) does not implement JT/T 808 or JT/T 1078 at all — it speaks
its own proprietary ASCII/binary protocol (different framing, different message-identity scheme,
no checksum/escaping, a different media transport), confirmed against the codebase itself: the
device-plane deployable's existing, tested Phase 9.1–9.6 JT/T 808-2013 parser cannot parse a
single frame this hardware sends. `docs/architecture/adr/0009-mdvr-vendor-protocol-device-plane.md`
records the resulting decision (Option A of `docs/vendor/HARDWARE_INTEGRATION_PLAN.md`'s Decision
Point 1): RAAD terminates this vendor's protocol directly, in the same device-plane deployable, via
a new, parallel protocol/dispatcher/handlers stack — not a patched JT/T 808 "dialect," and not by
integrating through the vendor's own separate CMS server product. **That deployable was
subsequently renamed `services/jt808/` → `services/device-gateway/` and reorganized into
`src/vendors/{jt808,lsz,teltonika,queclink,ruptela}/` behind a common `DeviceProtocolAdapter`
interface (ADR-0010)** — the "device gateway," a single multi-vendor entry point for every
GPS/MDVR integration, not a JT808-specific service; `teltonika`/`queclink`/`ruptela` are
structural placeholders only (no hardware procured, no vendor docs, no code invented ahead of
either). ADR-0010 also wires a real Redis-backed event bus (`RedisEventPublisher`, shared by every
vendor adapter) and a broker-driven device registry projection, replacing the interim in-memory
stand-ins ADR-0009 had explicitly deferred. The existing JT/T 808 implementation
(`src/vendors/jt808/`) is kept, untouched, dormant, for a possible future genuinely-compliant
vendor; the architectural principles below (separate plane, event-only communication with the
business plane, same `DevicePositionReported`/`DeviceOnline`/`DeviceOffline`/`DeviceAlarmRaised`
event contract, now all real, published events per ADR-0010) apply identically regardless of
which vendor adapter is active. `.claude/rules/jt808.md`/`.claude/rules/jt1078.md` remain this
architecture's _target_ framing for device-plane work in general; they no longer describe the
currently-integrated hardware specifically — see ADR-0009/ADR-0010 for the full reasoning.

## Domain Vocabulary

- **Fleet** — the set of buses/vehicles operated by a school or transport operator.
- **Route** — a defined path a bus follows, with an ordered set of stops.
- **Driver** — the operator assigned to a bus/route.
- **Student transportation record** — the association between a student and the route/bus they ride.
- **Parent notification** — an alert sent to a parent/guardian about their child's bus (e.g., approaching stop, boarded, dropped off).

## Repository Status

This repository is **no longer greenfield**. The Business API backend (`backend/`) is a running
FastAPI modular monolith with **all ten** of its bounded contexts fully implemented end-to-end
(domain → application → infrastructure → API → database migration), backed by a live PostgreSQL
schema, as of the Backend Stabilization phase (ADR-0004 through ADR-0008). Cross-cutting
authorization (RBAC permission matrix, tenant/region `ScopeResolver`, CR-1/D5 policy enforcement),
the `audit_entries` write architecture, the Redis Streams event broker, both background workers,
and three scheduled jobs are likewise implemented and verified — see "Known gaps" below for what
genuinely remains (`PaymentProviderPort`/`VideoProviderPort`/`ReportRendererPort` adapters, load
tests). A real CI/CD gate (`.github/workflows/backend-pipeline.yml`) and a contract test suite
(`tests/contract/`) are both now implemented, closing what was previously the largest item on
this list. A **Final Backend Completion phase** subsequently closed seven confirmed RBAC/
error-code/ownership/test-coverage/audit-column gaps and added CORS support. A **Pagination/
Filtering/Sorting phase** then closed the other Tier-2 item that Final Backend Completion phase
had deliberately deferred. A **WebSocket phase** then implemented `/ws/tracking`/
`/ws/notifications` (API Contracts §11) — see "Known gaps" below for the full list — leaving
`PaymentProviderPort`/`VideoProviderPort`/`ReportRendererPort` adapters and load tests as the
largest remaining items before this backend is fully frontend/mobile-ready.

### Tech stack (decided)

- **Language/framework:** Python, FastAPI (async, modular monolith — `.claude/rules/architecture.md`).
- **Database:** **PostgreSQL** via the `asyncpg` driver (`ADR-0002`, superseding an earlier MySQL 8.x
  decision — see `docs/architecture/adr/0002-postgresql-migration.md` and
  `.claude/rules/database.md`). **Redis** (via `redis-py`/`redis.asyncio`, Backend Stabilization
  phase) backs `tracking`'s `RedisLatestPositionPort` (read-only — see the Tracking bullet
  below) **and**, independently configurable (`RAAD_BROKER__URL`), the event broker (ADR-0008:
  Redis Streams) plus its `LockPort`/`DeadLetterQueue` — see "Known gaps" below; session/other
  hot-state caching is not yet wired.
- **ORM/migrations:** SQLAlchemy 2.x async + Alembic, revisions in `backend/migrations/versions/`.
- **Dependency injection:** a small hand-rolled composition root (`backend/raad/core/di/`), not a
  third-party DI framework.
- **Dev tooling** (pytest, ruff/mypy): still **not formally approved** — `backend/pyproject.toml`'s
  own comments track this as an open item. `black` is in use for formatting but is applied
  inconsistently across the codebase (see the Phase 10 architecture review's Code Quality findings)
  — don't assume every file is currently `black`-clean.

### Completed bounded contexts

Each of the ten below has a full `api / application / domain / infra / events` stack (per
`.claude/rules/backend.md` #1) and is registered in `core/di/bootstrap.py` and
`interfaces/http/api_v1.py`:

- **IAM** — users, auth (JWT), and (as of the Backend Stabilization phase) a real, seeded RBAC
  permission matrix (`role_permissions` table, Database Design §4.4; ADR-0004) —
  `require_permission` resolves for real on every route via `IamPermissionEvaluator`, no longer a
  guaranteed-`NotImplementedError` placeholder. **`users` starts empty on every fresh deployment,
  deliberately** — no migration or seed script creates an account (`role_permissions` seeds
  permission _grants_ for the `founder` role, never an actual row), since every documented way to
  create a `User` (`POST /users`) itself requires an already-authenticated in-scope admin caller.
  `interfaces/cli/bootstrap_founder.py` (entry point: `python -m
raad.interfaces.cli.bootstrap_founder`) closes that gap as a one-time, operator-invoked CLI —
  not a migration-seeded row (a fixed, version-controlled credential) and not an HTTP endpoint
  (would need to be reachable unauthenticated, a new public attack surface) — see
  `docs/runbooks/founder-bootstrap.md` for the full guide and ADR-0013's own follow-up entry for
  how this surfaced (a fresh Docker deployment had no documented way to invoke it until that
  ADR's `docker/README.md` was corrected). **ADR-0023 (2026-08-07)** adds `GET /me`/`GET /me/
  students`/`GET /me/driver-profile` — a new `me_router` composing `transport_ops`'s own
  application services to resolve a `Principal` to its own `Parent`/`Driver` domain identity,
  self-scoped with no RBAC grant — see "Canonical `/me` Self-Service Identity Resolution" below
  for the full writeup.
- **Organization** — organizations, regions, tenant hierarchy, and (ADR-0005) `region_assignments`/
  `support_assignments` backing a real `ScopeResolver` (`interfaces/http/deps.get_scope` resolves
  for real now too).
- **Fleet Device** — vehicles, devices, cameras, device↔vehicle assignment lifecycle. The
  **Device Domain Overhaul** brought this context in line with RAAD's actual business model
  (RAAD owns and manages all GPS/MDVR hardware; schools never register, configure, or view
  device internals): `devices` gained `imei`/`iccid`/`serial_number` (nullable, globally unique
  like `terminal_id`, each with its own value object and `ensure_*_available` pre-check
  validator mirroring `ensure_terminal_id_available`'s existing pattern) for hardware-intake
  theft/fraud/RMA workflows — a previously-flagged gap, now closed. The seeded RBAC matrix was
  corrected (migration `22e94bc4e924`, additive on top of the already-applied `5437a5d1651b`
  seed, never edited in place): `org_admin` now holds **zero** `fleet_device.devices.*`
  permissions (not even `.read`) — `fleet_device.vehicles.*` stays granted, since vehicles are
  legitimately school fleet data; `support_staff` (the operational "RAAD technician" role)
  gained `.assign`/`.reassign`/`.unassign` to close a real onboarding gap (it already had
  `.create`/`.update`/`.activate`). `VehicleApplicationService.get_vehicle_by_id` now embeds a
  minimal `tracking_status` (`last_seen_at` only — deliberately no derived `is_connected`
  boolean, since the only source that could answer "online right now" honestly is the JT808
  service's own Redis session state, which this query never reads) via a same-module join of
  this context's own `device_assignments`/`devices` tables — the _only_ device-derived data an
  Org Admin session can ever reach; `list_vehicles` deliberately leaves it `null` to avoid an
  N+1 device lookup per page. **ADR-0018 (Device Inventory & Allocation) has landed**, closing
  the `device_inventory` half of this bullet's earlier deferral: a new `DeviceInventoryItem`
  aggregate (`manufactured/in_stock/allocated/scrapped`, `receive()`/`allocate()`) backs
  `device_inventory` — a platform-scoped, pre-tenant hardware pool with deliberately **no**
  `organization_id` column, "like `regions`/`plans`". Two new RAAD-only routes,
  matching ADR-0018 §2 exactly: `POST /device-inventory` (receives stock) and
  `POST /device-inventory/{id}/allocate` (body `{organization_id}` only — allocates one item to
  an Organization, transitioning it to `allocated` and creating the resulting `devices` row via
  the *existing* `Device.register()` factory in the same transaction, linked back by a new
  nullable `devices.inventory_id`). **Resolved gap, not silently invented around**: ADR-0018's
  own request body has no `terminal_id` field, but `Device.register()` requires one — resolved
  (confirmed with the user) by reusing the inventory item's own `serial_number` as the new
  device's `terminal_id`, grounded in ADR-0009/0010/0015 (the only currently-integrated vendor,
  LSZ, has no real JT808 terminal_id concept; `serial_number` is already its wire identity). The
  seeded RBAC matrix gained three grants (migration `7eb581884c39`): `org_admin` →
  `fleet_device.devices.read` — ADR-0018 §3's own narrow, explicit, flagged reversal of the
  Device Domain Overhaul's zero-device-visibility posture, read-only, tenant-scoped, no other
  `fleet_device.devices.*` grant added — satisfying "Organization immediately sees the assigned
  device" without reopening device management; and `founder`/`support_staff` →
  `fleet_device.device_inventory.create`/`.allocate`. No `GET /device-inventory` list/detail
  route exists — ADR-0018 §2 documents only the two `POST` routes, so none is exposed (routes
  are contract-driven, not capability-driven, matching this module's own existing camera-
  registration precedent) — flagged as a real usability gap (RAAD staff has no way to browse
  in-stock inventory before allocating from it) rather than silently invented around.
  `device_status_log` (a durable online/offline transition history, Database Design §7.3)
  remains documented-but-not-built, deliberately deferred, not silently dropped.
- **Tracking** — vehicle positions, geofence crossings. `LatestPositionPort` now has a concrete,
  read-only `RedisLatestPositionPort` (`tracking/infra/adapters.py`, Database Design §7.1's
  `vehicle:{id}:last` key), bound in DI whenever `RAAD_REDIS__URL` is configured (no Redis is
  reachable in this dev sandbox, so it stays unbound here — same "fail loudly, don't fake it"
  policy `db.url` follows). No write path exists on either the port or the adapter: the JT808
  Technical Design (§21.2) names the JT808 device-plane service itself, not this backend, as the
  key's writer — `TrackingApplicationService.record_vehicle_position` persists history only,
  deliberately never also writing Redis. Both routes now enforce `TrackingVisibilityPolicy`
  (`.claude/rules/security.md` #4's four-dimension predicate) via `interfaces/http/policy_guards.
resolve_tracking_decision` — ADR-0006 resolves the D4-vs-CR-1 documentation conflict this
  required (safety-over-billing wins for genuinely live position during an active trip; trip
  history stays fully CR-1-gated).
- **Transport Operations** — `Student` (enroll/update/activate/disable/graduate/transfer),
  `Parent` (register/update/activate/disable), the `student_parents` M:N link
  (link/unlink/list-by-student/list-by-parent), `Driver` (register/update/activate/disable),
  `Route` (create/update/activate/disable) with its `Stop` child entity
  (add/remove/move-sequence, ordered by `sequence_no`), `Trip`
  (schedule/start/end/interrupt/resume/change-driver), and now `StudentAssignment`
  (assign/remove/transfer/graduate/disable — "the CR-1 access gate", Database Design §6.7) are
  built. Of `transport_ops`'s eight tables (Database Design §6: `students`, `parents`,
  `student_parents`, `routes`, `stops`, `trips`, `student_assignments`, `trip_students`), only
  `trip_students` remains unbuilt (deliberately deferred, see below). The `/drivers` REST
  resource has no corresponding row in `docs/business/RAAD_Phase3.3_API_Contracts_v1.md` §4.3
  (only `Trip`-level `/trips/{id}/driver` is documented there) — built anyway on Database
  Design §6.1/ADR-0001's unambiguous table definition and ownership, following the same
  uniform-CRUD precedent `student_parents` already established for an identically undocumented
  sub-resource; flagged in `modules/transport_ops/api/routers.py`'s module docstring, not
  silently assumed. `/routes` and `/routes/{id}/stops` (GET/POST only) **are** documented (API
  Contracts §4.3) — individual stop update/removal/reorder have no documented route yet, so
  `Route.remove_stop`/`Route.move_stop` are implemented and unit-tested but not HTTP-exposed
  this phase, mirroring `fleet_device`'s identical "use-case exists, no approved endpoint yet"
  posture for `RegisterCameraCommand`. `Trip.vehicle_id` references `fleet_device`'s `Vehicle`
  aggregate (a different bounded context) and is treated as an opaque, format-validated-only
  cross-module id with **no existence check** — confirmed with the user: this mirrors the
  existing `Parent.user_id`/`Driver.user_id` precedent exactly, since `transport_ops` cannot
  perform a cross-module DB read (`.claude/rules/backend.md` #3) and the only cross-module
  coordination design in this codebase, ADR-0003, is still "Proposed, not accepted" and covers
  a write workflow, not a read/validation. `trip_students` (Database Design §6.9, "roster
  snapshot") remains **not built** — its data source, `student_assignments` (§6.7, also owned
  by this bounded context per ADR-0001), is itself not built yet, so `Trip` ships as
  vehicle+driver+route only, no student roster. `Trip.interrupt`/`resume` are implemented and
  unit-tested at the domain/application layers but have no HTTP route this phase (no documented
  `/trips/{id}/interrupt`/`/trips/{id}/resume` path exists), the same "use-case exists, no
  approved endpoint yet" posture already established for `Route.remove_stop`/`move_stop`.
  `StudentAssignment.vehicle_id` gets the identical opaque, no-existence-check cross-module
  treatment as `Trip.vehicle_id`. **Two documentation findings surfaced while building
  `StudentAssignment`, flagged rather than silently resolved:** (1) Backend LLD §5.4 names this
  aggregate's four revocation events (`StudentAssignmentRemoved`/`StudentTransferred`/
  `StudentGraduated`/`StudentDisabled`) — three of those four exact `event_type` strings already
  belong to `Student`'s own status-change events (Phase 10.1); both aggregates now emit
  identically-named events, distinguishable only by `aggregate_type`, a collision the LLD's own
  event catalog never disambiguated. (2) API Contracts §6's documented example resource for
  `student_assignments` includes `created_at`/`updated_at` — this was a real, then-6-aggregate-
  deep gap (no aggregate anywhere in the codebase exposed these ORM-only audit columns through
  its DTO) until the Final Backend Completion phase closed it across all ten bounded contexts;
  see that phase's own entry below for the resolution and its two remaining, deliberate
  exceptions (`Payment`, `TransportFee`).
- **Billing (C8)** — `Plan` (create/activate/disable, not tenant-owned — Database Design §8.1
  has no `organization_id` column at all), `Subscription` (open/renew/expire/suspend/cancel),
  `Invoice` (issue/mark_paid/void), `Payment` (initiate/mark_processing/mark_paid/mark_failed/
  mark_expired — no `retry()`, a retry is a brand-new `Payment.initiate(...)` with a fresh
  idempotency key), and `TransportFee` (create/mark_paid/mark_overdue/waive, no HTTP route —
  no documented API surface). Only five HTTP routes are exposed, matching API Contracts §4.7
  exactly: `GET /billing/plans`, `GET /billing/subscriptions`, `GET /billing/invoices`,
  `POST /billing/payments`, `POST /billing/payments/callback` — `Plan`/`Subscription` have no
  documented write routes at all (`OpenOrganizationSubscriptionCommand` — ADR-0016 renamed this
  from LLD §4.2's original `RenewParentSubscriptionCommand`, see this bullet's own ADR-0016
  paragraph below — is reachable at the application layer only).
  **Superseded by ADR-0022 (2026-08-06) — see "Payment Provider Architecture + Organization
  Billing" below for the current design.** The next two sentences describe this phase's
  original, now-historical state, kept for the record rather than rewritten in place: originally,
  `PaymentProviderPort` (LLD §4.2, EVC Plus's interface) had no bound adapter — `initiate_payment`
  persisted the `Payment` as `PENDING` then raised `NotImplementedError` at the charge step, the
  same "fail loudly, don't fake" deferral `TrackingApplicationService`'s `LatestPositionPort`
  already established, applied at method-granularity here since only one of ~25 methods needed
  the provider. `POST /billing/payments/callback` was **not** wired to `handle_payment_callback`
  — no signature/secret verification scheme was documented anywhere (a firm requirement per
  `.claude/rules/security.md` #10, but with no specified mechanism at the time), and the
  "provider (signed)" caller had no `Principal` to authenticate through this codebase's
  `require_permission` model; the route existed but always raised `NotImplementedError`. Two real
  documentation conflicts were
  found and resolved, not silently picked: (1) Phase-2 §20.2's narrative says "Mark Invoice
  FAILED" on a declined payment, but Database Design §8.3's `invoices.status` enum has no
  `failed` value — resolved by marking `Payment` (which does have `failed`) and leaving the
  invoice unchanged, `entities.py`'s module docstring has the full reasoning. (2)
  `payments.idempotency_key` is `CHAR(64)` per Database Design §8.3 verbatim, but PostgreSQL
  blank-pads `CHAR(n)` storage and returns it padded on `SELECT` (unlike `VARCHAR`) —
  implemented exactly as documented, with `infra/mappers.py`'s `model_to_payment` stripping the
  padding artifact back off before it reaches the domain layer. **ADR-0016 (RAAD business model
  realignment, billing cutover milestone) deletes the parent-billing path outright, not
  deprecated in place:** `Subscription` no longer carries `subscriber_type`/`subscriber_id`
  (the former polymorphic organization-or-parent subscriber) — it keys on its own
  `organization_id` alone now, matching "RAAD bills Organizations only"; `SubscriberType`/
  `SubscriberId` are removed from `billing/domain/value_objects.py` entirely.
  `RenewParentSubscriptionCommand`/`BillingApplicationService.renew_parent_subscription` are
  replaced by `OpenOrganizationSubscriptionCommand`/`open_organization_subscription` (drops the
  former `parent_id`/`msisdn` fields, keeps `organization_id`/`plan_id`), and
  `SubscriptionRepository.get_active_by_subscriber(subscriber_type, subscriber_id)` is renamed
  `get_active_by_organization(organization_id)`. `Plan.billing_scope`'s `BillingScope` enum
  loses its `PARENT` value (one active value left, `ORGANIZATION`, kept as a "documented seam
  for future variants" the same way `OrgType.SCHOOL` is — not eliminated outright, unlike
  `Organization.billing_model`, below). A same-milestone migration
  (`f4a1c9e7b302_billing_organization_drop_parent_`) drops `subscriptions.subscriber_type`/
  `subscriber_id` (and the `subscriber_type` Postgres `ENUM` type), replacing the composite
  index `ix_subscriptions__subscriber_type_subscriber_id_status` with
  `ix_subscriptions__organization_id_status`; `plans.billing_scope`'s own Postgres `ENUM` type
  is deliberately left with its now-unused `'parent'` value still legal at the DB level — a
  flagged, narrower scope call than what the column drops needed, since narrowing an existing
  native `ENUM` type's allowed values in place would mean recreating the type and every
  dependent column, a materially riskier operation no document asked for. **`Organization.
billing_model`** (`BillingModel` enum, `ENUM(organization_pays,parent_pays)`) is removed
  entirely from `organization/domain/value_objects.py` — not kept as a single-value enum — with
  its own migration column-and-type drop bundled into the same revision;
  `RegisterOrganizationRequest`/`OnboardOrganizationCommand`/`OrganizationDTO`/
  `OrganizationResponse` all drop the field accordingly. **ADR-0006 gained an Amendment section**
  recording that `SubscriptionAccessPolicy` (CR-1, `core/policies/subscription_access.py`) drops
  its `billing_model` input entirely — `subscription_state` (the organization's own subscription
  now, never a parent's) is evaluated unconditionally instead of only for the former
  `PARENT_PAYS` branch; `interfaces/http/policy_guards.resolve_cr1_decision` no longer resolves
  `organization` at all (only `billing`'s own `get_active_subscription_for_organization`), and
  `notifications/events/subscribers.py`'s `_NotificationFanOut` gates each vehicle's
  notifications on the organization's own subscription once per `vehicle_id`, not once per
  parent. `TransportFee` is unaffected (it was never part of the parent-subscription path).
  Usage-metrics tracking/display (active users, MAU, active devices, active vehicles — no
  pricing formula, per this ADR's own explicit scope limit) remains unbuilt, deferred to
  ADR-0020's platform-analytics milestone.
- **Notifications (C7)** — `Notification` (create/mark_read, the in-app store — D2) and
  `DeviceToken` (register/revoke, FCM registration). `notification_preferences` (Database
  Design §7.7) is **not built** — no document gives it an HTTP route and the task's own scope
  named only "Notification aggregate," the same "documented table, no documented read/write
  path, not built this phase" posture `TransportFee`/`trip_students` already establish
  elsewhere. Four routes exposed, matching API Contracts §4.6 exactly (`GET /notifications`,
  `GET /notifications/{id}` — uniform-CRUD addition, `POST /notifications/{id}/read`,
  `POST /notifications/tokens`, `DELETE /notifications/tokens/{id}`); `/ws/notifications` is
  now wired (the WebSocket phase, `modules/notifications/api/ws.py`) — see that phase's own
  Known Gaps entry for the full design. `GET /notifications` and `GET /notifications/{id}` are
  scoped by personal ownership
  (`recipient_user_id = principal.user_id`), not tenant — the first list/get endpoints in this
  codebase scoped that way; a non-owner request raises `NotFoundError` (404), not
  `AuthorizationError`, generalizing Backend LLD §14.3's "404-over-403 avoids confirming
  existence of out-of-scope data" reasoning from its literal cross-tenant wording, flagged as
  this phase's own interpretive extension. `Notification.create()` does **not** call
  `SubscriptionAccessPolicy` — mirrors `transport_ops`/`tracking`'s identical, already-
  established deferral of that policy's actual enforcement-point wiring (`domain/policies.py`'s
  module docstring has the full reasoning); the withholding decision belongs to the not-yet-
  built Notification Worker. **A real event-contract conflict was found and documented, not
  invented around:** API Contracts §13.2 documents a single `student.assignment_changed` wire
  event (payload including `new_status`), but the actually-implemented Backend LLD event
  contract in `transport_ops` is four separate, already-shipped events
  (`StudentAssignmentRemoved`/`StudentTransferred`/`StudentGraduated`/`StudentDisabled`, no
  `new_status` field) — per this phase's explicit instruction, no translation layer was added;
  this module does not consume events at all this phase (broker wiring/event consumption
  explicitly out of scope), so the conflict is recorded but blocks nothing built here.
  `notifications.data_json` is this codebase's first JSON column — PostgreSQL native `JSONB`
  (ADR-0002), no prior precedent to follow.
- **Reporting (C9)** — `ReportRun` (request/start/succeed/fail) is the only aggregate built.
  `ReportDefinition` (Phase 2 §2's conceptual pairing with `ReportRun`) is **not built** — no
  `report_definitions` table exists anywhere in Database Design (the schema authority), no API
  route manages one; flagged as a real Phase-2-vs-Phase-3.2 gap, not silently resolved. `Report
Type` is modeled as an opaque, non-empty, length-validated string over `report_runs.
definition_key` rather than a closed enum — Database Design §8.6 gives that column no
  `ENUM(...)` notation (unlike `status`, which does get one), and neither Project Brief §5.8's
  two prose categories ("Student Transport Reports", "Transport Payment Reports") nor any other
  document gives exact wire-format values; inventing a closed set was avoided. Two routes
  exposed, matching API Contracts §4.8 exactly (`POST /reports/runs` → `202 Accepted` +
  resource, `GET /reports/runs/{id}`) — no list route is documented, so none exists.
  `GET /reports/runs/{id}` is scoped to "requester" (`requested_by = principal.user_id`), the
  same personal-ownership/404-over-403 posture `notifications` already established. Actual
  report rendering (PDF/Excel, the documented Report Worker's job, Backend LLD §11.2) is
  entirely out of scope this phase — `request_report` persists a `QUEUED` row only;
  `start`/`succeed`/`fail` exist at the application layer only, for a not-yet-built worker, no
  HTTP route. `report_runs.params_json` reuses the `JSONB` pattern Notifications established.
- **Video (C6)** — `VideoSession` (`request_live`/`request_playback`/`activate`/`end`/`fail`,
  Database Design §7.4) is the only aggregate built — `playback_requests`, mentioned in the same
  section with no distinct column list of its own, is read as descriptive elaboration of
  `video_sessions.window_start`/`window_end` (already modeled), not a second aggregate; flagged
  in `domain/entities.py`'s own docstring rather than silently invented. **Native JT1078 is
  explicitly not implemented** — per this phase's own explicit instruction, the system is built
  around a `VideoProviderPort` abstraction (MVP: a hardware/vendor video API), deliberately left
  unbound (`infra/adapters.py` is a docstring-only module, mirroring `PaymentProviderPort`'s
  identical "fail loudly, don't fake" precedent). All three documented routes (`POST /video/live`,
  `POST /video/playback`, `POST /video/sessions/{id}/stop`, API Contracts §4.5) call
  `interfaces/http/policy_guards.enforce_d5` — D5 (`.claude/rules/jt1078.md` #1: "Parents have
  zero reachable path to video, anywhere, ever") — before any application-service call, resolving
  the device's `organization_id` via `fleet_device`'s own `DeviceApplicationService` (no
  cross-module DB read). `video_sessions` carries no `stream_url`/token column — that stays
  Redis-owned by the (not-yet-built) JT1078 service itself; a bound provider's return value is
  surfaced only in the API response, never persisted.
- **Platform & Audit (C10)** — `AuditEntry` (`GET /admin/audit`, read-only) and `SystemSetting`
  (`create`/`update_value`, `GET`/`PATCH /admin/settings`) are built; `Integration` (Database
  Design §8.9) is **not** — no document gives it any lifecycle verbs or API route at all (unlike
  `TransportFee`'s "use-case exists, no endpoint" precedent, which at least has documented CRUD
  semantics), flagged in `domain/entities.py`'s own docstring. **`AuditEntry` is never created
  through this module** — see ADR-0007: `audit_entries` is a shared-kernel table (like `outbox`),
  written transactionally by every _other_ module's own `UnitOfWork.commit()` via
  `core.audit.writer.AuditWriter`, with zero changes to any of those modules' own source files.
  `platform_audit` is purely the read side.

### Architecture patterns in use

All ten completed contexts apply the same patterns identically — verified module-by-module in
the Phase 10 architecture review (and, for Billing/Notifications/Reporting/Video/Platform &
Audit, via this codebase's own automated `tests/architecture/` gate suite), not just asserted:

- **Clean Architecture / layered dependency direction:** `api → application → domain`; `infra`
  implements interfaces `domain` defines; domain never imports FastAPI or SQLAlchemy
  (`.claude/rules/backend.md` #2).
- **DDD:** aggregates with buffered domain events (`_AggregateRoot._record()` /
  `pull_domain_events()`, deliberately duplicated per module rather than shared), value objects,
  domain-owned invariants.
- **Repository pattern:** one `SqlAlchemy<Entity>Repository` per aggregate, composing
  `core.db.repository.SqlAlchemyRepositoryBase`; every repository keeps an in-memory identity map
  (`{id: (domain_obj, orm_row)}`) so in-place aggregate mutations get re-projected onto their ORM
  row via `flush_tracked_changes()` immediately before commit.
- **Unit of Work:** `core.db.unit_of_work.SqlAlchemyUnitOfWork`, extended per module
  (`SqlAlchemy<Module>UnitOfWork`) to bundle that module's repositories onto one transaction
  boundary; `commit()` always flushes tracked changes, then delegates to the base class's
  outbox-write-then-session-commit.
- **Domain events + transactional outbox + transactional audit trail:** every state change
  buffers `DomainEvent`s on the aggregate; the application service records them onto the UoW;
  `commit()` writes them to the `outbox` table **and** the `audit_entries` table, in the _same_
  transaction as the business rows (`core/events/outbox.py`, `core/audit/writer.py` — ADR-0007)
  — no event without a committed change, no committed change silently missing its event or its
  audit row. Both are shared-kernel tables owned by no bounded context, mirroring each other
  exactly. The outbox's publish/relay side (`SqlOutboxPublisher`) is bound whenever a broker is
  configured (ADR-0008: Redis Streams, `RAAD_BROKER__URL`) — unbound without one, the same
  "fail loudly" policy every other pending-infra port follows; `audit_entries`' own read side
  (`GET /admin/audit`, `platform_audit`) has no such dependency and is fully live regardless.
- **Dependency injection:** one composition root, `core/di/bootstrap.py`, binding every service,
  repository-bearing UnitOfWork, and cross-cutting port; unbound dependencies fail loudly
  (`LookupError`/`NotImplementedError`) rather than resolving to a fake.
- **RBAC + tenant/region scope + domain policies (ADR-0004/0005/0006):** `require_permission`
  (RBAC, `role_permissions` matrix) and `get_scope`/`ScopeResolver` (region/support assignments)
  both resolve for real now, on every route in every module. `interfaces/http/policy_guards.py`
  (outside any single module, since it orchestrates multiple modules' own application services)
  is the CR-1/D5 enforcement point — `TrackingVisibilityPolicy` on both `tracking` routes,
  `VideoAccessPolicy` on all three `video` routes — composing RBAC + scope + the relevant domain
  policy, never bypassable at any of those five routes.
- **PostgreSQL + SQLAlchemy Async + Alembic + FastAPI:** see Tech stack above.

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
│   │       └── events/       # publishers/subscribers (scaffolded, broker pending)
│   └── interfaces/http/     # api_v1 router aggregation, shared deps, middleware, error handlers
├── migrations/               # Alembic env.py + versions/
└── tests/                    # unit/ (all ten modules' domain/application layers, core/policies,
                               # core/audit), integration/ (live-DB round trips + DB-invariant
                               # proofs for nine modules), contract/ (still empty),
                               # architecture/ (see known gaps below)
```

### Migration status

- **Engine:** PostgreSQL (ADR-0002).
- **Chain:** a single linear Alembic chain, one or more revisions per completed bounded context
  (`transport_ops` has several — one per aggregate), in build order:
  `iam → organization → fleet_device → tracking → transport_ops (student → parent →
student_parents → driver → route → trip → student_assignment) → billing → notifications →
reporting → iam (role_permissions, ADR-0004) → organization (region/support_assignments,
ADR-0005) → video → core (audit_entries, ADR-0007) → platform_audit (system_settings)` (head).
  No branches. Two revisions (`role_permissions`, `audit_entries`) are owned by `core`/shared
  infrastructure rather than a single bounded context's own aggregate build-out — flagged in
  their own migration files' docstrings, not silently folded into an unrelated module's chain
  entry.
- **Verified zero drift:** `alembic check` reports "No new upgrade operations detected." against
  the live schema; the full chain has been round-tripped (`upgrade head → downgrade → upgrade
head`) with no orphaned objects. Every migration that introduces a PostgreSQL native `ENUM`
  type includes an explicit `DROP TYPE` in its `downgrade()` — `alembic revision --autogenerate`
  does not emit this itself, and omitting it breaks re-upgrade after a downgrade.
- `migrations/env.py` imports `infra/models` from all ten modules plus `core.audit.writer`
  (the shared-kernel `audit_entries` model, ADR-0007) — kept in sync 1:1 with which modules/
  shared-kernel packages have a non-empty/model-bearing source file.

### Known gaps (tracked, not hidden)

- **Final Backend Completion phase** closed seven confirmed bugs/gaps surfaced by a fresh
  documentation-vs-code audit, plus CORS (the one Tier-2 item selected for this phase;
  pagination/filtering/sorting and `/ws/tracking`/`/ws/notifications` remained deliberately
  deferred, not attempted this phase — see the Pagination/Filtering/Sorting phase and the
  WebSocket phase, both below, for how each was subsequently closed): (1) **4 endpoints were unreachable by every role, including Founder** —
  `GET /admin/audit`/`GET /admin/settings` required `admin.audit.list`/`admin.settings.list`, and
  `POST /video/live`/`POST /video/playback` required `video.sessions.create`, none of which the
  seeded `role_permissions` matrix (migration `5437a5d1651b`) actually grants; router-side
  `Permission(...)` strings realigned to the deployed matrix rather than touching the migration.
  (2) **Error codes didn't match the documented catalogue** (API Contracts §5.2):
  `AuthenticationError` emitted `AUTHENTICATION_REQUIRED` where the contract names
  `UNAUTHENTICATED`; CR-1/D5 denials fell through to generic `FORBIDDEN` instead of the documented
  `PARENT_ACCESS_DENIED` (with `reason`/`required_action`) and `VIDEO_FORBIDDEN` — new
  `ParentAccessDeniedError`/`VideoForbiddenError` (`core/errors/exceptions.py`) close this. (3)
  **Trip driver-ownership was never verified** — any Driver could start/end any trip, not just
  their own, a gap `routers.py`'s own docstring had correctly flagged as deferred back when RBAC
  itself was still pending; now resolved via `_ensure_driver_owns_trip` (a no-op for Org Admin,
  whose blanket transport_ops grant is an intentional admin-override). (4) `PrincipalResponse.
region_ids` was hardcoded to `[]` despite `ScopeResolver` being real since ADR-0005 — now
  resolved via `effective_org_scope` on login/refresh. (5) ~45 router docstrings across 7 modules
  still claimed `require_permission` "currently raises `NotImplementedError`" — stale since
  ADR-0004, and surfaced verbatim in the generated `/docs` Swagger UI; corrected. (6)
  `interfaces/http/policy_guards.py` — this codebase's own description of itself as "the CR-1/D5
  enforcement point... never bypassable" — had zero test coverage; `tests/unit/
test_policy_guards.py` (23 tests) now covers the `safety_override` reconciliation, ownership
  resolution, and both policy-decision compositions directly, using the same fake-`Container`
  pattern `test_notification_subscribers.py` established. (7) **`created_at`/`updated_at` now
  ship on every aggregate's response** across all ten modules (Organization/Region, Vehicle/
  Device, Student/Parent/Driver/Route/Trip/StudentAssignment, Plan/Subscription/Invoice, User) —
  the domain-entity gap this file used to describe per-module is closed; `Payment` (no audit-
  column bundle, Database Design §8.4) and child/link entities with no independent top-level
  response (`Stop`, `Camera`, `StudentParent`, `DeviceAssignment`) are the only remaining,
  deliberate exceptions. **CORS** (`CorsSettings`, `main.py`) is now configured — previously
  entirely absent, which would have blocked every cross-origin request from a React frontend
  regardless of a valid bearer token; verified against a live `uvicorn` instance, not just unit
  tests. One incidental correction surfaced along the way: this environment does in fact have a
  reachable live PostgreSQL (the organization/fleet_device integration suites ran against it and
  caught a real tz-aware-into-naive-column bug in the new `created_at`/`updated_at` wiring,
  fixed with each module's own pre-existing `_naive`/`_to_naive_utc` helper) — superseding this
  file's earlier "no live PostgreSQL reachable in this sandbox" note for `tracking`'s Redis port;
  that Redis-specific claim itself was not re-verified and may still hold.
- **Pagination/Filtering/Sorting phase** closed the other Tier-2 item Final Backend Completion
  phase deliberately deferred (API Contracts §7/§8), across every module. New framework-free
  primitives (`core/pagination/__init__.py`: `OffsetPageRequest`/`OffsetPage`,
  `CursorPageRequest`/`CursorPage`, `SortSpec`/`FilterCondition`, `parse_sort`/`parse_filters`,
  `encode_cursor`/`decode_cursor`), a generic repository-layer implementation
  (`core/db/repository.py`'s `SqlAlchemyRepositoryBase.list_page`/`list_cursor_page`/
  `FilterField`, enforcing a per-resource filter/sort/search whitelist — never an arbitrary
  client-supplied column), and FastAPI-facing wiring (`interfaces/http/deps.py`'s four new
  `Depends`, `interfaces/http/pagination.py`'s `OffsetPageResponse`/`CursorPageResponse`) back
  every list endpoint in the API. **Offset pagination** (`?page&page_size`,
  `?filter[field]=value`, `?sort=field`, `?q=`) now backs `GET /users`, `GET /organizations`,
  `GET /regions`, `GET /vehicles`, `GET /devices`, `GET /students`, `GET /parents`,
  `GET /drivers`, `GET /routes`, `GET /trips`, `GET /student-assignments`, `GET /billing/plans`,
  `GET /billing/subscriptions`, `GET /billing/invoices`, `GET /admin/audit`, and
  `GET /admin/settings` — every plain resource list this codebase has, per `core/pagination`'s
  own "offered for admin tables where total counts matter" framing. **Cursor pagination**
  (`?limit&cursor`) now backs the two routes API Contracts §4.4/§4.6 explicitly mark
  "(paginated)" with that framing in mind: `GET /tracking/trips/{id}/positions` (over the
  pre-existing `event_time` ascending keyset) and `GET /notifications` (over `created_at`
  descending, newest-first — a flagged interpretive choice, no document specifies ordering).
  Whitelists are uniformly scoped to columns already exposed on each resource's own list
  response, never a wider column set. Three real issues surfaced and were resolved, not silently
  papered over: (1) `platform_audit`'s `SystemSettingModel` has no `id` column (its PK is `key`)
  — `SqlAlchemyRepositoryBase.list_page`'s empty-sort fallback (`order_by(model.id.asc())`)
  would have raised `AttributeError` for this one aggregate alone; guarded by defaulting to
  `[SortSpec(field="key")]` in `PlatformAuditApplicationService.list_system_settings`, the one
  and only place that guard is needed. (2) `notifications`' `Notification.status` is a
  domain-derived `@property` computed from `read_at`, never a persisted `NotificationModel`
  column (Database Design §7.5 has no `status` column at all) — an initial whitelist draft
  included it anyway, which would have turned every `filter[status]=...` request into an
  unhandled `AttributeError` (500) instead of the standard `ValidationError`; caught in review
  and excluded from the whitelist before landing. (3) Wiring cursor pagination into
  `list_student_assignments` (`transport_ops`) meant it could no longer serve the Notification
  Worker's own `notify_vehicle_watchers` recipient-resolution read, which genuinely needs every
  active assignment, not one page of them — `notifications/events/subscribers.py` now reads
  `TransportOpsUnitOfWork.student_assignments.list_all()` directly instead (untouched by this
  phase, still fully unbounded), the one file this phase touched outside its own
  pagination/filtering/sorting concern. As with every `list_all()`/`list_page()` in this
  codebase, none of the above is itself `ScopeResolver`-filtered yet — the same
  system-wide, pre-existing, already-flagged gap below, now inherited by `list_page`/
  `list_cursor_page` too, not newly introduced by this phase.
- **WebSocket phase** implemented `/ws/tracking`/`/ws/notifications` (API Contracts §11),
  closing the last item the Final Backend Completion phase had deferred. Both channels
  authenticate via the **same** JWT verification `SecurityContextMiddleware` uses for REST —
  factored out as `core.security.tokens.resolve_principal_from_access_token`, since
  Starlette's `BaseHTTPMiddleware` (what that middleware is built on) never runs for a
  WebSocket ASGI scope at all, so the entry point necessarily differs even though the
  verification logic is one shared function. Per API Contracts §11.1, the client's first frame
  after connecting must be `{"type":"auth","token":"<jwt>"}` (the "first auth frame" option,
  not a subprotocol); an invalid/missing/timed-out auth closes with a private-use WebSocket
  code (`interfaces/http/realtime.WsCloseCode`: 4400/4401/4403, chosen to mirror this API's own
  400/401/403 HTTP semantics). **Realtime delivery reuses the existing Redis Streams broker
  (ADR-0008)**, not a new mechanism: each channel gets its own `RedisStreamsBrokerConsumer`
  (`ws-tracking`/`ws-notifications` consumer groups, distinct from `core/di/bootstrap.py`'s own
  `notification-worker` group), run as an in-process `BrokerFanOutWorker` (a
  `core.workers.base.Worker`, the identical lifecycle/health/error-isolation shape
  `NotificationWorker` already establishes) started from `main.py`'s own `lifespan` — necessary
  because the Notification Worker itself runs in a wholly separate OS process
  (`interfaces/workers/bootstrap.py`) that cannot push onto a WebSocket the API process holds
  open; only Redis is shared between them. `interfaces/http/realtime.ConnectionManager` is an
  in-memory, per-process registry (each connection tracked with the `Principal` that
  authenticated it) — correct for the single-API-process shape this environment actually runs,
  flagged (mirroring `core.workers.idempotency.InMemoryIdempotencyStore`'s identical caveat) as
  needing a Redis Pub/Sub-backed adapter behind the same interface if a future deployment scales
  to multiple API instances. `/ws/tracking` subscribe authorization reuses `interfaces/http/
policy_guards.resolve_tracking_decision` verbatim (the same `TrackingVisibilityPolicy`
  composition the REST tracking routes already enforce), via a new `resolve_vehicle_tracking_
context` helper in that same file (needed because, unlike the REST routes, a subscribe must
  resolve `organization_id` from the `Vehicle` aggregate itself, not a cached position, since a
  client may subscribe before any position has ever arrived). **Live position push
  re-authorizes on every send, not just at subscribe time** — the mechanism `/ws/tracking`
  actually uses to satisfy API Contracts §11.2's "closed server-side immediately on a CR-1
  revoking event": `SubscriptionExpired`/`StudentAssignmentRemoved`/`StudentTransferred`/
  `StudentGraduated`/`StudentDisabled` (the real, shipped CR-1-revocation events) carry no
  `vehicle_id` in their payload at all (`StudentAssignmentRemoved` etc. carry only
  `{actor_id}`), and resolving one back to the specific vehicle(s) it affects would need a
  translation this codebase doesn't have — the same already-flagged `student.assignment_
changed`-vs-four-separate-events gap `notifications/domain/events.py` documents. Rather than
  inventing that resolution, every position forward re-runs `resolve_tracking_decision` fresh
  against current DB state, dropping and closing a now-unauthorized subscriber on the very next
  event for that vehicle — the same safety property (no unauthorized frame ever delivered),
  reusing existing policy code, without the translation layer. Only `TripEnded` (a single,
  certain, already-`vehicle_id`-bearing event) gets the literal, immediate `subscription_closed`
  frame + close the API Contract describes; `access_revoked`/`assignment_inactive`/
  `subscription_expired` as _explicit_ close reasons are not wired this phase — flagged, not
  silently invented around. `/ws/notifications` does **not** re-check CR-1 at all — it is
  already enforced upstream, at `Notification` creation time, by the (separate-process)
  Notification Worker, so a denied parent's `Notification` row is simply never created; this
  channel only checks personal ownership (`recipient_user_id == principal.user_id`), mirroring
  `GET /notifications`'s identical scoping. One real bug was found and fixed via an ASGI-level
  smoke test (`TestClient`/`httpx` is not an approved dependency in this codebase, so an actual
  WebSocket handshake couldn't be driven through the normal test suite — this smoke test drove
  the real `FastAPI` app through raw ASGI scope/queues instead, as a one-off manual verification):
  a malformed, non-ULID `vehicle_id` in a subscribe frame raised `DomainError` uncaught out of
  `handle_subscribe`, which FastAPI's HTTP-only global exception handler cannot safely convert
  to a response on an _already-accepted_ WebSocket — fixed by catching `Exception` (not just
  `AppError`; an unbound-port `LookupError` carries the identical risk) at that boundary,
  logging loudly and closing cleanly instead, mirroring `core.workers.base.Worker._tick`'s own
  "one failure is logged, never left to crash the surrounding loop" principle. Comprehensive
  unit tests cover the shared token resolver, `ConnectionManager`/`BrokerFanOutWorker`/
  `authenticate_connection`, both channels' subscribe/fan-out/lifecycle logic (fake-`WebSocket`/
  fake-`Container` doubles, the same convention `test_policy_guards.py`/`test_notification_
subscribers.py` already establish), and `resolve_vehicle_tracking_context`; a live-Redis
  integration test (`tests/integration/test_realtime_broker_fanout.py`) proves two distinct
  consumer groups each receive their own copy of a published event — skipped in this sandbox
  (no broker reachable, the same pre-existing gap every Redis-dependent test here already
  carries) but ready to run unmodified once one is configured.
- `tests/architecture/` has ten automated boundary-gate tests (domain purity, layer dependency
  direction, module boundaries, API-layer boundaries) enforcing Backend LLD §2.3 across all ten
  completed modules — rule 7 (static proxy) was extended with an explicit `raad.core.*`-origin
  exception (ADR-0007) so `platform_audit`'s own repository can legitimately bind to the
  shared-kernel `AuditEntryRecord` without tripping a false positive.
- Test coverage now spans all ten modules' domain/application layers plus `core/policies` and
  `core/audit`; live-DB integration coverage now spans all ten modules — IAM/Organization/Fleet
  Device/Tracking each got their own dedicated `test_{module}_repository.py` this phase,
  closing the last gap in this list (their `SqlAlchemyUnitOfWork` wiring was previously
  exercised only indirectly via `test_rbac_and_scope_resolver.py`/
  `test_postgres_repository_invariants.py`). Writing `tracking`'s own file caught a real,
  previously-undetected production bug: `SqlAlchemyVehiclePositionRepository.delete_before`
  bound a tz-aware `cutoff` directly against a naive-UTC column, crashing on every real
  invocation — fixed by reusing `mappers._naive`, the same helper `event_time`/`received_at`
  already use. `tests/contract/` is also no longer empty: `test_api_contracts_routes.py`
  validates the built OpenAPI surface against API Contracts §2/§4 (schema-only — `httpx`/
  `TestClient` is not an approved dependency in this environment), and building it surfaced +
  fixed five previously-flagged, now-resolvable missing `GET`-list routes (`/organizations`,
  `/regions`, `/vehicles`, `/devices`, `/users` — each blocked only on ScopeResolver, ADR-0005,
  now resolved). `raad/core/validation/` (`SelfValidating`/`ensure`/`guard_not_none`) was
  retired — zero imports anywhere in the codebase, confirmed by grep before removal; every
  module validates via Pydantic at the API boundary and domain-layer `DomainError`/
  `ValidationError` instead. See `docs/architecture/backend-stabilization-final-report.md` for
  the full per-issue writeup and scored assessment of this entire stabilization phase.
- **The event broker is now chosen and implemented: Redis Streams (ADR-0008)** —
  `core/events/redis_streams.py`'s `RedisStreamsBrokerPort`/`RedisStreamsBrokerConsumer`, bound
  in DI whenever `RAAD_BROKER__URL` is configured (no broker is reachable in this dev sandbox,
  so it stays unbound here — same "fail loudly, don't fake it" policy `db.url`/`redis.url`
  follow). `SqlOutboxPublisher` needed zero changes — it already depended only on the abstract
  `BrokerPort`. `core.workers.scheduler.LockPort` (`RedisLockPort`) and `core.workers.dlq.
DeadLetterQueue` (`RedisDeadLetterQueue`) are likewise now concrete, sharing the broker's own
  Redis connection. Realtime WebSocket fan-out (`/ws/tracking`/`/ws/notifications`) was a
  distinct capability from this phase's own broker/worker plumbing, deferred at the time —
  see the WebSocket phase's own entry below for how it was subsequently built on top of this
  exact broker.
- **Notification Worker built** (`interfaces/workers/notification_worker.py` + `modules/
notifications/events/subscribers.py`): consumes the broker (only started when a
  `BrokerConsumer` is bound), dispatches via `core.events.processor.EventProcessorRegistry` to
  four D1-catalog processors (`trip_started`/`trip_completed`/`approaching_stop`/`arrived_org`),
  resolving recipients via `transport_ops`'s own already-existing application services and
  gating each one through `SubscriptionAccessPolicy` (CR-1) before calling `Notification.
create()` — the enforcement point `notifications/domain/policies.py`'s own docstring had
  named as "the not-yet-built Notification Worker"'s job. `subscription`/`system` notification
  types are **not** auto-triggered from any event — no document names which billing/system
  event(s) should produce one, flagged rather than invented.
- **Report Worker built** (`interfaces/workers/report_worker.py`): polls `queued` `ReportRun`s
  (new `ListReportRunsQuery`/`list_report_runs`, `reporting` module) and attempts rendering via
  the newly-added `ReportRendererPort` abstraction (`reporting/application/ports.py`) — left
  unbound, the identical `PaymentProviderPort`/`VideoProviderPort` "fail loudly, don't fake"
  posture, so every run this worker picks up ends `failed` in this environment (no rendering
  engine exists) rather than sitting `QUEUED` forever.
- **Three scheduled jobs registered** (`interfaces/workers/bootstrap.py`), guarded by
  `RedisLockPort` whenever a broker is configured: `prune_vehicle_positions` (new
  `TrackingApplicationService.prune_position_history` + `VehiclePositionRepository.
delete_before` — a plain bulk `DELETE`, not `PARTITION BY RANGE` + partition-drop, since
  `vehicle_positions` isn't actually partitioned yet, `.claude/rules/database.md` #6's own
  literal mechanism deferred separately), `sweep_expired_subscriptions` and
  `reconcile_expired_payments` (new `BillingApplicationService` methods, both bulk-scan
  orchestration over already-existing `Subscription.expire()`/`Payment.mark_expired()`).
  **Trip generation is deliberately not registered** — Backend LLD §11.2 names "daily trip
  generation" as a Scheduler job, but no document gives any schedule/recurrence data model a
  `Trip` could be generated from; inventing one was out of scope. `TrackingApplicationService`
  is now always constructible (`latest_position_port` optional at the service level, matching
  `BillingApplicationService`/`VideoApplicationService`'s already-established pattern) so the
  retention job — which needs no Redis at all — stays reachable even without one configured;
  only `get_current_vehicle_position` still fails loudly without a bound port.
- **Billing's `PaymentProviderPort` gap is closed (ADR-0022, 2026-08-06)** — a real, verified
  `StripePaymentAdapter` is bound conditionally in DI, and `POST /billing/payments/callback` is
  genuinely wired (HMAC signature verification, `SYSTEM_PRINCIPAL` actor) — see "Payment Provider
  Architecture + Organization Billing" below for the full design. Only a live merchant account's
  credentials remain, same disclosed posture as TLS/Redis. Video's `VideoProviderPort` (no
  vendor/hardware adapter — native JT1078 intentionally postponed per this phase's own explicit
  instruction) still carries the identical "fail loudly, don't fake" posture unchanged.
- RBAC (`role_permissions`) and `ScopeResolver` (`region_assignments`/`support_assignments`)
  editing has no HTTP route yet — `PermissionApplicationService.grant`/`revoke` and
  `ScopeAssignmentApplicationService`'s own grant/revoke methods are reachable at the application
  layer only, the same "use-case exists, no approved endpoint yet" posture as
  `Route.remove_stop`/`Trip.interrupt` (ADR-0004/0005).
- **Tenant Isolation Security Audit & Fix phase (ADR-0021) closed the gap this bullet used to
  describe.** A live-reproduced vulnerability (a brand-new Org Admin's `GET /vehicles` returning
  other organizations' vehicles) triggered a full audit across every organization-facing
  resource. Root cause, confirmed once and present everywhere: `get_by_id` had **no** scope
  filter at all (a read/write IDOR — every `PATCH`/status-transition/`DELETE` route loads its
  aggregate via the same `get()`), and every `list_all`/`list_page`/`list_cursor_page` call site
  passed a hardcoded unrestricted `TenantRegionScope`, exactly the gap this bullet used to name.
  Fixed once, centrally, per `.claude/rules/backend.md` #4 ("resolved once at the edge...
  injected into every repository query automatically — never rely on a call site remembering"):
  `SqlAlchemyRepositoryBase` (`core/db/repository.py`) now takes the caller's `TenantRegionScope`
  at construction and applies it inside `get_by_id`/`list_page`/`list_all`/`list_cursor_page` via
  a new `_apply_scope` method (`scope_by_own_id: bool = False` handles `Organization`, the one
  aggregate that *is* the tenant root rather than owning an `organization_id` column); each
  module's `SqlAlchemyUnitOfWork` passes it into its repositories, set by that module's own
  `get_<module>_uow` FastAPI dependency via `Depends(get_scope)`. Out-of-scope single-resource
  access now 404s (never 403 — matches `notifications`/`reporting`'s existing "never confirm
  existence of another org's data" precedent). Landed module by module — `fleet_device`
  (Vehicle/Device, plus a new `ensure_same_organization` write-side check closing a device↔
  vehicle cross-org assignment bug), `organization` (Organization/Region), `transport_ops` (all
  seven aggregates, plus a new `_enforce_own_organization` authorization-layer check on every
  creation command with a client-supplied `organization_id` — `EnrollStudent`/`CreateRoute` had
  no cross-aggregate reference to transitively validate it against, a real write-side IDOR the
  repository fix alone couldn't close), `billing` (Subscription/Invoice/Payment/TransportFee —
  the audit's highest-severity finding, since `GET /billing/subscriptions`/`GET /billing/
  invoices` leaked every organization's financial data to any caller holding the underlying
  list-only permission, `parent` included), and `iam` (Users — the confirmed `regional_manager`/
  `support_staff` scope-bypass finding; `login`/`refresh` deliberately kept on a **second**,
  unscoped UoW dependency, since no `Principal` exists yet to resolve a scope from at that point
  in the request). An adjacent finding fixed alongside this work: `/ws/tracking` never checked
  RBAC capability at all (no FastAPI dependency chain runs before an accepted WebSocket's own
  message loop), letting `driver`/`finance_staff` subscribe despite holding no `tracking.*`
  permission — closed with an explicit `PermissionEvaluator` check in `handle_subscribe`. 68 new
  tests (15 unit, 53 live-Postgres integration) plus a live two-organization verification script
  (30/30 checks passing — cross-tenant GET/PATCH/DELETE/list/filter-bypass/write-side-IDOR
  denial, `/ws/tracking`'s capability and cross-tenant checks) confirm the fix; see
  `docs/architecture/adr/0021-tenant-scope-enforcement-at-repository-layer.md` for the full
  design record. `notifications`/`reporting`/`tracking`/`video` needed no fix — independently
  re-verified as already correctly scoped (personal-ownership or CR-1/D5-gated, not
  `organization_id`-list-scoped in the way this bullet described). The frontend needed no fix
  either — exhaustively checked, zero instances of client-side org-based filtering anywhere,
  confirming the leak was identical via direct API calls, not masked by the UI.
- **Real, unresolved documentation gap** (Reporting, Phase 17): Phase 2 Enterprise Architecture
  §2/§10.1 names a `ReportDefinition` domain concept as a documented pairing with `ReportRun`,
  but Database Design (the schema authority) never gives it a table, and no API route manages
  one. `ReportType`/`report_runs.definition_key` is therefore an opaque string, not a closed
  catalog — this will need resolving by an approved documentation update (a `report_definitions`
  table and/or a formal enum) before report content generation can be meaningfully implemented.
- **Real, unresolved event-contract conflict** (Notifications, Phase 16): API Contracts §13.2's
  documented `student.assignment_changed` wire event (with a `new_status` payload field) does
  not match the four separate events `transport_ops.StudentAssignment` already emits
  (`StudentAssignmentRemoved`/`StudentTransferred`/`StudentGraduated`/`StudentDisabled`, no
  `new_status` field). No translation layer exists anywhere in this codebase. This will need
  resolving — by an approved documentation update, not code-level invention — before the
  Notification Worker (event consumption) can be built.

This section must be kept current as further bounded contexts are completed — update it rather
than letting it drift, the same discipline this rewrite itself was triggered by.

## Frontend Implementation Status

The React web dashboard (`frontend/`) is being built against a master implementation roadmap —
`docs/architecture/frontend-flutter-master-roadmap.md` — derived from this backend, the ten
bounded contexts above, and an approved UI/UX design (below). That roadmap's phases (F0–F13 for
React, M0–M5 for Flutter) are the authority on sequencing; this section tracks what has actually
landed, the same discipline the backend sections above already follow.

### Design source

The approved visual design lives at `docs/architecture/RAAD Console (Standalone).html` (a
self-contained interactive mockup covering every module — dashboard, org/fleet/people/ops tables,
live tracking, live video, notifications, reports, settings, billing, plus Parent/Driver mobile
app screens) and `docs/architecture/logo-raad.png` (the RAAD mark: a shield containing a location
pin, brand blue `#1E63FF` / brand green `#2FBF4F`). Per this phase's own explicit instruction,
the mockup was **extracted into a design system, not converted 1:1** — every component was
rebuilt as reusable React, with three deliberate, flagged departures from the raw mockup (never
silent): (1) the mockup's ad-hoc per-element pixel values (spacing, font sizes) were rationalized
into one consistent scale (`frontend/src/styles/tokens.css`); (2) its smallest label text
(9.5–10px) was raised to an 11px floor for legibility; (3) several interactive elements in the
mockup had no real accessibility semantics at all (the settings toggle was a plain non-interactive
`<div>`, the drawer had no dialog role/Escape handling) — rebuilt with real ARIA roles/keyboard
support rather than copied as-is. The mockup also depicts zero loading states and zero
empty/zero-result states anywhere (every table shows fixed sample rows) — `Skeleton` and
`EmptyState` components were added because every real network-backed view needs both, not
because the design specified them.

### Two-dashboard architecture

RAAD ships two distinct dashboards, not one app with a role switcher (the mockup's own "tap role
to switch view" affordance was a demo convenience, not a real product behavior — a `Principal` has
exactly one role per session, so no production UI cycles between them):

- **Platform Dashboard** (`/platform/*`) — Founder, Regional Manager, Support Staff, Finance
  Staff. Manages the whole platform across every organization, tenant provisioning included
  (`/platform/organizations` is where new organizations — and their Org Admin accounts — are
  created). Scoped server-side by RBAC + `ScopeResolver`, not by the frontend.
- **Organization Dashboard** (`/org/*`) — Org Admin only. Shows only that Org Admin's own
  organization (`organization_id` scoping enforced server-side); has no "Organizations" nav item
  at all, since creating tenants isn't this role's job.
- Driver and Parent have **no web dashboard** — both are mobile-only roles
  (`.claude/rules/flutter.md` #1). If either reaches the web login, `MobileOnlyPage` shows a
  clear "use the RAAD mobile app" message instead of a broken or empty shell.

This mapping lives in `shared/auth/dashboard.ts` (`getDashboardType`/`getDashboardHomePath`) and
drives the post-login redirect ("authenticate once, land on the correct dashboard") plus
`router.tsx`'s two `RouteGuard`-gated route subtrees. Per-role nav trees live in
`app/layout/navConfig.ts` (`platformNav`/`organizationNav`, filtered by `getNavForRole`) — one
real, flagged deviation from a literal per-role reading of the mockup: **Live Video is absent
from every platform role's nav**, not just hidden from Parents, because `.claude/rules/api.md` #2
documents `/video` as "Org-Admin only," not "Org-Admin plus RAAD staff." Finance Staff's nav is
additionally pruned to Dashboard/Organizations/Billing/Reports per their documented "billing
scope only" access (`.claude/rules/security.md` #3) — this is presentation only, matching
`.claude/rules/frontend.md` #2; the backend's own RBAC matrix remains the real gate regardless of
what this nav shows or hides.

### Phase F0 — Design System & Cross-Cutting Infrastructure (complete)

Delivered per the roadmap's own F0 scope: design tokens (`styles/tokens.css`, `styles/global.css`
— colors/typography/spacing/radii/shadows/motion, extracted and rationalized from the approved
mockup; dark-mode CSS-variable mechanism is in place but not populated, since the approved design
specifies only one settings _toggle_ for a dark theme with no corresponding palette anywhere —
flagged, not invented); a reusable component library (`shared/components/`: `Button`, `Badge`,
`Card`, `Avatar`, `IconButton`, `LiveIndicator`, `Input`, `Select`, `Toggle`, `FormField`,
`DataTable`/`FilterChips`/`Pagination`/cell helpers, `DetailDrawer`, `EmptyState`, `Skeleton`,
`Toast`, `Logo`, `LoadingScreen`); the app shell (`app/layout/`: `Sidebar`, `TopBar`, `AppShell`,
`navConfig`, `PageHeaderContext` — a small store each feature page calls via `usePageHeader(title,
subtitle)` instead of `AppShell` needing to know every route's copy in advance); the two-dashboard
routing above; a rebuilt, branded `LoginPage`; and `PlaceholderPage` (every nav item routes to a
real page — the built feature or an honest "being built next" state — never a dead link or 404).
The RAAD logo is wired into the sidebar, login page, browser favicon, and a branded
`LoadingScreen`. The dashboard home page deliberately shows **no fleet/trip/rider KPI numbers**
yet, even though the mockup depicts fixed sample figures ("48 trips today") — no aggregate summary
endpoint exists on the backend to back them, and fabricating numbers here would break this
project's own "fail loudly, don't fake it" posture; the real KPI grid lands with its own feature
phase.

New dependencies this phase, each mapping to one F0 need with no substitute already in the repo:
`lucide-react` (the approved design's icon set is Lucide's exact kebab-case names —
`data-lucide="building-2"` etc. — used verbatim, so this is the only choice that doesn't mean
redrawing 50+ icons by hand), `@fontsource/manrope`/`sora`/`jetbrains-mono` (self-hosted versions
of the design's three exact typefaces — an improvement over the mockup's own Google Fonts CDN
calls: no third-party runtime request, works offline), `@tanstack/react-table` (headless table
logic backing `DataTable`; sorting/pagination stay server-driven per API Contracts §7/§8 — this
table never sorts client-side), `clsx` (conditional className composition).

Not built this phase (by design — F0 is tokens/shell/primitives only, not features): any real
data-fetching. Every non-dashboard nav route renders `PlaceholderPage` until its own roadmap phase
(F1 onward) lands.

### Phases F1–F5 and the Device Domain Overhaul (complete) — retroactive catch-up

This section had drifted out of date (`documentation.md` #3): F1 through F5 and the frontend half
of the Device Domain Overhaul were all implemented, but never recorded here. Reconstructed below
from each shipped phase's own in-code docstrings (`app/router.tsx`'s `PLATFORM_BUILT_ROUTES`/
`ORGANIZATION_BUILT_ROUTES` and `app/layout/navConfig.ts`, both verified against the current
repository, not memory) rather than left to drift further — kept intentionally more compact than
F0's/F6's own entries since it's a catch-up, not a live phase record.

- **F1 — Organization & Region Management (C2):** `features/organizations/OrganizationsPage.tsx`
  at `/platform/organizations` (list/detail/create/status-transition, Founder can create, Org
  Admin's own `/org` dashboard has no Organizations nav entry at all per the two-dashboard split).
- **F2 — User & Access Management (IAM, C1):** `features/admin/users/UsersPage.tsx` at
  `/platform/users` — reachable only by roles holding an `iam.users.*` permission
  (`founder`/`regional_manager`/`support_staff`); `org_admin`'s own `/org/users` stays
  `PlaceholderPage` since `org_admin` holds no `iam.users.*` grant at all in the seeded matrix.
- **F3 — Fleet & Device Management (C3):** `features/fleet-devices/vehicles/VehiclesPage.tsx` and
  `.../devices/DevicesPage.tsx`, originally mounted at both `/platform/*` and `/org/*` (one shared
  component pair per entity, not a duplicate per dashboard) — see the Device Domain Overhaul entry
  below for how `/org/devices` was subsequently removed.
- **F4 — Transport Operations, Part A (Students/Parents/Linking, C4):**
  `features/transport-ops/students/StudentsPage.tsx` and `.../parents/ParentsPage.tsx`, the same
  shared-component-across-both-dashboards pattern, including the students↔parents linking UI
  ("Guardians" section on the student detail drawer).
- **F5 — Transport Operations, Part B (Drivers/Routes & Stops, C4):**
  `features/transport-ops/drivers/DriversPage.tsx` and `.../routes/RoutesPage.tsx` — the route
  detail drawer can add stops (`POST /routes/{id}/stops`) but deliberately cannot reorder or
  remove one, with a visible caption explaining why: no HTTP route exists for
  `Route.move_stop`/`remove_stop` yet (backend's own flagged gap).
- **Device Domain Overhaul (frontend half):** added `features/organizations/regions/
RegionsPage.tsx` at `/platform/regions` (Founder-only nav entry — only `founder` holds
  `organization.regions.create`/`.update`); and, matching the backend's RBAC correction that
  `org_admin` now holds zero `fleet_device.devices.*` permissions, **removed** `/org/devices`
  entirely — `VehiclesPage`'s own "Tracking" drawer section (`tracking_status.last_seen_at` only,
  no device identifier) is now the _only_ device-derived data an Org Admin session can reach,
  matching the backend's identical posture.

### Phase F6 — Transport Operations, Part C: Trips & Student Assignments (C4) (complete)

Completes `transport_ops`'s last two aggregates on the frontend, per the roadmap's own
per-aggregate split of this bounded context (F4 Students/Parents → F5 Drivers/Routes → F6 Trips/
StudentAssignment).

**Trips** — `features/transport-ops/trips/`: `TripsPage.tsx` (list/detail, filterable by status
and trip type via two `FilterChips` rows, no search box since `SqlAlchemyTripRepository` whitelists
no searchable fields), `ScheduleTripForm.tsx` (`POST /trips`), `ChangeTripDriverForm.tsx`
(`PATCH /trips/{id}/driver`, a distinct explicit action on the drawer, mirroring
`AssignDeviceForm.tsx`'s precedent), and start/end actions (`POST /trips/{id}/start`/`/end`) gated
by `TripStatus` on the detail drawer's footer. Mounted at `/platform/trips` and `/org/trips` (one
shared `TripsPage` component, matching every prior phase's two-dashboard posture) — both nav
entries already existed in `navConfig.ts` as `PlaceholderPage`s from F0 onward and are now real.
`canManage` (`founder`/`org_admin`) is a presentation hint only; `driver` holds `.start`/`.end` too
but has no web dashboard at all (`.claude/rules/flutter.md` #1), so no ownership-check UI logic
is needed here — Org Admin/Founder's grant is the seeded matrix's intentional admin-override.

**A real, discovered backend whitelist gap, not silently worked around:** `Vehicle`'s own
repository (`fleet_device`) does whitelist `organization_id` as a filter, but
`SqlAlchemyDriverRepository`/`SqlAlchemyRouteRepository` (`transport_ops`) whitelist only `status`
— attempting `filter[organization_id]=...` against `/drivers` or `/routes` raises the backend's own
`ValidationError` ("Field 'organization*id' is not filterable on this resource"), and neither
summary response even carries `organization_id` to filter by client-side. `ScheduleTripForm`'s
vehicle picker is therefore organization-scoped (real backend support); its driver and route
pickers are deliberately global, with a hint explaining a cross-organization pick will be rejected
server-side — the backend's actual `Trip.schedule` `DomainError` is the real safety net, surfaced
verbatim via a toast, not a client-side filter that can't be built honestly. `TripsPage`'s own
vehicle/driver/route \_name* lookups for its list table reuse the same picker functions with no
organization filter (`""`, which `buildOffsetListQuery` omits entirely), capped at the first 100
rows each — the same best-effort limitation `RoutesPage`'s/`StudentsPage`'s own
`organizationNameById` lookups already accept.

**Student Assignment — "the CR-1 access gate" — deliberately has no dedicated nav page or route
at all.** The approved design mockup (`docs/architecture/RAAD Console (Standalone).html`) shows no
"Student Assignments" screen — its own Student Management table already carries `Route`/`Stop`
columns directly on the student row — and `navConfig.ts` has never had a nav entry for it either.
Built instead as `features/transport-ops/student-assignments/StudentAssignmentSection.tsx`, a
second `mapSlot` section on `StudentsPage`'s own detail drawer (stacked above the existing
"Guardians" section), plus `AssignStudentForm.tsx` (`POST /student-assignments`) — imported across
the `students`/`student-assignments` feature-folder boundary (both under the same `transport_ops`
bounded context), a deliberate, narrow exception to `.claude/rules/frontend.md` #1's "no
cross-folder `api.ts` import" discipline: it's a _component_ import, not a duplicated data-fetching
read, and the roadmap itself names `student-assignments` as its own deliverable rather than code
to inline into `students/`. Flagged in both `router.tsx`'s and `StudentsPage.tsx`'s own docstrings,
not silently decided.

Ending an assignment dispatches to one of `removed`/`transferred`/`graduated`/`disabled`
(`POST /student-assignments/{id}/end`, the actual CR-1 revocation event) via a compact
reason-select + button, rather than four separate buttons — a deliberate space-saving choice for
a section nested inside an already-busy drawer. **Shows only the student's current active
assignment, not a history list**: `StudentAssignmentSummaryResponse` carries no `assignedAt`/
`endedAt` to order past (non-active) rows by, so a "previous assignments" list would need an N+1
detail fetch per historical row for no clearly-scoped benefit this phase — a real, deliberate scope
limit, flagged in `StudentAssignmentSection.tsx`'s own docstring rather than silently omitted.

**Testing:** `api.test.ts` for both feature folders (wire-shape/query-string assertions, including
explicit coverage that `listDriversForPicker`/`listRoutesForPicker` never send the unwhitelisted
`organization_id` filter), `TripsPage.test.tsx` (loading/empty/error states, name-lookup
resolution, start/end/change-driver flows, read-only-role gating), `ScheduleTripForm.test.tsx`/
`ChangeTripDriverForm.test.tsx`/`AssignStudentForm.test.tsx` (org-picker branching, dependent-picker
enabling, exact submitted payload shape, validation errors), and `StudentAssignmentSection.test.tsx`
(the CR-1 gate's current-state display, assign/end flows, error state) — `StudentsPage.test.tsx`
was updated to mock the new `student-assignments` module and gained one integration test proving
the "no active assignment → Assign to route" path renders inside the existing drawer.

### Map provider decision + F7 infrastructure prep (ADR-0011)

The roadmap's §3.9 map-provider decision (the last item blocking Phase F7 alongside §4A's B1/B2,
both now complete per ADR-0009/ADR-0010) is resolved: **Mapbox GL JS**, user-confirmed. This phase
prepared F7's frontend integration points without building F7 itself: `frontend/src/shared/map/`
(`MapProvider.ts` — the pluggable interface `.claude/rules/frontend.md` #6 requires; `providers/
MapboxMapProvider.ts` — the concrete implementation; `MapView.tsx` — a thin provider-selecting
React wrapper), the new `mapbox-gl`/`@types/mapbox-gl` dependencies, and `VITE_MAPBOX_ACCESS_TOKEN`
(`frontend/.env.example`, read through `config/env.ts`'s existing single-point-of-truth pattern).
No backend changes were needed — `tracking`'s existing REST/WebSocket contracts already expose
plain decimal-degree `lat`/`lng`, exactly what Mapbox (or any provider) consumes directly. This
phase itself left both "Live Tracking" nav entries (`/platform/tracking`, `/org/tracking`) on
`PlaceholderPage` — F7 (below) is what actually built the page.

### Development Redis environment (ADR-0008/ADR-0010 made runnable)

`docker/docker-compose.yml`'s long-placeholder `redis:` service is now a real definition
(`redis:7-alpine`, AOF persistence, healthcheck) — the first concrete service filled into that
file. `backend/.env.example`'s `RAAD_BROKER__URL`/`RAAD_REDIS__URL` and a new `services/
device-gateway/.env.example`'s `DEVICE_GATEWAY_BROKER_URL` all point at it by convention
(`redis://localhost:6379/0`), so the Business API's own broker (ADR-0008) and the Device Gateway's
event bus/registry projection (ADR-0010) can share one local Redis instance exactly like the
architecture always assumed. `services/device-gateway/scripts/verify_redis_e2e.py` is a new,
committed (not one-off) end-to-end check: a real LSZ registration+position frame over a real
socket, through a real `RedisEventPublisher`, decoded back by the Business API's own real
`_fields_to_event`/`DevicePositionReportedProcessor` — reusable the moment a reachable Redis
exists. **Live verification status, updated 2026-07-24 (follow-up pass):** Docker Desktop, WSL2,
and Redis are now genuinely reachable in this environment and were independently re-confirmed, not
just asserted — see `docs/architecture/adr/0012-development-redis-environment.md`'s Verification
section for the full record. That pass surfaced a real, previously-undetected bug, not just a
missing-infrastructure gap: `verify_redis_e2e.py`'s own PASS only ever proved wiring shape, not
persistence, and `services/device-gateway/src/vendors/lsz/handlers/position_handler.py` was
passing this vendor's out-of-range `heading_deg`/`alarm_flags` straight through instead of
clamping them as its own docstring already claimed — silently failing _every_ real position event
forever via a `tracking.domain` `DomainError` (both of the vendor's own documented worked examples
trigger it, so this was not a rare edge case). Fixed and regression-tested; a real Postgres
`vehicle_positions` row was then independently confirmed, end to end. Two narrower gaps remain,
tracked honestly rather than implied closed: the _standing_ worker process reaching a live event
on its own was not directly observed (it shares a consumer group with a large pre-existing
`outbox` backlog it must drain first); and `vehicle:{id}:last`'s direct Redis cache write (backing
`GET /tracking/vehicles/{id}/latest`'s instant read) is confirmed still unbuilt anywhere in
`services/device-gateway`.

### Device onboarding readiness audit (docs/architecture/device-onboarding-readiness-audit.md)

A full, code-verified (not documentation-inferred) audit of the entire device-onboarding
lifecycle — registration through GPS, live tracking, video, events, notifications, and
persistence — run immediately before Phase F7 below. Confirmed registration and GPS→Postgres
ingestion genuinely work end to end; found several gaps beyond F7's own frontend scope: no writer
for the Redis `vehicle:{id}:last` key anywhere (neither this backend nor the device-gateway), the
geofence pipeline (domain events, table, two of four notification triggers) fully coded but never
actually invoked from the live position-ingestion path, `DeviceOnline`/`DeviceOffline` published
by the device-gateway but never consumed by this backend (`devices.last_seen_at` stays NULL
forever as a result), and no implementation anywhere of boarding/alighting/overspeed/SOS/ignition.
See that document's own "Missing pieces" checklist for the full, severity-ordered list. F7 itself
proceeded independently of all of these, per the audit's own conclusion — none of them gate F7's
own WebSocket/map integration work, only "a real device's activity is fully visible end to end."

### Phase F7 — Live Monitoring & Maps (complete)

`/platform/tracking` and `/org/tracking` are real now — `features/live-monitoring/`
(`LiveTrackingPage.tsx`, one shared component across both dashboards, matching every prior
phase's two-dashboard pattern; `api.ts`). Deliberately the roadmap's "per-vehicle detail view"
half, not an always-every-vehicle-live fleet map: `/ws/tracking` supports exactly one active
vehicle subscription per connection (`tracking/api/ws.py`'s own documented simplification), so
this page is a vehicle picker plus one live map, with `useWebSocketChannel("/ws/tracking", ...)`
sending the one subscribe frame it ever needs whenever the connection is `open` and a vehicle is
selected (also correctly re-subscribes after any auto-reconnect, and re-subscribes to a new
vehicle by sending a fresh frame on the same connection — the backend replaces the prior
subscription itself, no client-side unsubscribe needed). Each `position` frame calls
`MapProvider.updateMarker` (`addMarker` for the first one) — the "hot path for live tracking"
`MapProvider`'s own interface docstring already named. Honest by construction, not just by
intent: since the device onboarding readiness audit (above) confirmed nothing currently writes
`vehicle:{id}:last`, the REST snapshot 404s in most environments — the page shows an explicit "No
live position data" state rather than a fabricated marker, exactly matching the roadmap's own F7
exit criteria; the live WS path still works immediately and independently the moment a real
position event exists. A vehicle's in-progress trip (if any) gets a static route-line + stop-point
overlay (reusing F5's route/stop data) — context only, not live geofence *crossing* events, since
the audit confirmed those are never actually generated anywhere in this codebase today. No ETA
anywhere — no backend capability exists for one (roadmap §2.5), omitted rather than stubbed.
Explicitly out of scope this phase, flagged rather than silently dropped: simultaneous
multi-vehicle live markers on one map (would need either N parallel WebSocket connections or a
backend protocol change, neither attempted) and trip position history/playback
(`GET /tracking/trips/{id}/positions`, a distinct scrubber-style feature, not "live" monitoring).

### Phase F8 — Notifications (complete)

Lands after the Priority 1 production-readiness program and ADR-0019/ADR-0020 (both sections
below) — the roadmap's own F0→F13 sequence simply continues from F7 once those took priority.
`/platform/notifications` and `/org/notifications` are real now — `features/notifications/`
(`NotificationsPage.tsx`, `api.ts`, `labels.ts`, `useUnreadCount.ts`), one shared component
across both dashboards, matching every prior phase's two-dashboard pattern.

**The one fact that shapes this whole phase, confirmed by reading the router before writing any
UI, not assumed:** `GET /notifications` is scoped to `recipient_user_id = principal.user_id`,
**not** `organization_id` — the first (and still only) list endpoint in this codebase scoped by
personal ownership rather than tenant (`notifications/api/routers.py`'s own docstring: "the first
list endpoint in this codebase scoped that way"). There is no "every notification in this
organization" admin view to build here, by design — `NotificationsPage` is each signed-in user's
own inbox, identical regardless of which dashboard path reaches it.

**First cursor-paginated page in this frontend.** Every prior list page uses offset pagination;
`GET /notifications` is one of only two cursor routes API Contracts §7 documents (the other,
`GET /tracking/trips/{id}/positions`, remains unbuilt — F7's own documented scope cut). New,
general-purpose (not notifications-specific) utilities close the gap the same way this codebase's
existing offset helpers already do: `shared/api/types.ts` gained `CursorPageWire`/`toCursorPage`,
`shared/api/listParams.ts` gained `CursorListParams`/`buildCursorListQuery` (`?limit&cursor`, no
`sort` — cursor mode paginates one fixed server-chosen keyset, never a client-chosen sort, per
`core/pagination`'s own module docstring, mirrored rather than inventing a sort option the
backend would reject). The page itself uses `@tanstack/react-query`'s `useInfiniteQuery` (already
a dependency) for "Load more," not hand-rolled page-number state that wouldn't fit a cursor-only
contract anyway.

**Live-updated over `/ws/notifications`** — implemented backend-side since the WebSocket phase
but never previously consumed by any frontend page. Subscribe is implicit per API Contracts
§11.3 (no frame to send); a push triggers a **refetch** of the list/unread-count rather than
merging the WS frame's own fields into the cache, since `_notification_frame`
(`notifications/api/ws.py`) deliberately carries no `status`/`read_at`/`organization_id`/`data` —
only ever representing a brand-new, thus-unread notification, never a full row.

**`AppShell`'s topbar bell badge goes live for the first time.** `TopBar.tsx`'s own
`unreadNotifications` prop has existed since Phase F0 but was never once passed a value anywhere
in the codebase (confirmed by search, not assumed) — the badge simply never rendered. New
`useUnreadCount` counts `status === "unread"` among the most recent 50 notifications (`GET
/notifications`'s own max `limit` — no dedicated count endpoint exists) and increments live on
every WS push, invalidated back down when `NotificationsPage`'s own mark-read mutation succeeds
(one shared query key, `["notifications","unread-count"]`, between the two). A disclosed real
limitation, not a fabricated total: undercounts only past 50 simultaneously-unread items, and
`IconButton`'s own badge already caps its displayed text at "9+" regardless. `AppShell` and
`NotificationsPage` each open their own independent `/ws/notifications` connection when both are
mounted — a real, accepted minor inefficiency (the backend's `ConnectionManager` already supports
multiple connections per user, so this is wasteful, not incorrect), rather than building a
connection-scoped context provider this codebase doesn't have yet for one bell badge.

**Testing:** wire-mapping tests for both the cursor list and mark-read routes, a `useUnreadCount`
hook test, and `NotificationsPage` coverage (empty/error states, rendering, mark-as-read
triggering a refetch, type filter chips, Load More fetching a second page) — one real
react-query v5 behavior learned while writing these: `mutationFn` is invoked with an internal
context object as a second argument beyond the variable this code itself passes, so assertions
check only the first argument. `AppShell.test.tsx` updated to mock the new WS hook and `MapView`
(the latter closes a pre-existing, unrelated stderr-noise gap from the dashboard redesign work:
that test renders the real `DashboardHomePage`, which now embeds a live map preview jsdom has no
canvas backend for). `tsc` clean, full suite green (361/361 across 58 files), production build
clean.

### Phase F9 — Billing (complete)

`/platform/billing` and `/org/billing` are real now — `features/billing/`
(`BillingPage.tsx`, `api.ts`, `labels.ts`), one shared component across both dashboards, matching
every prior phase's two-dashboard pattern. API Contracts §4.7 and `billing/api/routers.py`'s own
already-extensive module docstring fully specify this surface; no new ADR was needed.
**Superseded at `/org/billing` specifically by ADR-0022 (2026-08-06)** — see "Payment Provider
Architecture + Organization Billing" below; `/platform/billing` still is exactly this shared
`BillingPage`, unchanged.

**Read-only by design, confirmed before writing any UI code, not assumed:** the router's own
docstring states plainly that no write route exists for `Plan`/`Subscription`/`Invoice` this
phase — the backend phase that built this surface was explicitly scoped to forbid
`POST/PATCH/DELETE` for any of the three. `BillingPage` accordingly never attempts a create/edit
form the API couldn't serve.

**The one real design decision this phase turned on: `POST /billing/payments`.** The route is
fully reachable, but with no `PaymentProviderPort` bound it always persists a `PENDING` `Payment`
row and then raises `NotImplementedError` (500) at the charge step — a guaranteed failure by the
backend's own explicit "fail loudly, don't fake a charge" design. Wiring a "Pay now" control to
it would mean every click both shows a broken action *and* leaves a real, permanently-`PENDING`
database row behind as a side effect. `features/billing/api.ts` builds no `initiatePayment`
client function at all this phase — a documented decision (that file's own docstring), not dead
code nothing calls — extending this codebase's "fail loudly, don't fake it" *data* posture one
step further, to *affordances*: don't offer a control guaranteed to fail either. Revisit once a
real payment-provider account resolves Known Issue #4.

**First tabbed page in this frontend.** Three independent paginated resources (Plans,
Subscriptions, Invoices) don't fit one `DataTable` — a new, small, general-purpose `Tabs`
component (`shared/components/Tabs/`) switches between entire panels, distinct from the
already-existing `FilterChips` (which narrows one list's own rows, never swaps panels). Each tab
reuses the existing `usePaginatedQuery` hook verbatim, gated by `enabled` so only the active tab
fetches.

**A real, confirmed RBAC gap shaped the page's own role-gating** — read directly from the seeded
permission matrix, not inferred from route names: Regional Manager/Support Staff hold
`billing.plans.list` alone, not `billing.subscriptions.list`/`.invoices.list`, which every other
role reaching this page (Founder, Finance Staff, Org Admin) holds all three of. The tab switcher
itself is omitted for that pair of roles and Plans renders directly, rather than three tabs where
two would 403 — mirroring the Founder Dashboard's identical "omit what would 403" precedent
already established for Finance Staff.

**Name resolution reuses the established pattern, not a new one.** Neither `SubscriptionResponse`
nor `InvoiceResponse` carries an organization or plan name, only an opaque id — both resolve via
small, separate, unfiltered lookup reads (capped at 100 rows, falling back to the raw id past
that), the same `regionsLookup`-style precedent `OrganizationsPage` already established.

**Testing:** wire-mapping tests for all three list routes plus the organization-picker lookup,
and `BillingPage` coverage (default Plans tab, tab switching with name resolution, row-click
detail drawer, a visible error state, and — the one genuinely load-bearing test — Regional
Manager seeing Plans-only with `listSubscriptions`/`listInvoices` never called, versus Org Admin
correctly seeing all three tabs). `tsc` clean, full suite green (372/372 across 60 files),
production build clean.

## Production Readiness Hardening (Priority 1)

A full, read-only production-readiness audit (2026-08-02, `docs/PROJECT_STATUS.md` §9) found the
backend/frontend feature work above solid but identified nine concrete gaps standing between this
repository and a real VPS deployment for real Organizations — tracked as `PROJECT_STATUS.md`
§5's Priority 1 list, worked strictly one item at a time (architecture review → implementation →
automated tests → live verification → docs → deployment changes → runbook →
`PROJECT_STATUS.md`/this file updated), never skipping ahead, per the user's explicit process.
`PROJECT_STATUS.md` is the live tracker for exactly where this stands; this section, like
"Frontend Implementation Status" above, collects one paragraph per completed item as it lands.

**Priority 1 Item 1 — Backups (complete).** Closes what had been a real, unconditional
production blocker: zero backup mechanism existed anywhere in the repository
(`infrastructure/backups/` was a single empty placeholder). A new `backup` Docker Compose
service (`docker/backup.Dockerfile`, built `FROM postgres:16-alpine` — reuses its own
`pg_dump`/`pg_restore` rather than installing a separate client toolchain, the same reasoning
`backend.Dockerfile` already gives for `migrate`/`worker` reusing one image) runs continuously
alongside the rest of the stack, calling `scripts/db/backup.sh` on a schedule
(`scripts/db/backup-loop.sh`, `BACKUP_INTERVAL_HOURS`) — no cron daemon, one less moving part.
`backup.sh` dumps via `pg_dump --format=custom` (chosen specifically because it enables
`restore.sh`'s `pg_restore --clean --if-exists`, which a plain-SQL dump can't support as
cleanly), verifies the dump is non-empty before declaring success, and prunes local dumps past
`BACKUP_RETENTION_DAYS`. `scripts/db/restore.sh` is the destructive counterpart — requires an
explicit `--target-url` (never an implicit "current" database) and `--confirm`, specifically so a
mistyped invocation cannot silently wipe the wrong database.

**Off-site copy is a deliberately pluggable, not-yet-wired hook** — the one new dependency this
item adds, `rclone` (MIT license, a single static Go binary, `apk add`-ed only into
`backup.Dockerfile`, never touching `pyproject.toml`/`package.json`), chosen because it speaks
one config format across 40+ storage backends (S3, Backblaze B2, DigitalOcean Spaces, SFTP, ...)
rather than committing this repo to one vendor's SDK before a real destination exists to test
against. Confirmed with the user before building: no VPS or cloud storage account is provisioned
yet, so this phase ships the local mechanism as fully real and live-verified, and leaves
`BACKUP_RCLONE_REMOTE` unset/documented rather than faking an off-site guarantee that doesn't
exist — the same "fail loudly, don't fake it" posture this codebase already applies to
`PaymentProviderPort`/`VideoProviderPort`. An unconfigured remote produces a loud, repeated
warning on every run, never a silent skip. Tracked as `PROJECT_STATUS.md` Known Issue #12, not
left implicit.

**A real bug was found and fixed during live verification, not just claimed passing**: both
scripts originally logged their full connection string — including the plaintext password — on
every run. Caught by actually executing `backup.sh`/`restore.sh` against a real PostgreSQL server
(two disposable, uniquely-named throwaway databases, never the real dev database) rather than
only reading the code; fixed by redacting `user:PASS@` down to `user:***@` for every log line in
both scripts, verified by re-running the same live drill and confirming the redaction. That same
live drill (seed a marker row → back up → restore into a second throwaway database → assert the
row round-tripped → drop both databases) is now the automated, CI-enforced test:
`testing/backups/test_backup_restore.sh` (a new top-level `testing/backups/` directory —
deliberately not under `backend/tests/`, whose taxonomy is fixed to the `raad` Python package's
own layers per `.claude/rules/testing.md` #1; this tests standalone shell tooling operating on a
whole database, the same "cross-cutting operational concern" category `testing/load/` already
established), wired into `.github/workflows/backend-pipeline.yml` reusing that job's existing
live Postgres service container.

Full operator guide — manual backup, restore drills, disaster recovery, configuring a real
off-site remote: `docs/runbooks/backup-and-restore.md`. Zero changes to any bounded context, RBAC/
tenant-isolation code, or database migration — this item touched only Docker/scripts/tests/docs,
exactly its own scope.

**Priority 1 Item 2 — TLS/HTTPS (complete, mechanism-wise; not yet live-tested against a real
domain).** Closes what had been a real, unconditional production blocker: the whole stack ran on
plain HTTP, with `infrastructure/nginx/conf.d/prod.conf`'s own comment already naming the
intended shape — "a `listen 443 ssl` server block... certbot-managed files bind-mounted from the
VPS host... once a real domain/cert exists." This item builds exactly that design, not a
different one; ADR-0013 had deferred it, not left it undecided.

**The chicken-and-egg bootstrap problem** (nginx refuses to start if a `listen 443 ssl` block's
certificate file doesn't exist, but the first certificate can only be obtained by proving domain
ownership over a *working* HTTP server) is solved with an explicit two-phase runbook, not a
clever auto-generating entrypoint — matching this codebase's existing preference for documented
one-time steps (`docs/runbooks/founder-bootstrap.md`'s precedent) over implicit magic.
`prod.conf` (existing file) gained only an ACME-challenge webroot location, staying the safe,
always-bootable default (`docker/.env.example`'s `NGINX_PROD_CONF=prod.conf`). A new
`infrastructure/nginx/conf.d/prod-tls.conf` is the enabled-TLS successor an operator switches to
once `docs/runbooks/tls-setup.md`'s bootstrap — get a certificate while still on plain HTTP, then
flip `NGINX_PROD_CONF` and restart — has actually been run.

**`${DOMAIN_NAME}` substitution uses nginx's own official templating mechanism** (mounting to
`/etc/nginx/templates/default.conf.template` rather than directly to `conf.d/`, standard since
nginx 1.19's Docker image), not a custom render step — its entrypoint substitutes only variable
names actually present in the container's `environment:`, so nginx's own runtime variables
(`$host`, `$request_uri`, etc., never real env vars) pass through untouched. Both `prod.conf` and
`prod-tls.conf` mount through this same path for consistency (a no-op substitution for the
former). Getting `docker-compose.prod.yml`'s `nginx` service to this shape required the `!reset`
YAML tag (Compose's explicit "clear this field" merge-control, the same mechanism `ports: !reset
[]` already established in this same file) on `volumes:`, since the target path changed from the
base file's direct `conf.d/` mount.

**Renewal reloads nginx without mounting the Docker socket.** A new `certbot` service (official
`certbot/certbot` image, no custom Dockerfile — bind-mounts `scripts/tls/certbot-renew-loop.sh`
in, the same "stock image + bind-mounted file" pattern `nginx`'s own service already uses in this
repo) calls `certbot renew --deploy-hook "kill -HUP 1"` on a schedule
(`CERTBOT_RENEW_INTERVAL_HOURS`). The deploy-hook only fires on an actual renewal, and reaches
nginx's master process by sharing its PID namespace (Compose's `pid: "service:nginx"`) —
deliberately not the Docker-socket-mount pattern some nginx+certbot tutorials use, which grants a
container effectively-root host access for the same outcome.

**Testing limitation, disclosed rather than hidden**: this sandbox has no Docker daemon and no
local `nginx`/`certbot` binary (unlike Item 1's Backups, where PostgreSQL's client tools
happened to be locally installed) — neither `nginx -t` nor `docker compose up` could be run.
Verification was YAML structural validation, a hand-written Compose-merge simulation (confirming
the final merged `nginx` service actually publishes both `80` and `443` and no longer mounts
`dev.conf`), and careful manual config review — which caught two real bugs before they could ship
silently: an accidentally-added `ports: !reset []` on `nginx` that would have un-published port
80 in prod entirely (nginx is "the one service meant to be reachable from outside the Docker
network" per this file's own header comment), and `prod-tls.conf`'s original catch-all redirect
that would have sent the nginx container's own Docker healthcheck (a plain-HTTP request to
`127.0.0.1/health`) to an HTTPS URL it has no clean way to validate, turning a healthy container
into a false-negative "unhealthy" the moment TLS activated — fixed by carving out `/health` as a
plain-HTTP exception in the port-80 server block. A real self-signed certificate, generated with
the one crypto tool that *was* locally available (`openssl`), confirmed the `ssl_certificate`/
`ssl_certificate_key` paths match certbot's actual, unchanging output convention
(`/etc/letsencrypt/live/<domain>/{fullchain,privkey}.pem`) — not a substitute for a real ACME
run, but confirms the path convention is right. `docs/runbooks/tls-setup.md` makes an operator's
first genuinely live test a Let's Encrypt **staging** request specifically, so that first real
exercise of this mechanism happens safely, with no rate-limit consequence, before any production
certificate is ever requested. Zero changes to any bounded context, RBAC/tenant-isolation code,
or database migration.

**Priority 1 Item 3 — Auth rate limiting + account lockout (complete).** Closes what had been a
real, unconditional production blocker: `/auth/login` was completely unthrottled —
`interfaces/http/middleware.py` carried only an explicit stub comment ("no rate-limit policy...
has been approved yet"), and nothing in `iam`'s `User` aggregate tracked failed attempts at all.
Two distinct, complementary mechanisms, per this item's own name: **account lockout** (identity-
based — N consecutive failed attempts against *one account* locks it, regardless of source IP)
and **rate limiting** (IP-based — throttles `/auth/login` from *one source*, regardless of which
account(s) it targets).

**Account lockout** lives on the `User` aggregate itself (`modules/iam/domain/entities.py`),
matching this codebase's "aggregates own their own invariants" convention rather than a
bolted-on middleware check: `record_failed_login(*, max_attempts, lockout_duration_minutes,
clock)` increments a counter and, once it reaches `max_attempts`, sets `locked_until = now +
lockout_duration_minutes`; a *prior* lockout window that has already elapsed resets the counter
to zero first, so a single stray failure long after an old lockout expired doesn't immediately
re-lock the account from a stale high count. `is_locked(*, now)` is a pure computed check
(`locked_until is not None and locked_until > now`) — no separate "unlock" write exists, the
window simply elapses. `AuthApplicationService.login()` checks `is_locked` before spending a
bcrypt verify on the password at all, and on a wrong password against a *known* account, commits
the incremented counter and *then* raises — confirmed safe by reading `SqlAlchemyUnitOfWork.
__aexit__`'s actual implementation: it only rolls back when an exception is propagating, and a
`rollback()` called after an already-completed `commit()` has nothing left to undo. A successful
login, or any legitimate password-establishing action (`change_password_hash`/
`set_temporary_password_hash` — the latter is the *existing*, already-permission-gated
`iam.users.reset_password` operator flow), clears lockout state — giving operators a working
unlock path with zero new API surface or RBAC permission, the same reasoning already established
for that flow's other side effects. New `AccountLockedError` (`AuthenticationError` subtype, 401,
`ACCOUNT_LOCKED`, carries `locked_until` via the existing generic `details` dict) resolves through
the existing `isinstance`-walked `_STATUS_TABLE` with no table edit needed. New `LockoutSettings`
(`max_failed_attempts=5`, `lockout_duration_minutes=15`, both configurable) and a migration
(`d4fbe03f2b94`) adding `users.failed_login_attempts`/`locked_until`.

**Rate limiting** is IP-scoped and deliberately the simplest correct primitive — a Redis
`INCR`+`EXPIRE` fixed-window counter (`core/security/login_rate_limiter.py`'s
`LoginRateLimiter`), not a sliding-window/token-bucket algorithm; no requirement here justified
that extra complexity, and account lockout already owns the "one account targeted from many IPs"
case, so duplicating that here would be redundant. New `RateLimitMiddleware`
(`interfaces/http/middleware.py`) fills the file's long-standing stub, deliberately scoped to
`POST /api/v1/auth/login` only — not the general per-route framework the original stub gestured
at and explicitly said was never approved. Resolves `LoginRateLimiter` via `container.
try_resolve(...)`, the same idiom `SecurityContextMiddleware` already uses for `TokenService`;
bound in DI only when `RAAD_REDIS__URL` is configured, reusing the tracking module's existing
Redis client rather than opening a second connection (`core/di/bootstrap.py`'s established
"reuse, don't duplicate" convention). Wired into `main.py` between `CorrelationIdMiddleware` and
`SecurityContextMiddleware` (Starlette runs last-added outermost, so this executes right after
correlation-id binding but before the JWT check) — its `RateLimitedError` (429, `RATE_LIMITED`,
needs its own new `_STATUS_TABLE` entry, unlike `AccountLockedError`) is raised directly rather
than hand-built into a `JSONResponse`, propagating to the same global `AppError` handler every
other error already goes through.

**Two real bugs were found and fixed during live verification, not just asserted away** — the
same "prove it against a real dependency, not just a fake" discipline Item 1's password-redaction
bug and Item 2's `ports: !reset []`/healthcheck bugs already established for this roadmap:

1. A tz-aware/naive datetime bug, the *identical class* of bug `RefreshToken.is_expired` had
   already taught this codebase to guard against (Backend Stabilization phase) — `model_to_user`
   (`modules/iam/infra/mappers.py`) never applied the existing `_aware_utc` conversion on read
   (unlike `model_to_refresh_token`, which already had the fix), so `User.is_locked` crashed with
   `TypeError: can't compare offset-naive and offset-aware datetimes` the instant a real,
   previously-persisted locked account was checked against `Clock.now()` (tz-aware). Never caught
   by unit tests (all fake-repository-backed, never round-tripping a real naive-column read) — only
   the new live-Postgres integration test (`tests/integration/test_iam_repository.py`'s
   `AccountLockoutRepositoryTests`) exercised the actual reload path and caught it. Fixed by
   applying `_aware_utc` uniformly across all four of `model_to_user`'s datetime fields
   (`created_at`/`updated_at`/`last_login_at`/`locked_until`), not just the one that crashed —
   `created_at`/`updated_at`/`last_login_at` aren't compared against `Clock.now()` anywhere today,
   but leaving them naive would silently reintroduce this exact bug the moment one was.
2. `RateLimitMiddleware`'s original design only handled `LoginRateLimiter` being *unbound*
   (`RAAD_REDIS__URL` not configured) — it had no handling for the limiter being bound but the
   underlying Redis connection actually failing. This sandbox's own `RAAD_REDIS__URL` **is**
   configured (`redis://localhost:6379/0`) while no Redis process is actually reachable at that
   address (confirmed: `redis.exceptions.ConnectionError: Error 22 connecting to localhost:6379`)
   — exactly the scenario the original design missed, and the uncaught `RedisError` would have
   taken `/auth/login` down entirely, the worst possible failure mode for an *optional* hardening
   layer. Fixed by catching `RedisError` around the `is_allowed(...)` call and failing open (log a
   warning once, not per-request, then allow the request) — the same "fail loud once, don't
   cascade-fail the platform over an optional hardening layer" posture already established for
   every other optionally-bound Redis port in this codebase, just extended to cover "configured but
   down," not only "never configured."

**Live verification, not just unit tests**: account lockout's full round trip — 5 wrong passwords
via real HTTP requests against a genuinely running `uvicorn` server, then confirmed `ACCOUNT_
LOCKED` (401) even on the correct password on attempt 6 — was exercised end-to-end against a real,
disposable user in the live database, alongside a live-Postgres integration test proving the same
round trip at the repository layer (fail N times → confirm locked in the database → confirm
rejection even with the correct password → advance a `FixedClock` past the window → confirm
unlock). Rate limiting's counting/threshold logic itself is unit-tested only, against a fake
in-memory Redis double (`tests/unit/test_login_rate_limiter.py`) — no reachable Redis server
exists in this sandbox to round-trip the real `INCR`/`EXPIRE` behavior against, tracked honestly
as `PROJECT_STATUS.md` Known Issue #14, not overstated as complete. What *is* live-verified for
rate limiting is the fail-open path above: a real server, real HTTP requests, confirmed via the
server's own structured logs that `login_rate_limiter_unreachable` logged exactly once across six
requests while login kept functioning throughout. 1203 unit tests + 10 architecture-gate tests
pass with zero regressions; the only integration-suite failures are the pre-existing, already-
disclosed "no reachable Redis in this sandbox" gap in unrelated tracking/broker-fanout tests, not
anything this item touched. Zero changes to any bounded context other than `iam`, and zero changes
to RBAC or tenant-isolation code.

**Priority 1 Item 4 — Redis production hardening (complete, mechanism-wise; not yet live-tested
against a real running Redis process).** Closes what had been a real, unconditional production
blocker: `docker-compose.yml`'s `redis` service ran with no password at all, no explicit
persistence policy, and no memory ceiling — `infrastructure/redis/redis.conf.template` was a
literal one-paragraph placeholder ("real values... to be set once the hot-state usage profile...
has finalized"), and that profile has, in fact, finalized over the course of this session (event
broker, latest-position cache, geofence hysteresis state, and — as of Item 3 — a login
rate-limit counter, all sharing one instance).

**Persistence and memory are one deliberately coupled decision**, not two independent tuning
knobs: `--appendonly yes --appendfsync everysec` (AOF, at most one second of loss on a hard
crash — the standard, documented durability/throughput tradeoff, RDB snapshotting left on the
image's own stock schedule as a secondary fallback, not tuned) plus `--maxmemory ${REDIS_
MAXMEMORY:-256mb} --maxmemory-policy noeviction`. The `noeviction` choice is the one genuinely
non-obvious call this item made, traced by actually reading `core/events/outbox.py`'s
`SqlOutboxPublisher.publish_pending`: an outbox row is marked `published_at` — meaning "never
retry this" — in the same transaction as the broker publish call succeeding, *before* any
consumer has read or acknowledged the resulting Stream entry. That means Phase 2 §10's own
framing ("Redis is treated as reconstructable hot state") holds for the cache side (latest
position, geofence state, rate-limit counters — all trivially rebuilt) but **not** for the
broker side: a published-but-unconsumed Stream entry lost to eviction is a real domain event
gone for good, not reconstructable from Postgres. Since `maxmemory-policy` is a server-wide
Redis setting with no per-key-type override, and this MVP topology deliberately keeps broker and
cache on one shared instance/`maxmemory` budget (splitting them onto genuinely separate
processes — the only way to give the cache side a permissive `allkeys-lru` policy safely — is
flagged as a documented future step, not attempted this phase per `.claude/rules/
architecture.md` #7's "no premature microservices... driven by measured load, not speculation"),
the only safe choice is "fail loudly on an OOM error," never silent data loss — the identical
safety-over-convenience posture `.claude/rules/backend.md` #6 already establishes for
safety-over-billing, extended here to safety-over-cache-flexibility.

**Broker and cache now live on separate logical Redis DBs** (0 for `RAAD_REDIS__URL`'s cache/
rate-limit/geofence keys, 1 for `RAAD_BROKER__URL`/`DEVICE_GATEWAY_BROKER_URL`'s event stream/
lock/DLQ state) — not a new idea invented for this item, but adopted from
`.github/workflows/backend-pipeline.yml`'s own CI service containers, which already split them
this way and simply hadn't been carried into the dev/prod Compose defaults. `core/di/
bootstrap.py`'s two `Redis.from_url(...)` calls already used two separate client objects for
exactly this reason (ADR-0008's own "independently configurable settings" precedent), so the
split needed no code change, only a URL/db-number change.

**A real, previously-undiscovered gap was found and closed on the backend's own Redis client
construction**: both `Redis.from_url(...)` calls in `core/di/bootstrap.py` were passing zero
connection-level kwargs — no `socket_connect_timeout`, no `socket_timeout`, no
`health_check_interval` — relying entirely on undocumented redis-py library defaults (confirmed:
redis-py 8.0.1's own `AbstractConnection` defaults to a 5-second connect/socket timeout and no
periodic health check unless explicitly configured). New `RedisConnectionSettings` (`core/
config/settings.py`, shared by both `RedisSettings` and `BrokerSettings` via inheritance) makes
these explicit and independently configurable per client, with slightly tighter defaults (3s/3s/
30s) than the library's own — appropriate for this codebase's request-scoped hot paths (e.g.
`RateLimitMiddleware`, Item 3) where a hung connection attempt is worse than a fast, clean
failure into the "fail open" path Item 3 already built.

**`--requirepass` was previously unset entirely** — the `redis` service accepted any connection
with no credential, mitigated only by the port already being un-published outside the Docker
network in prod (`docker-compose.prod.yml`'s existing `ports: !reset []`) but still a real gap
for anything reachable *inside* that network (every other container in the stack, or a
compromised host). `REDIS_PASSWORD` (`docker/.env`, default `dev-only-change-me`) is now
required by the service's own `--requirepass` and threaded automatically into
`RAAD_REDIS__URL`/`RAAD_BROKER__URL`/`DEVICE_GATEWAY_BROKER_URL` via Compose's own `${VAR}`
substitution — the same convention `RAAD_AUTH__JWT_SECRET_KEY` already established, deliberately
*not* backed by a `Settings.validate_on_startup()` prod-only rejection check, since
`POSTGRES_PASSWORD` (the closest analogous secret) has no such check either — consistency with
an existing precedent, not an inconsistency introduced here.

**A real bug was caught by review before it could ship silently, matching this phase's own
theme**: the original healthcheck (`redis-cli ping`, no credential) would have started failing
with `NOAUTH` the instant `--requirepass` was added, marking every container in the stack
"unhealthy" from that point on. Fixed by switching to `CMD-SHELL` (the only form that expands a
shell variable at healthcheck-run time, not just at `docker compose up` time) and authenticating:
`redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping`.

**`infrastructure/redis/redis.conf.template` is resolved by deletion, not by finally being
filled in** — a deliberate call, flagged rather than silently made: mounting a real `redis.conf`
would need its own envsubst-capable entrypoint (Redis's stock image has no equivalent to
nginx's own built-in templating mechanism, `infrastructure/nginx/`'s already-established
pattern) for no benefit this deployment's tunable count actually needs, when Compose's own
`${VAR}` substitution directly in `command:` already covers everything. This mirrors
`infrastructure/backups/`'s own already-established precedent exactly (Priority 1 Item 1: "no
configuration lives here — the actual mechanism lives in `docker/` instead") —
`infrastructure/README.md` updated to describe `redis/` the same way.

**Testing limitation, disclosed rather than hidden**: this sandbox has no Docker daemon, no WSL2
distribution installed (`wsl --list --verbose` reports zero distributions), and no local
`redis-server` binary — confirmed by direct check, not assumed — so the actual server behavior
(`--requirepass` enforcement, AOF persistence surviving a real restart, `--maxmemory`/
`noeviction` under real memory pressure) has never been exercised against a genuinely running
Redis process, the same category of gap Item 2 (TLS) already carries for its own mechanism.
Verification was YAML structural validation of the merged Compose config (base+dev leaves the
`redis` service fully as the base file defines it; base+prod's existing `ports: !reset []`
survives untouched alongside every new flag) and a live Python-side smoke test — building the
real DI container and inspecting the actual `redis.asyncio.Redis` client's connection-pool
kwargs (confirmed: correct password, correct db number per client, all three new timeout values
present), valid without a reachable server since `Redis.from_url` is lazy and never opens a
socket at construction time. New runbook `docs/runbooks/redis-operations.md` covers the
reconstructability nuance above in full, persistence/auth verification commands, memory-pressure
troubleshooting (`OOM command not allowed` → check `INFO memory` against `REDIS_MAXMEMORY`,
check `XLEN raad:events` for a stuck consumer before assuming "just raise the limit"), password
rotation, and the documented single-instance/no-HA scope decision — Phase 2 §13.3's own roadmap
already names Redis HA as a later-scale concern, not attempted this phase. 1203 unit tests + 10
architecture-gate tests pass with zero regressions. Zero changes to any bounded context, RBAC/
tenant-isolation code, or database migration.

**Continuous completion program (2026-08-03).** The user directed all remaining Priority 1 items
(5–9) be implemented back to back, without stopping for per-item approval, ending in one
consolidated Production Readiness report — a mode change from the strict one-item-at-a-time
cadence Items 1–4 followed. Each item below still gets its own architecture review →
implementation → tests → live verification (wherever a real dependency exists) → docs →
`PROJECT_STATUS.md`/this file update; only the between-items pause is removed.

**Priority 1 Item 5 — Real health checks + minimum monitoring (complete).** Closed Known Issue
#3: `/health/ready` previously only confirmed `Settings` had loaded, never touching the database
or Redis — a broken DB connection would still report "ready", the worst failure mode for a
readiness probe. New `HealthCheckService` (`core/health/service.py`) runs real,
`asyncio.timeout`-bounded (3s) checks — `SELECT 1` for Postgres, `PING` for each of the two Redis
clients (cache and broker, independently, matching Item 4's own DB-split) — always constructible
so an unconfigured dependency reports `not_configured` rather than the service itself needing a
null-check at the call site, the same "service always constructible, individual methods handle
an unbound port" pattern `TrackingApplicationService` already established. Readiness policy: the
database is mandatory (unconfigured or unreachable both fail); Redis/broker are only gating if
actually configured, matching every other conditionally-bound Redis port's existing "fail loudly
per-feature, don't crash the whole app" posture.

**New `/metrics`, hand-rolled, no new Python dependency** (`core/observability/metrics.py`) — a
purpose-built Prometheus-text-exposition renderer chosen over `prometheus-client` for the same
reason `core/pagination`/`core/di` are hand-rolled rather than framework-based: the actual need
(one counter, dependency gauges, a start-time gauge — no histograms/quantiles) doesn't justify a
general-purpose library. `RequestLoggingMiddleware` (already observing every request/response
pair for its own structured log line) increments `raad_http_requests_total` directly — no
separate metrics middleware — labeled by the matched **route template**
(`request.scope["route"].path`, populated by Starlette's own routing by the time `call_next`
returns) rather than the raw request path, deliberately avoiding the unbounded-cardinality bug
that labeling by raw path (one series per resource ID) would introduce.

**Live-verified, not just unit-tested**: a real running `uvicorn` server against this sandbox's
real, reachable Postgres and its genuinely-unreachable Redis produced exactly the designed
`{"status":"not_ready","checks":{"database":"ok","redis":"down","broker":"down"}}` / HTTP 503
response, and `/metrics` correctly accumulated real request counts with route-template labels
(including a 404's raw-path fallback) across a live traffic sequence. A dedicated live
integration test additionally proves `HealthCheckService` distinguishes a genuinely reachable
Postgres host from a genuinely unreachable one (a real connection attempt to a nonexistent
port, not a mock) — 1217 unit tests + 10 architecture-gate tests pass with zero regressions.

**New `prometheus` Docker Compose service** (stock `prom/prometheus:v2.53.0`, no custom
Dockerfile) scrapes `/metrics` via `infrastructure/monitoring/prometheus/prometheus.yml` — not
published to a host port by default, matching every other non-`nginx` service's "don't expose
more than the deployment needs" posture already established. **Grafana dashboards, Sentry error
tracking, and OpenTelemetry tracing were deliberately not built this phase** — each needs a real
external account/target (a live Prometheus instance with real traffic to design dashboard panels
against; a real Sentry DSN; a service-to-service call graph OpenTelemetry would have something
to trace) that this session cannot obtain or fabricate meaningfully, flagged explicitly in
`docs/runbooks/monitoring.md` rather than shipped as dead/unverifiable code — the same "fail
loudly, don't fake it" posture `PaymentProviderPort`/`VideoProviderPort` already establish.
Zero changes to any bounded context, RBAC/tenant-isolation code, or database migration.

**Priority 1 Item 6 — RBAC grant/revoke route (complete).** Closed what had been a real
operational blocker: `PermissionApplicationService` (`iam`) and `ScopeAssignmentApplicationService`
(`organization`) have existed, fully implemented, since the Backend Stabilization phase — both
docstrings named the exact gap this closes ("RAAD can't onboard its own staff without
hand-editing the DB"), reachable at the application layer only. New Founder-only routes:
`GET/POST /roles/{role}/permissions` + `POST /roles/{role}/permissions/revoke` (`iam.
roles_router`), and `GET /scope-assignments/{user_id}` + `POST /scope-assignments/regions`/
`/support` + their own `/revoke` counterparts (`organization.scope_assignments_router`). No
documented API Contracts surface exists for either — built directly on Database Design §4.4's
("editable by Founder... without code change") and §4.6's own schema authority instead, the same
"use-case exists, no approved endpoint yet, built on the schema authority" posture `/drivers`
already established; `organization/domain/entities.py`'s own module docstring, which had named
`region_assignments`/`support_assignments`'s module ownership as an open question, is updated to
record the resolution. New migration (`a1c9e4f2b871`) grants `founder` the six new permissions
(`iam.role_permissions.{list,grant,revoke}`, `organization.scope_assignments.{list,grant,
revoke}`) — the most sensitive action in the system, since it can grant any permission to any
role including itself, so no other role gets it.

**A real, live-caught production bug — not specific to this item's own new code, but only
reachable through it.** Live-testing the new grant route (a real running server, a real Founder
JWT, a real POST) surfaced `asyncpg.exceptions.StringDataRightTruncationError` the instant a real
permission string was granted. Root cause, traced to the actual event factories: `iam.domain.
events.role_permission_granted`/`revoked` built `aggregate_id` as `f"{role}:{permission}"`, and
`organization.domain.events.region_assignment_granted`/`revoked`/`support_assignment_granted`/
`revoked` built it as `f"{user_id}:{region_id}"` (or `organization_id`) — composite strings that
reliably exceed 26 characters (even two concatenated 26-char ULIDs plus a separator already do),
while `outbox.aggregate_id` **and** `audit_entries.entity_id` are both `CHAR(26)`, sized for a
real minted ULID like every *other* event in this codebase actually has. Never caught before
this item: both application services existed since the Backend Stabilization phase, but no HTTP
route (and no live-Postgres integration test) had ever actually exercised them — a fake-backed
unit test can't catch a real column-width constraint at all, which is exactly why this class of
bug keeps surfacing only during this program's live-verification step, not its unit tests.

**Fixed at the right layer, not papered over with truncation.** `RolePermission`/
`ScopeAssignment` are, by `RolePermissionRepository`'s/`ScopeAssignmentRepository`'s own existing
docstrings, "pure grant/revoke reference data, no aggregate lifecycle" — they never had a real
minted ULID identity to begin with, so a composite string was always a fabrication standing in
for one. `core.events.base.DomainEvent.aggregate_id` is now `str | None` (widened alongside the
already-nullable `org_id`/`correlation_id` on the same dataclass — not a novel precedent), and
all six factories now pass `aggregate_id=None`; the full identifying data (role, permission,
user_id, region_id/organization_id) stays exactly where it already was, in `payload`, so no
information is actually lost. `outbox.aggregate_id` needed a real schema change to match —
`CHAR(26) NOT NULL` — closed by a new shared-kernel migration (`f3d8b1a4e6c2`, chained after the
RBAC-grant migration), following the same "owned by `core`, not a single bounded context"
precedent `role_permissions`'/`audit_entries`' own earlier migrations already established.
`audit_entries.entity_id` needed no schema change — it was already nullable, which is in fact
what first suggested this exact fix.

**Live-verified twice, not just asserted fixed**: the exact same grant call that produced the
original `StringDataRightTruncationError` was re-run against the same live server after the fix
and returned a clean `204`, immediately confirmed via a follow-up `GET` showing the new grant
present; the same round trip (grant → confirm → revoke → confirm cleared) was independently
repeated for a region-scope assignment against a real, freshly-created `Region` row, and a
non-Founder caller's attempt was independently confirmed to 403 with `iam.role_permissions.grant`
named in the error. 19 new unit tests (13 covering both application services, which had zero
prior test coverage despite existing since the Backend Stabilization phase, plus 6 asserting
`aggregate_id is None` directly on all six fixed event factories — a permanent regression guard
for this exact bug class). A second, genuinely unrelated rough edge surfaced during the same live
session and was tracked honestly rather than silently absorbed into this item's own fix: a
mistyped `organization_id` in a scope-assignment grant produced a raw, uncaught
`ForeignKeyViolationError` (a correct constraint, an unhelpful 500 instead of a clean 4xx) —
confirmed systemic (`IntegrityError` is caught in exactly one place anywhere in this codebase),
not something this item introduced or fully in scope to fix, recorded as `PROJECT_STATUS.md`
Known Issue #16. 1236 unit tests + 10 architecture-gate tests pass with zero regressions.

**Priority 1 Item 7 — Deployment & rollback runbook, VPS setup guide (complete).** Pure
documentation, zero code changes: two new runbooks closing the two gaps this roadmap item's own
name already specified. `docs/runbooks/vps-deployment.md` covers everything `docker/README.md`
didn't — provisioning the machine itself, not running the stack once it exists: OS baseline,
`ufw` firewall (default-deny, SSH/80/443 only — every other service, `postgres`/`redis`/
`backend`/`prometheus`/etc., stays internal to the Docker network, matching `docker-compose.
prod.yml`'s own existing `ports: !reset []` overrides), installing Docker, and a full
`docker/.env` walkthrough naming exactly which values matter for a real deployment and why
(`POSTGRES_PASSWORD`/`RAAD_AUTH__JWT_SECRET_KEY`/`REDIS_PASSWORD` all need real generated
values; `RAAD_ENVIRONMENT=prod` is what makes `Settings.validate_on_startup()` actually enforce
the JWT-secret one). First boot deliberately stays on plain HTTP (matching `docker-compose.
prod.yml`'s own safe default) before the DNS/TLS handoff to `tls-setup.md`, and the guide's own
"Step 8" end-to-end confirmation checklist deliberately exercises every other runbook this whole
Priority 1 program produced (health checks, Redis persistence, metrics, a real backup/restore
drill) rather than treating them as separate, disconnected concerns.

`docs/runbooks/rollback.md` distinguishes the two independent things that can go wrong in a bad
deploy — application code (reversible by checking out a known-good commit and rebuilding, no
data touched) versus a database migration (reversible via `alembic downgrade`, but **only** when
the migration was genuinely additive and no already-committed application code depends on the
new schema). Explicitly names this codebase's own real precedent for a destructive migration
(ADR-0016's billing cutover, `f4a1c9e7b302`, which dropped `organizations.billing_model` and
two `subscriptions` columns outright) rather than asserting "every migration here is safely
reversible" as a blanket, inaccurate claim — a downgrade of a genuinely destructive migration
can lose data, and the runbook says so plainly, pointing at restoring from backup into a scratch
database first to confirm exactly what would be discarded.

**One real error was caught and fixed before either runbook shipped**, matching this whole
program's own live-verification discipline even for a documentation-only item: the first draft
of `vps-deployment.md`'s Founder-bootstrap command used an incorrect module path
(`raad.interfaces.workers.bootstrap_founder`); cross-checked against `docker/README.md`'s own
already-correct, previously-documented command and `backend/raad/interfaces/cli/
bootstrap_founder.py`'s actual location, and corrected to `raad.interfaces.cli.
bootstrap_founder` before commit. Every other command in both runbooks was similarly checked
against this repository's actual current file paths, module names, and CLI flag names (`--full-
name`, confirmed against the CLI's own `argparse` definition) rather than written from memory.
Necessarily unverified against a real running VPS — none is provisioned in this sandbox — the
same disclosed-limitation posture Items 2 (TLS) and 4 (Redis) already carry for their own
mechanisms.

**Priority 1 Item 8 — Payment provider integration (audited; genuinely blocked on two external
dependencies, no code changes shipped).** Confirmed by re-reading both the actual application-
layer code and every source document in full, not assumed, that `BillingApplicationService.
initiate_payment`/`handle_payment_callback`/`reconcile_expired_payments` are already completely
built and tested (42 passing unit tests, `test_billing_application.py`) — idempotency-key
handling, the full paid/failed state orchestration (marking the invoice paid and renewing the
subscription in the same transaction), and the scheduled reconciliation job all genuinely work
today, entirely independent of whether a real payment provider is ever bound. What remains open
is exactly two things, both external to this engagement, not a coding gap this session declined
to attempt:

1. **No real EVC Plus merchant account or API documentation exists anywhere in this
   engagement.** The only design document that exists, Phase 2 §20 ("Parent EVC Plus Payment
   Workflow"), designs the *workflow* (a sequence diagram and state machine) and explicitly
   disclaims processing payments itself ("this section designs the workflow; it does not process
   payments... RAAD never handles raw card/bank credentials"). Building a concrete
   `EvcPlusPaymentAdapter` against invented endpoint URLs/request-response shapes would embed
   unverified guesses as if they were real, tested integration code — precisely the situation
   `.claude/rules/workflow.md` #8 requires stopping and asking about rather than assuming through.
   **A second, real, previously-unflagged conflict was found while re-reading this section**:
   Phase 2 §20 describes the **Parent-Pays** billing model (a parent subscribing directly, paying
   via their own phone's EVC Plus PIN) — but ADR-0016 (the RAAD business model realignment,
   already fully implemented) removed direct parent billing outright
   (`SubscriberType`/`SubscriberId`/`RenewParentSubscriptionCommand`/`Organization.billing_model`
   all deleted, not deprecated in place — "RAAD bills Organizations only now"). Phase 2 §20's own
   workflow diagram is therefore describing a billing model this codebase no longer has, not
   superseded by any later document that redesigns the *payment* workflow for the
   Organization-only model that replaced it — flagged here per `.claude/rules/documentation.md`
   #2 ("report the conflict explicitly rather than silently picking one"), not resolved either
   way.
2. **`POST /billing/payments/callback`'s own router docstring already correctly identifies its
   two blockers** — independently re-verified against the actual source documents during this
   audit, not superseded by anything found: no signature/secret verification scheme is
   documented anywhere (Phase 2 §20.4 and API Contracts §12 both *mandate* verification but name
   no algorithm, header, or secret/config source — `.claude/rules/security.md` #10 makes this a
   firm invariant, not a permissible simplification to skip), **and** the caller ("provider
   (signed)", API Contracts §4.7's own role column for this one row) has no `Principal` to
   authenticate through this codebase's `require_permission` model — `PaymentCallbackCommand.
   actor: Principal` (`application/commands.py`) has no documented value for a non-human,
   non-RBAC-role caller, and `core.tenancy.principal.Role` defines no "system"/"webhook" member
   to represent one. Inventing a signature scheme or fabricating a placeholder `Principal` to
   force this through the existing shape would both be undocumented behavior shipped as if
   real — the router's own docstring already reached this exact conclusion before this audit;
   this audit independently re-derived and confirmed it, rather than trusting the prose without
   checking.

**A useful, safe check was still worth running given this session's own Item 6 discovery**: with
a real, live-caught `aggregate_id`-overflow bug already found once in this exact class of code
(composite-string aggregate ids exceeding `CHAR(26)`), every other module's domain events were
swept for the same pattern. Confirmed clean: `billing`'s own twenty-odd events all key off a
single real ULID (`plan_id`/`subscription_id`/`invoice_id`/`payment_id`/`transport_fee_id`), and
`platform_audit`'s `SystemSetting` events use `key` directly — already safe by construction,
since `SystemSettingKey`'s own value object enforces a 26-character maximum length precisely to
fit this same shared column, the correct precedent the `RolePermission`/`ScopeAssignment` bug
should have followed from the start. No other latent instance of this bug class exists anywhere
in the codebase as of this audit.

**Recommended path to closing this item for real**: (1) a real EVC Plus (or alternative
provider) merchant account and its actual API documentation, so a genuine, verifiable adapter can
be built and tested against real behavior rather than assumption; (2) a new ADR resolving how a
signed, non-human webhook caller is represented for authorization/audit purposes across this
codebase generally (not just for payments — the identical question would recur for any future
signed-webhook integration), matching this project's own established practice of formalizing
exactly this kind of cross-cutting design decision before implementing against it
(`.claude/rules/workflow.md` #7/#8). No code changed in this item; `PROJECT_STATUS.md`'s Known
Issue #4 carries the full audit trail.

**Priority 1 Item 9 — Mobile App MVP (partial; the honest limit of the continuous-completion
program, and the last item in it).** Built directly against the already-approved
`docs/architecture/frontend-flutter-master-roadmap.md` §5 (Phases M0–M5), not freelanced —
verified that plan exists and is detailed (state-management choice, dependency choices, exit
criteria per phase) before writing any Dart, matching this project's own "verify the design is
approved before implementing" discipline.

**Phase M0 (Foundation) code-complete**: hand-written `StateNotifier`-based Riverpod (not the
`@riverpod` code-generation API, which needs `build_runner` — an unnecessary build-time
dependency for an app this size with no code-gen SDK available to prove it works anyway),
`flutter_secure_storage` holding only the refresh token (the access token stays in
`ApiClient`'s in-memory field, mirroring the roadmap's own stated pattern and the web
dashboard's identical in-memory-access-token posture), a REST client (`ApiClient`) that maps
the backend's real `{error: {code, message, correlation_id, details}}` envelope into a typed
`ApiException` rather than a raw HTTP exception, and a `/ws/tracking` client
(`TrackingWebSocketClient`) implementing the documented protocol exactly — the
`{"type":"auth","token":...}` first-frame handshake, then a `{"channel":"vehicle",
"vehicle_id":...}` subscribe frame, decoding `{"type":"position",...}` pushes. Role-based
routing (`app/app.dart`) uses Dart 3's pattern-matching `switch` expression on a sealed
`AuthState`, branching on the real `principal.role` string `POST /auth/login` returns.

**Phase M2 (Driver) code-complete, one disclosed UX limitation discovered while building it**:
`driver` holds `transport_ops.trips.{list,read,start,end}` in the seeded RBAC matrix, so the
full trip lifecycle is reachable — but `GET /trips` has no "assigned to me" filter, and there is
no endpoint the `driver` role can reach to resolve their own `Driver.id` from their
`Principal.user_id` at all (`driver` holds no `transport_ops.drivers.*` permission, and
`DriverSummaryResponse` doesn't expose `user_id` even if it did). `DriverHomeScreen` therefore
lists every trip in the driver's own organization (already tenant-scoped server-side, ADR-0021)
rather than fabricating a "mine" filter that isn't actually possible — safety is not weakened by
this, since the server independently, correctly enforces "Driver (own)" on start/end regardless
of what the list displays (`_ensure_driver_owns_trip`, already-existing backend code).

**Phase M3 (Parent) partially blocked on a real, previously-undiscovered backend gap, found
specifically because this session tried to wire a real screen against real API contracts
instead of assuming they'd support it.** `GET /parents/{parent_id}/students` requires
`transport_ops.student_parents.list` — Org Admin only in the seeded matrix, not `parent` — and
critically has **no ownership check at all**: `parent_id` comes straight from the path with
nothing verifying it's the caller's own linked `Parent` record. Granting `parent` the permission
without also adding that check would let any parent pass any other parent's `parent_id` and see
their children — a real cross-parent privacy leak in the same family ADR-0021's tenant-isolation
audit already closed at the organization level. `LiveTrackingScreen` itself is fully implemented
and protocol-correct (it only needs a `vehicleId`, not a resolved Parent identity) — but
`ParentHomeScreen` cannot safely wire a real "my children" list to it, so it says so plainly and
offers a manually-entered vehicle-id field as an explicitly-labeled stand-in for testing, not the
intended production UX. `PROJECT_STATUS.md`'s new Known Issue #17 records the recommended fix
(a genuinely self-scoped `GET /me/students`, resolving identity server-side rather than trusting
a client-supplied id) and recommends a short ADR before implementing it, matching this project's
own established process for exactly this kind of design decision.

**Phases M4 (FCM push notifications) and M5 (offline resilience + app-store release) were not
attempted** — M4 needs a real Firebase project (`google-services.json`/
`GoogleService-Info.plist`, real API keys), the identical category of external dependency Item 8
already carries for a real EVC Plus account; M5's release half needs real Play Store/App Store
Connect accounts, and its offline-caching half is only meaningful once M2/M3 are functionally
complete against a resolved backend. A real `mobile-pipeline.yml` (`.github/workflows/`,
mirroring `backend-pipeline.yml`'s exact shape: checkout → `subosito/flutter-action` → `flutter
pub get` → `flutter analyze` → `dart format --set-exit-if-changed` → `flutter test`) and one
widget test (`login_screen_test.dart`, covering the login form's static shape) were added so
Phase M5's "real CI pipeline" exit criterion has something real to build toward.

**The one categorical difference between this item and every other item in this entire
program**: this sandbox has no Flutter/Dart SDK installed at all (`flutter`/`dart` resolve to
nothing on `PATH`, confirmed directly, not assumed) — meaning **none of the ~19 Dart files
written this item have been parsed, analyzed, compiled, or run in any way.** Every other
Priority 1 item retained some independent verification path despite an incomplete target
environment — YAML structurally parsed via a real Python YAML parser for every Docker Compose
change, a live DI container actually built and inspected for backend wiring, real HTTP requests
against a genuinely running `uvicorn` server for every backend behavior change — this item has
none of that. What verification *was* possible: every request/response JSON shape used in the
Dart code was checked directly against the actual FastAPI Pydantic schemas and route
implementations (not assumed or half-remembered), and every file was manually re-read end to end
for Dart syntax correctness against `flutter_riverpod`/`flutter_secure_storage`/
`web_socket_channel`/`flutter_test`'s documented, stable public APIs. That manual review caught
one real bug before commit: the first draft of `AuthRepository.logout()` called `POST
/auth/logout` with `auth: false`, but that route requires `Depends(get_current_user)` — a valid
bearer access token — in addition to the refresh token in its body; fixed to send the current
access token, and ordered correctly in `AuthController.logout()` (revoke-on-server call happens
*before* the local access token is cleared, not after). `mobile/README.md`'s own "Testing
limitation" section states all of this plainly — every M0–M3 "code complete" claim in this
codebase is "written and carefully reviewed, not yet verified" until a real `flutter analyze`/
`flutter test`/`flutter run` actually succeeds against this code.

**This closes the 2026-08-03 continuous-completion program** — all nine Priority 1 items are
now either complete-and-live-verified, complete-with-a-disclosed-testing-limitation, correctly
audited-and-left-unbuilt (external dependency), or built to the honest limit of what this
session could verify. `PROJECT_STATUS.md` §15 carries the full final report.

## Payment Provider Architecture + Organization Billing (ADR-0022, 2026-08-06)

A direct continuation of the program above, at the user's own explicit follow-on directive:
Organization Billing needed a real, self-scoped UI (the shared platform-wide `BillingPage` gave
an Org Admin every organization's rows, not their own), and — per that same directive — "no
placeholder payment functionality should ship... the payment architecture should be
production-ready... leaving only real provider credentials... to be added after VPS deployment,"
targeting **Hostinger VPS via Coolify**. Full design record:
`docs/architecture/adr/0022-payment-provider-architecture.md`. Before implementing, four
genuinely blocking design forks were resolved via `AskUserQuestion`, all four "(Recommended)"
options accepted: (1) Stripe gets a real, verified adapter now; EVC Plus/Zaad stay
interface-complete stubs — no real merchant docs exist for either, and Phase 2 §20's own EVC Plus
workflow document describes a Parent-Pays flow ADR-0016 has since removed outright, a real,
still-unresolved documentation conflict flagged rather than silently picked around. (2) Secrets
are environment variables, composition-root only (`core/di/bootstrap.py`) — never
`SystemSetting`, since `org_admin` holds `admin.settings.read`/`.update` too, which would let any
Org Admin read/tamper with a platform-wide secret. (3) The webhook authenticates via a
per-provider HMAC signature (Stripe's own documented `Stripe-Signature` scheme) over a shared
secret — no `Principal`/RBAC involved at all; `SYSTEM_PRINCIPAL` (moved from
`notifications/events/subscribers.py` to `core/tenancy/principal.py` so both modules share the
one constant, the same "least-bad available role" reuse that module's own Notification Worker
already established) represents the caller for the audit trail only. (4) Coolify owns
reverse-proxy/TLS for its own deployment path — this stack's own `nginx`/`certbot` stay the
alternative generic-VPS path, never both running together.

**Backend — redesigned `PaymentProviderPort`.** Three findings from reading the actual code
before designing anything, not assumed: the existing port (`charge(amount, msisdn, reference) ->
str`) was shaped entirely around mobile money, with no way to carry a client-tokenized card
`payment_method_id`; `Payment.mark_paid`/`mark_failed` had no same-state idempotency guard
(unlike `mark_processing`/`mark_expired`, which already did) — a real bug, since every payment
provider retries a webhook delivery until it gets a `200`, and a duplicate "paid" callback would
have re-run `subscription.renew(...)` a second time, double-advancing the billing period;
`infra/adapters.py` was completely empty. Fixed: `PaymentProviderPort` now has three methods
(`charge`, `verify_webhook_signature`, `parse_webhook_event`) over `PaymentChargeRequest`/
`PaymentChargeResult`/`WebhookEvent` dataclasses supporting both a card token and an msisdn.
`StripePaymentAdapter` (new `httpx` dependency — chosen over the official `stripe` SDK, matching
this codebase's own "hand-roll a narrow need" pattern already established for
`core/pagination`/`core/observability/metrics`) calls the real Payment Intents API
(`confirm=true`, `automatic_payment_methods[allow_redirects]=never` — a deliberate v1 scope cut,
no 3D Secure/SCA flow) and implements Stripe's documented HMAC-SHA256 webhook signature scheme,
verified against self-constructed signature test vectors (no live Stripe account exists in this
environment). `EvcPlusPaymentAdapter`/`ZaadPaymentAdapter` implement the full interface but
`charge`/`verify_webhook_signature` raise a clear "no merchant API documentation exists" error —
the user's own explicit choice, not a lesser effort. The idempotency bug is fixed at both layers
(entity-level same-state no-op + a service-level short-circuit before touching
`Invoice`/`Subscription` at all on an already-terminal `Payment`), with a regression test proving
a replayed "paid" callback doesn't move `current_period_end` twice.

**Backend — the webhook route, wired for real.** `POST /billing/payments/callback` (previously a
documented, deliberate `NotImplementedError` no-op — see the Billing (C8) bounded-context entry
above, now flagged superseded at that point) has no `Depends(require_permission(...))` at all —
the HMAC signature check *is* this route's authentication. A missing/invalid signature is a
`401`, logged (not an `audit_entries` row — no aggregate mutation happens for a rejected request
to attach one to, the same "log loudly, don't cascade-fail" posture the login rate limiter's own
Redis-unreachable path already established). New `GET /billing/payments` (payment history — no
list route existed for `Payment` at all before this) behind a new `billing.payments.list`
permission (Founder/Finance Staff/Org Admin, mirroring `.subscriptions.list`'s grant set). A real
production bug was caught only through live verification, not unit tests (which call the
*service* layer directly, never the FastAPI dependency-injection chain): the webhook route
initially 401'd on `get_scope` even with no signature reached at all, because `get_billing_uow`
transitively depends on an authenticated `Principal` regardless of what the route handler itself
declares — fixed with a new `get_billing_uow_unscoped`, mirroring `iam.api.deps.get_iam_uow`'s
identical `login`/`refresh` precedent for "no Principal exists yet." Live-verified over real
HTTP/real Postgres with fake-but-well-formed Stripe credentials, covering all four webhook
scenarios (no signature, tampered signature, unknown `provider_ref`, unhandled event type). 1330
unit + 10 architecture-gate tests pass, up from 1304.

**Frontend — `OrgBillingPage` + a real "Pay Invoice" flow.** `/org/billing` is now a dedicated
`OrgBillingPage.tsx` (Org Admin's own current subscription/plan, invoices, and payment history,
scoped to `principal.organizationId` throughout) — `/platform/billing` is untouched, still the
shared, cross-organization `BillingPage`. `InvoicesSection` is split into its own component,
mounted only once a subscription id is actually known — deliberately, since `GET
/billing/invoices` is not tenant-scoped server-side (a real, pre-existing gap, not new), so an
unfiltered call at mount time would return every organization's invoices for a moment; this
component structurally cannot make that call before the filter is known. New
`shared/components/ConfirmDialog/` — this frontend's first genuinely consequential/hard-to-reverse
action (charging a real card), so it gets a real confirm step, distinct from every prior
mutation's "loading button + toast" convention (all reversible admin actions). "Pay Invoice"
mounts Stripe Elements (`@stripe/stripe-js` + `@stripe/react-stripe-js`, new dependencies —
required for PCI-compliant client-side card tokenization, not optional: the raw card number never
reaches this backend) inside it; a new `getBillingProviderConfig()` read (against the existing
`GET /admin/settings`, no new route — reads the non-secret `billing_payment_provider`
`SystemSetting` row ADR-0022 seeds) gates whether the card form renders at all, versus an honest
"Online payment is not available yet" state. **A real infinite-render-loop bug was caught while
writing tests, never shipped**: an early test mock for `useStripe`/`useElements` returned a fresh
object identity on every call, and `CardFields`'s `useEffect([stripe, elements, onReady])` re-ran
on every one of those renders, each time handing a new tokenizer up and triggering another
re-render — fixed by making the mock return stable references, matching real Stripe.js's own
memoized context values (the production component itself was never at fault; only the test
double was unstable). 392/392 frontend tests pass (up from 344), `tsc -b` clean, production
build clean.

**Deployment — a Coolify overlay, alongside the existing generic-VPS path.** New
`docker/docker-compose.coolify.yml` — Coolify already runs its own Traefik reverse proxy with
automatic Let's Encrypt TLS, so this stack's own `nginx`/`certbot` must not also run alongside
it. Rather than trying to delete a service via a compose override (not possible in the Compose
spec — overrides can only modify fields on a service already defined, never remove the service
itself), `nginx` (base `docker-compose.yml`) and `certbot` (`docker-compose.prod.yml`) are gated
behind a new `gateway` Compose profile, defaulted on via `docker/.env.example`'s
`COMPOSE_PROFILES=gateway` so every existing dev/generic-VPS command is completely unaffected —
the Coolify path simply never activates that profile. Also fixed a real, pre-existing bug
surfaced while designing the overlay: `infrastructure/nginx/conf.d/frontend.conf` (the SPA
`try_files` fallback) was referenced in `frontend.Dockerfile`'s own comment but never actually
mounted anywhere, so a deep-linked frontend route (e.g. `/org/billing`) 404'd straight from the
frontend container's own nginx in production — fixed on both `docker-compose.prod.yml` and the
new Coolify overlay. New `docs/runbooks/coolify-deployment.md`, flagged like every other
deployment runbook in this repository as mechanism-verified (YAML structural validation, a
hand-written Compose-merge simulation confirming the final service topology) but not live-tested
against a running Coolify instance in this environment — the identical disclosed-limitation
posture TLS/Redis hardening already carry for their own mechanisms.

**What remains, genuinely external, cannot be fabricated:** a real Stripe (or, once real merchant
documentation exists, EVC Plus/Zaad) merchant account's live `secret_key`/`webhook_secret`, and a
real Hostinger VPS + Coolify instance to exercise the new deployment path against. Everything
else this initiative touched is built, tested, and live-verified as far as this environment
allows. `PROJECT_STATUS.md`'s Known Issue #4 and Section 8 carry the full audit trail.

## Canonical `/me` Self-Service Identity Resolution (ADR-0023, 2026-08-07)

At the user's explicit direction — "Implement Known Issue #17 by introducing a single canonical
self-service identity API rather than isolated endpoints" — closes `PROJECT_STATUS.md` Known
Issue #17, discovered while building the Mobile App MVP (Priority 1 Item 9): neither `parent`
nor `driver` had any safe way to resolve its own domain identity (`Parent.id`/`Driver.id`) from
an authenticated `Principal`. `GET /parents/{parent_id}/students` took `parent_id` straight from
the URL path with no ownership check comparing it to the caller's own linked `Parent.user_id`.
Per `.claude/rules/workflow.md` #8, `docs/architecture/adr/0023-canonical-me-identity-resolution.
md` was written and accepted before any implementation, exactly as the Known Issue's own
"recommended fix" had specified.

**One canonical capability, not two unrelated endpoints.** `GET /me` resolves the caller's own
cross-module identity in one place (`user_id`/`role`/`organization_id`, plus `parent_id`/
`driver_id` only when the role matches and a linked row resolves) — `GET /me/students` and
`GET /me/driver-profile` are thin, dedicated views built on that same resolution, not two
one-off lookups each reinventing "how do I find my own `Parent`/`Driver` row." Org Admin (and
every other RAAD-staff role) needs no separate lookup at all — `organization_id` is already on
`Principal` directly, and none of those roles has a second aggregate distinct from `iam.User`
the way Parent/Driver do; closed by construction, flagged explicitly rather than silently
assumed, since the user's own request named "Org Admin, etc." directly.

**Ownership: `iam`, composing `transport_ops`'s own application services — the same legal
cross-module shape ADR-0020's `PlatformStatsApplicationService` already established.** A new
`MeApplicationService` (`iam/application/services.py`) is constructor-injected with
`transport_ops`'s `ParentApplicationService`/`DriverApplicationService`/
`StudentParentApplicationService` — application-layer only, never that module's `domain`/
`infra`, confirmed by re-running `tests/architecture/test_module_boundaries.py` Rule 1 after
implementation, still green. `iam` was chosen as the owning module (not `transport_ops`, even
though every DB read this capability performs happens there) because it already owns
`Principal`/`User`/`GET /auth/me` — the natural conceptual home for "who am I, across the whole
platform," not a `transport_ops`-specific concern that happens to have two current consumers.
`MeApplicationService` needs no `IamUnitOfWork` at all — `Principal` already carries
`user_id`/`role`/`org_id` directly from the verified JWT, no DB round-trip required for the base
fields; its methods take only a `TransportOpsUnitOfWork` per call, resolved via that module's own
already-scoped `get_transport_ops_uow` (imported directly into `iam/api/routers.py`, mirroring
`platform_audit.api.routers`'s existing precedent of importing another module's own `api/deps.py`
function directly).

**Two small, additive mirror-methods, both already precedented 1:1 by an existing sibling
method.** `ParentRepository.get_by_user_id`/`ParentApplicationService.get_parent_by_user_id`
already existed (added during the Backend Stabilization phase for CR-1 enforcement); `Driver`
simply never had the equivalent. New `DriverRepository.get_by_user_id` (domain interface +
`SqlAlchemyDriverRepository` infra implementation — identical non-unique `user_id` filter shape,
`deleted_at IS NULL` scoping) and `DriverApplicationService.get_driver_by_user_id` (returns
`DriverDTO | None`, never raises — "no Driver profile" is an expected, non-exceptional outcome
for a non-driver caller, mirroring `get_parent_by_user_id`'s identical reasoning) close the gap.
`/me/students` reuses `StudentParentApplicationService.list_students_for_parent` **unchanged** —
`MeApplicationService` resolves `parent_id` server-side first, then calls the existing,
already-tested query with that resolved id, rather than duplicating its logic.

**No client-supplied `parent_id`/`driver_id` — structural, not a runtime check.** Every method
`MeApplicationService` exposes takes a `Principal` (or its bare `user_id`) as its only identity
input; the route signatures have no `parent_id`/`driver_id` parameter to accept in the first
place, so there is nothing for a caller to override. This directly closes the class of bug Known
Issue #17 described in `GET /parents/{parent_id}/students` by construction. That existing route
is left exactly as-is — still gated by `transport_ops.student_parents.list`, still unreachable by
`parent`/`driver` today — fixing its own missing ownership check was explicitly out of scope for
this ADR (a materially different risk, since it's usable only by roles that can already see any
organization's data by design). **One real, previously unflagged finding surfaced while
researching this ADR**, recorded rather than silently corrected in place: `transport_ops.
student_parents.list` is not actually Org-Admin-only as CLAUDE.md had previously stated —
`founder`/`regional_manager`/`support_staff` also hold it (a later RBAC migration revoked
`.students.{list,read}`/`.parents.{list,read}` from RAAD-staff roles but never touched
`.student_parents.list`), though `parent`/`driver` still hold neither, so no new exposure results
from this ADR either way.

**Authorization: self-scoping, not RBAC — matching `GET /auth/me`'s existing posture.** Confirmed
against every RBAC migration in the chain: `parent`/`driver` hold no `transport_ops.parents.*`/
`.drivers.*`/`.students.*`/`.student_parents.*` permission today. `/me`, `/me/students`,
`/me/driver-profile` are gated by `Depends(get_current_user)` alone — no `require_permission` —
safe specifically because every response is derived from `principal.user_id` alone, so no
permission grant could make these routes return anyone else's data even if one existed. **Zero
RBAC migration, zero schema migration** — no new column, no new grant.

**404-over-403 when no linked domain record resolves.** `/me/students`/`/me/driver-profile`
raise the existing `NotFoundError` (404) when resolution comes back empty — covering both "this
role has no such profile" and "a role that should have one doesn't, due to a data inconsistency"
with one honest code path, mirroring this codebase's established personal-ownership 404 pattern
(`GET /notifications/{id}`'s non-owner 404). `/me` itself never 404s — `parent_id`/`driver_id`
are simply left `null` when not applicable, since the root identity is always resolvable from a
valid, already-authenticated `Principal`.

**Routes**: `GET /me`, `GET /me/students`, `GET /me/driver-profile` (new `me_router`,
`iam/api/routers.py`, mounted at `/api/v1/me` in `interfaces/http/api_v1.py`) — no documented API
Contracts surface, the same "built directly on schema authority" posture already established for
`/roles/{role}/permissions`/`/scope-assignments`/`GET /billing/payments`. Verified by forcing
`app.openapi()` schema generation (this FastAPI version registers included-router routes lazily —
`app.routes` alone doesn't surface them until the OpenAPI schema is actually built) and
confirming all three paths and response schemas resolve correctly against the real, fully-wired
DI container.

**Testing.** 10 new unit tests (`tests/unit/test_me_application.py`) — plain constructor-argument
fakes mirroring `tests/unit/test_platform_stats_application.py`'s pattern (this service takes its
dependencies directly, not resolved from a `Container`, so no DI-binding trick is needed) —
covering every role's identity resolution, the "no secondary lookup for a role that structurally
can't have one" efficiency property, and both 404 paths. 2 new live-Postgres integration tests
extend the existing driver-repository suite (`get_by_user_id` round trip). A new dedicated
integration file, `tests/integration/test_me_application_integration.py` (4 tests), proves the
actual security property against a real database — the regression proof a fake-backed unit test
alone cannot provide: two real Parents, two real linked Students, `MeApplicationService.
get_my_students` genuinely cannot cross from one to the other. **One real bug caught while
writing that integration test, never shipped**: the first draft wrapped each
`MeApplicationService` call in its own `async with uow:` block at the test level, but the
service's own methods already open/close their own `async with uow:` internally (twice,
sequentially, since `get_my_students` calls two different sub-services on the same `uow`
instance) — `SqlAlchemyUnitOfWork.__aenter__` creates a fresh session on every entry and
`__aexit__` closes and nulls it, so the outer test-level wrapper's own `__aexit__` hit
`SqlAlchemyUnitOfWork.session`'s `RuntimeError` guard ("used outside of `async with`"); fixed by
passing each call an un-entered `UnitOfWork`, exactly matching how the real router hands one over
via `Depends(get_transport_ops_uow)`. Adding the new abstract `DriverRepository.get_by_user_id`
method also broke three pre-existing in-memory `InMemoryDriverRepository` test fakes (`test_
transport_ops_driver_application.py`, `test_transport_ops_trip_application.py`, `test_
transport_ops_driver_domain.py`) that implement the ABC without it — each fixed with the same
`get_by_user_id` mirror already established for the equivalent `InMemoryParentRepository` fake.
1330 unit + 10 architecture-gate tests pass (up from 1320), zero regressions; the full
live-Postgres integration suite (270 tests) passes except the 6 pre-existing, already-disclosed
"no reachable Redis in this sandbox" failures (`test_realtime_broker_fanout.py`/`test_tracking_
redis_latest_position.py`) — unrelated to this change, the same standing gap every other Priority
1 item in this program has carried.

**What remains, not done in this pass, flagged rather than silently implied finished:** wiring
`mobile/lib/features/parent/parent_home_screen.dart` (and the equivalent Driver trip-filter UX)
to these new endpoints — the mobile app has no Flutter SDK in this environment to verify any
change against, the same disclosed Mobile testing limitation Priority 1 Item 9 already carries.
The backend capability itself is real, tested, and live-verified against Postgres; the client
that would consume it is a follow-up. `PROJECT_STATUS.md`'s Known Issue #17 and Section 8 carry
the full audit trail.

## CI Hardening — Frontend + Device Gateway CI (2026-08-07)

`PROJECT_STATUS.md` Development Rules (Section 14) — re-verify the repository, read `CLAUDE.md`,
determine the highest-priority unfinished work, continue only the next approved roadmap item —
led here: every Priority 1 item was complete or externally blocked, so the next actionable item
was Priority 2's "CI hardening" backlog entry, the first of six remaining Priority 2 items with
no genuine blocker (the other five — Live video/JT1078, Reporting renderer, Load testing, Log
shipping, Secrets-manager integration — are each blocked on an unresolved architecture/
documentation gap, a new-dependency decision needing `.claude/rules/workflow.md` #1/#2's
explicit go-ahead, or a real external account, and are recorded as such in `PROJECT_STATUS.md`
Section 5 rather than silently skipped). No new ADR — this is CI/tooling wiring, not business
logic or a bounded-context change, the same posture `backend-pipeline.yml`/`mobile-pipeline.yml`
were themselves built under.

New `.github/workflows/frontend-pipeline.yml` and `device-gateway-pipeline.yml`, both mirroring
`backend-pipeline.yml`'s exact scope discipline (build/install → test only, no lint/security-scan
gate — `eslint` has no config anywhere in `frontend/` yet, and `ruff`/`mypy` remain "not yet
formally approved" per `backend/pyproject.toml`'s own tracked-as-open-item comment, so neither is
invented here) and using only already-approved tooling (`npm`/Vitest for frontend, stdlib
`unittest` + the already-approved `redis>=5.0` for device-gateway) — zero new dependencies, zero
new external accounts. Every command each workflow runs was executed directly in this sandbox
against the current tree before either file was written: frontend 392/392 tests + a clean
production build; device-gateway 333/333 tests. Backend's own unit (1330) and architecture-gate
(10) suites were re-run as a final regression check (untouched by this change) and still pass.

A real, pre-existing documentation drift was found and fixed in the same pass: `mobile-pipeline.
yml`'s own header comment and `ci-cd/pipelines/backend-pipeline.yml`'s status note both still
claimed the frontend/mobile/device-gateway deployables' CI didn't exist, though mobile's own gate
had shipped under Priority 1 Item 9 — both corrected, and all four now-real deployables'
`ci-cd/pipelines/*.yml` index stubs (previously 0-byte files) populated with the same
"organizational index, see the real workflow" comment `backend-pipeline.yml`'s own stub already
established. `jt808-pipeline.yml`'s filename is left as-is (not renamed to
`device-gateway-pipeline.yml`) — the original JT/T 808 code still lives on inside `services/
device-gateway/src/vendors/jt808/` (dormant, ADR-0009/0010), so the name lags the ADR-0010
rename without being outright wrong; renaming it wasn't otherwise in this item's scope.

Not live-tested against a real GitHub Actions run — no way to trigger one in this sandbox — the
same disclosed "mechanism verified locally, not via live CI" posture every other workflow file
in this repository already carries. `PROJECT_STATUS.md`'s CI/CD row (Section 3) and Section 8
carry the full audit trail, including why each of the five other Priority 2 items was skipped
rather than attempted.
