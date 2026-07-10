# Backend — RAAD Business API

FastAPI modular-monolith serving the RAAD Business API. Owns REST + WebSocket delivery to the web
dashboard and mobile app, all business logic, and the transactional outbox that feeds the event bus.
Never terminates a device socket (JT808/JT1078 are separate deployables — see `services/`).

Source of truth: `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md`.

## Structure

```
raad/
├── main.py            # application entrypoint
├── core/               # cross-cutting kernel: config, security, tenancy, db, events,
│                       # errors, logging, validation, pagination, policies, time, ids, di
├── modules/            # one package per bounded context (see below)
├── interfaces/         # delivery mechanisms: http (REST/WS) and workers
└── shared_contracts/   # event schemas and read-models shared across modules
```

## Modules (bounded contexts)

| Module | Context |
|---|---|
| `iam` | Identity & Access — authN, RBAC, sessions |
| `organization` | Organization/Tenant — customer orgs, settings, region hierarchy |
| `fleet_device` | Vehicles and GPS/MDVR devices, assignment lifecycle |
| `transport_ops` | Students, parents, drivers, routes, stops, trips |
| `tracking` | Position ingestion, live state, geofence evaluation |
| `video` | Live-video/playback session control (Org Admin only) |
| `notifications` | Event-driven notification rules and delivery (FCM + in-app) |
| `billing` | Plans, subscriptions, invoices, payments, transport fees |
| `reporting` | Operational/payment reports, dashboards, exports |
| `platform_audit` | System settings, audit log, integrations |

Every module follows the identical internal shape documented in `.claude/rules/backend.md` and
`.claude/rules/architecture.md`. Modules never read another module's tables directly — see
`.claude/rules/database.md`.

## Business entity → module mapping

There is no separate module per business entity — entities are grouped into the ten bounded
contexts above by domain cohesion, per the Phase 2 Domain Architecture (§2) and Phase 3.2 Database
Design. No required entity is missing; each is intentionally merged into the context that owns it:

| Business entity | Bounded context | Notes |
|---|---|---|
| School / Transport Company / Fleet Company (i.e. **Organization**) | `organization` | "School" is a customer `Organization` (`org_type`), not a distinct module — Ch. 6.2. |
| **Student** | `transport_ops` | Owns student ↔ route/stop/parent assignment (`student_assignments`). |
| **Parent** | `transport_ops` | `parents`, `student_parents` — kept with Student rather than IAM because parent access is entirely transport-assignment-scoped, not a general identity concern. |
| **Driver** | `transport_ops` | `drivers` — operational profile tied to trips/vehicles, not device/fleet hardware. |
| **Vehicle** | `fleet_device` | Vehicle is the asset; paired 1:1 with **Device** (GPS/MDVR hardware) in the same context per the device-assignment lifecycle (Phase 2 §19). |
| **Subscription** | `billing` | `plans`, `subscriptions`, `invoices`, `payments`, `transport_fees`. |

This mapping is recorded formally in `docs/architecture/adr/0001-business-entity-module-mapping.md`.
Any future request to split one of these entities into its own module is a bounded-context-boundary
change and requires a new ADR, not an ad hoc refactor.

## Migrations

Alembic. `alembic.ini` at the repo root of this deployable; revisions live in `migrations/versions/`.

## Tests

`tests/unit`, `tests/integration`, `tests/contract`, `tests/architecture` (the last enforces module
dependency-direction and import-boundary rules — see `.claude/rules/testing.md`).

## Foundation (Phase 4.2)

The application is runnable. Implemented, framework-only (no business logic):

- **App factory + lifespan** (`main.py`) — validates settings, configures logging, builds the
  DI container on startup.
- **Settings** (`core/config`) — typed `pydantic-settings`, fail-fast `validate_on_startup()`,
  one sub-config group per concern (§12.3).
- **Structured logging** (`core/logging`) — JSON formatter, request/correlation/tenant context
  binding via `contextvars`, mandatory PII/msisdn redaction (§13).
- **Exception handling** (`core/errors`) — the full `AppError` hierarchy (§14.1), HTTP status
  mapping, and the standard `{ error: {...} }` envelope, registered as global FastAPI handlers.
- **Middleware** (`interfaces/http/middleware.py`) — correlation-ID binding + request logging.
  A rate-limit hook seam is noted but not implemented (no approved policy yet).
- **Tenancy foundation** (`core/tenancy`) — `Principal`, `TenantRegionScope` types and the
  `ScopeResolver` interface (§17.4). No concrete resolution yet — needs the `organization`/
  `iam` modules.
- **Validation infra** (`core/validation`) — generic guard helpers, no business rules.
- **Event infra** (`core/events`) — `DomainEvent` envelope, `OutboxPublisher`/`EventDispatcher`/
  `BrokerPort` interfaces only (§10). No persistence or broker wiring yet.
- **UoW + repository base interfaces** (`core/db`) — `UnitOfWork`, `Repository`,
  `TenantScopedRepository` as pure interfaces (§7, §8). No SQLAlchemy/engine/tables yet.
- **Clock + ID ports** (`core/time`, `core/ids`) — `Clock`/`SystemClock` bound in DI;
  `IdGenerator` is interface-only pending the UUIDv7-vs-ULID decision (§20.2).
- **DI composition root** (`core/di`) — binds `Settings` and `Clock` today; module-specific
  ports are bound as their owning modules/infra land.
- **`/api/v1` versioning + empty module routers** (`interfaces/http/api_v1.py`) — every
  resource prefix from §16.1 is mounted, each pointing at an empty `APIRouter` in its owning
  module (`modules/<context>/api/routers.py`).
- **Health checks** (`interfaces/http/health.py`) — `/health`, `/health/live`, `/health/ready`,
  mounted unversioned since they're infra probes, not business API surface.

Deliberately **not** implemented yet (out of scope for this phase): `core/security` (JWT/RBAC),
`core/policies` (SubscriptionAccessPolicy/VideoAccessPolicy), any module's `application/`,
`domain/`, or `infra/` code, database tables/migrations, repositories, business endpoints, and
worker processes.

## Status

Application foundation only — runnable, but no business logic, CRUD, database tables, or API
endpoints beyond health checks exist yet.
