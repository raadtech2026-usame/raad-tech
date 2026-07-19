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
FastAPI modular monolith with five of its ten bounded contexts fully implemented end-to-end
(domain → application → infrastructure → API → database migration), backed by a live PostgreSQL
schema. The remaining five contexts (`video`, `notifications`, `billing`, `reporting`,
`platform_audit`) are still structural scaffolds only — no domain/application/infra logic, per
`docs/architecture/adr/0001-business-entity-module-mapping.md`'s module list. Treat those five as
genuinely not-yet-decided; do not infer behavior for them from the five completed ones.

### Tech stack (decided)

- **Language/framework:** Python, FastAPI (async, modular monolith — `.claude/rules/architecture.md`).
- **Database:** **PostgreSQL** via the `asyncpg` driver (`ADR-0002`, superseding an earlier MySQL 8.x
  decision — see `docs/architecture/adr/0002-postgresql-migration.md` and
  `.claude/rules/database.md`). Redis is planned for hot state (latest position, sessions, caches)
  but not yet wired.
- **ORM/migrations:** SQLAlchemy 2.x async + Alembic, revisions in `backend/migrations/versions/`.
- **Dependency injection:** a small hand-rolled composition root (`backend/raad/core/di/`), not a
  third-party DI framework.
- **Dev tooling** (pytest, ruff/mypy): still **not formally approved** — `backend/pyproject.toml`'s
  own comments track this as an open item. `black` is in use for formatting but is applied
  inconsistently across the codebase (see the Phase 10 architecture review's Code Quality findings)
  — don't assume every file is currently `black`-clean.

### Completed bounded contexts

Each of the five below has a full `api / application / domain / infra / events` stack (per
`.claude/rules/backend.md` #1) and is registered in `core/di/bootstrap.py` and
`interfaces/http/api_v1.py`:

- **IAM** — users, auth (JWT), RBAC scaffolding (permission matrix itself still pending approval).
- **Organization** — organizations, regions, tenant hierarchy.
- **Fleet Device** — vehicles, devices, cameras, device↔vehicle assignment lifecycle.
- **Tracking** — vehicle positions, geofence crossings (its application service is currently
  unreachable via DI pending a `LatestPositionPort`/Redis implementation — intentional
  "fail loudly" deferral, not a bug).
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

### Architecture patterns in use

All five completed contexts apply the same patterns identically — verified module-by-module in the
Phase 10 architecture review, not just asserted:

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
- **Domain events + transactional outbox:** every state change buffers `DomainEvent`s on the
  aggregate; the application service records them onto the UoW; `commit()` writes them to the
  `outbox` table in the *same* transaction as the business rows (`core/events/outbox.py`) — no
  event without a committed change, no committed change silently missing its event. The
  publish/relay side (`SqlOutboxPublisher`) exists but stays unbound until a broker is chosen
  (Phase 2 §4.3, still open) — this is a backend-wide deferral, not a per-module gap.
- **Dependency injection:** one composition root, `core/di/bootstrap.py`, binding every service,
  repository-bearing UnitOfWork, and cross-cutting port; unbound dependencies fail loudly
  (`LookupError`/`NotImplementedError`) rather than resolving to a fake.
- **PostgreSQL + SQLAlchemy Async + Alembic + FastAPI:** see Tech stack above.

### Project structure (current)

```
backend/
├── raad/
│   ├── main.py            # ASGI app factory / composition root wiring
│   ├── core/               # cross-cutting kernel: config, security, tenancy, db, events,
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
└── tests/                    # unit/ (Transport Ops only today), integration/ contract/
                               # architecture/ (all still empty — see known gaps below)
```

### Migration status

- **Engine:** PostgreSQL (ADR-0002).
- **Chain:** a single linear Alembic chain, one revision per completed bounded context, in build
  order: `iam → organization → fleet_device → tracking → transport_ops` (head). No branches.
- **Verified zero drift:** `alembic check` reports "No new upgrade operations detected." against
  the live schema; the full chain has been round-tripped (`upgrade head → downgrade → upgrade
  head`) with no orphaned objects. Every migration that introduces a PostgreSQL native `ENUM`
  type includes an explicit `DROP TYPE` in its `downgrade()` — `alembic revision --autogenerate`
  does not emit this itself, and omitting it breaks re-upgrade after a downgrade.
- `migrations/env.py` imports `infra/models` from exactly the five completed modules — kept in
  sync 1:1 with which modules have a non-empty `infra/models.py`.

### Known gaps (tracked, not hidden)

- No automated architecture-boundary test suite yet (`tests/architecture/` is empty) — Backend LLD
  §2.3 calls for one; module boundaries currently hold by manual discipline only.
- Test coverage is concentrated almost entirely in Transport Ops; IAM/Organization/Fleet
  Device/Tracking have no automated tests yet.
- RBAC permission matrix, tenant/region `ScopeResolver`, and the event broker are all approved-open
  items — every dependent code path is wired to fail loudly rather than fake a pass.

This section must be kept current as further bounded contexts are completed — update it rather
than letting it drift, the same discipline this rewrite itself was triggered by.
