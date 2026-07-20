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
relaying JT808/JT1078 traffic between bus terminals and the platform.

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
genuinely remains (`PaymentProviderPort`/`VideoProviderPort`/`ReportRendererPort` adapters,
`/ws/tracking`/`/ws/notifications`, CI/CD, contract/load tests).

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
  guaranteed-`NotImplementedError` placeholder.
- **Organization** — organizations, regions, tenant hierarchy, and (ADR-0005) `region_assignments`/
  `support_assignments` backing a real `ScopeResolver` (`interfaces/http/deps.get_scope` resolves
  for real now too).
- **Fleet Device** — vehicles, devices, cameras, device↔vehicle assignment lifecycle.
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
  `student_assignments` includes `created_at`/`updated_at`, but no aggregate in this module has
  ever exposed ORM-only audit columns through its DTO — `StudentAssignmentResponse` follows the
  5-aggregate-deep established precedent (omits them) rather than introducing a one-off
  inconsistency; retrofitting all six aggregates is out of this phase's scope.
- **Billing (C8)** — `Plan` (create/activate/disable, not tenant-owned — Database Design §8.1
  has no `organization_id` column at all), `Subscription` (open/renew/expire/suspend/cancel),
  `Invoice` (issue/mark_paid/void), `Payment` (initiate/mark_processing/mark_paid/mark_failed/
  mark_expired — no `retry()`, a retry is a brand-new `Payment.initiate(...)` with a fresh
  idempotency key), and `TransportFee` (create/mark_paid/mark_overdue/waive, no HTTP route —
  no documented API surface). Only five HTTP routes are exposed, matching API Contracts §4.7
  exactly: `GET /billing/plans`, `GET /billing/subscriptions`, `GET /billing/invoices`,
  `POST /billing/payments`, `POST /billing/payments/callback` — `Plan`/`Subscription` have no
  documented write routes at all (`RenewParentSubscriptionCommand`, LLD §4.2, is reachable at
  the application layer only). `PaymentProviderPort` (LLD §4.2, EVC Plus's interface) has no
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
  padding artifact back off before it reaches the domain layer.
- **Notifications (C7)** — `Notification` (create/mark_read, the in-app store — D2) and
  `DeviceToken` (register/revoke, FCM registration). `notification_preferences` (Database
  Design §7.7) is **not built** — no document gives it an HTTP route and the task's own scope
  named only "Notification aggregate," the same "documented table, no documented read/write
  path, not built this phase" posture `TransportFee`/`trip_students` already establish
  elsewhere. Four routes exposed, matching API Contracts §4.6 exactly (`GET /notifications`,
  `GET /notifications/{id}` — uniform-CRUD addition, `POST /notifications/{id}/read`,
  `POST /notifications/tokens`, `DELETE /notifications/tokens/{id}`); `/ws/notifications` is
  **not wired** — mirrors `/ws/tracking`'s identical, already-established deferral
  (`interfaces/http/api_v1.py`'s own module docstring), since both the broker and the
  Notification Worker itself (event consumption, recipient resolution) are out of this phase's
  scope. `GET /notifications` and `GET /notifications/{id}` are scoped by personal ownership
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
  written transactionally by every *other* module's own `UnitOfWork.commit()` via
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
  `commit()` writes them to the `outbox` table **and** the `audit_entries` table, in the *same*
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

- `tests/architecture/` has ten automated boundary-gate tests (domain purity, layer dependency
  direction, module boundaries, API-layer boundaries) enforcing Backend LLD §2.3 across all ten
  completed modules — rule 7 (static proxy) was extended with an explicit `raad.core.*`-origin
  exception (ADR-0007) so `platform_audit`'s own repository can legitimately bind to the
  shared-kernel `AuditEntryRecord` without tripping a false positive.
- Test coverage now spans all ten modules' domain/application layers plus `core/policies` and
  `core/audit`; live-DB integration coverage spans nine modules (IAM/Organization/Fleet
  Device/Tracking still have no dedicated live-DB integration test file, though their
  `SqlAlchemyUnitOfWork` wiring is exercised indirectly via `test_rbac_and_scope_resolver.py`
  and `test_postgres_repository_invariants.py`).
- **The event broker is now chosen and implemented: Redis Streams (ADR-0008)** —
  `core/events/redis_streams.py`'s `RedisStreamsBrokerPort`/`RedisStreamsBrokerConsumer`, bound
  in DI whenever `RAAD_BROKER__URL` is configured (no broker is reachable in this dev sandbox,
  so it stays unbound here — same "fail loudly, don't fake it" policy `db.url`/`redis.url`
  follow). `SqlOutboxPublisher` needed zero changes — it already depended only on the abstract
  `BrokerPort`. `core.workers.scheduler.LockPort` (`RedisLockPort`) and `core.workers.dlq.
  DeadLetterQueue` (`RedisDeadLetterQueue`) are likewise now concrete, sharing the broker's own
  Redis connection. `/ws/tracking`/`/ws/notifications` remain unwired — realtime WebSocket
  fan-out is a distinct capability from the broker/worker plumbing this phase completes, out of
  scope here.
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
- No module's own `list_all()` repository method is filtered by the now-real `ScopeResolver` —
  every one still applies an unrestricted `TenantRegionScope(organization_ids=None)` internally,
  a system-wide gap predating ADR-0005 that ADR-0005 made a real resolver *available* for but did
  not retrofit onto every existing list endpoint (a separate, larger, cross-cutting change).
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
