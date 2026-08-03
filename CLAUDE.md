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
  (`docs/architecture/adr/0019-account-sharing-session-cap.md`): a concurrent-session cap on the
  existing (previously dead) `refresh_tokens` table, configurable per role via the existing
  `SystemSetting` store, plus self-service session list/revoke. Lightweight tier only, by
  explicit user choice — no device fingerprinting/attestation this phase (blocked on the Flutter
  app existing beyond its current empty scaffold).
- **Platform Analytics dashboard**
  (`docs/architecture/adr/0020-platform-analytics-read-model.md`): a new, `platform_audit`-owned,
  cross-module (but never cross-module-DB-reading) stats read-model backing the Super Admin
  dashboard's KPI grid — including building the previously-missing `DeviceOnline`/`DeviceOffline`
  consumer so Online/Offline Devices is a real number, not a fabricated one.

**Implementation status:** architecture accepted; milestone implementation (IAM provisioning
port → org onboarding → billing cutover → device inventory → session cap → platform analytics)
is in progress. **IAM provisioning port, org onboarding, and billing cutover have landed** — see
the Billing (C8) bounded-context entry below for the billing cutover's own full writeup (parent
billing deleted outright: `SubscriberType`/`SubscriberId`/`RenewParentSubscriptionCommand`/
`Organization.billing_model`/`BillingScope.PARENT` all removed, not deprecated in place;
`SubscriptionAccessPolicy` (CR-1) amended per ADR-0006's own Amendment section; a migration
drops `organizations.billing_model` and `subscriptions.subscriber_type`/`subscriber_id`).
**Device inventory has landed** — see the Fleet Device bounded-context entry below for the full
writeup. Session cap and platform analytics remain not-yet-implemented — each milestone's own
entry will replace this line as it lands, following the same "update as it lands" discipline
every other phase in this file already follows.

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
  ADR's `docker/README.md` was corrected).
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
  paragraph below — is reachable at the application layer only). `PaymentProviderPort` (LLD
  §4.2, EVC Plus's interface) has no
  bound adapter — `initiate_payment` persists the `Payment` as `PENDING` then raises
  `NotImplementedError` at the charge step, the same "fail loudly, don't fake" deferral
  `TrackingApplicationService`'s `LatestPositionPort` already established, applied at
  method-granularity here since only one of ~25 methods needs the provider.
  `POST /billing/payments/callback` is **not** wired to `handle_payment_callback` — no
  signature/secret verification scheme is documented anywhere (a firm requirement per
  `.claude/rules/security.md` #10, but with no specified mechanism), and the "provider (signed)"
  caller has no `Principal` to authenticate through this codebase's `require_permission` model;
  the route exists but always raises `NotImplementedError`, flagged in
  `modules/billing/api/routers.py`'s module docstring. Two real documentation conflicts were
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
- Billing's `PaymentProviderPort` (no EVC Plus adapter) and its `POST /billing/payments/callback`
  webhook (no documented signature-verification scheme), and Video's `VideoProviderPort` (no
  vendor/hardware adapter — native JT1078 intentionally postponed per this phase's own explicit
  instruction) all carry the identical "fail loudly, don't fake" posture.
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
