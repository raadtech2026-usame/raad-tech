# Backend — RAAD Business API

FastAPI modular-monolith serving the RAAD Business API. Owns REST + WebSocket delivery to the web
dashboard and mobile app, all business logic, and the transactional outbox that feeds the event bus.
Never terminates a device socket (JT808/JT1078 are separate deployables — see `services/`).

Source of truth: `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md`.

## Structure

```
raad/
├── main.py            # application entrypoint
├── core/               # cross-cutting kernel: config, security, tenancy, db, events, audit,
│                       # errors, logging, pagination, policies, time, ids, di, workers
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

## Authentication & Security Foundation (Phase 4.3)

Framework-only, no login/business flows. Implemented:

- **JWT token service** (`core/security/tokens.py`) — `TokenService` interface, `JwtTokenService`
  concrete HS256 implementation (stdlib-only, no new dependency). Issues/verifies stateless
  access + refresh tokens; no refresh-token persistence or session management.
- **Password hashing** (`core/security/password_hashing.py`) — `PasswordHasher` interface,
  `Pbkdf2PasswordHasher` concrete implementation (PBKDF2-HMAC-SHA256, stdlib `hashlib`).
- **Password policy** (`core/security/password_policy.py`) — configurable strength rules
  (`AuthSettings.password_policy`).
- **Role & Permission foundation** (`core/security/permissions.py`) — `Permission` type,
  `PermissionEvaluator` interface. No concrete RBAC matrix yet — that's authorization business
  data pending formal approval, owned by `modules/iam` when implemented.
- **Token/claims models** (`core/security/claims.py`, `tokens.py`) — `TokenClaims`, `TokenPair`.
- **Security exceptions** (`core/security/exceptions.py`) — `InvalidTokenError`,
  `TokenExpiredError`, `InvalidCredentialsError`, all `AuthenticationError` subclasses.
- **Security utilities** (`core/security/utils.py`) — constant-time compare, secure token gen.
- **Policy interfaces** (`core/policies/__init__.py`) — generic `Policy`/`PolicyDecision` shape;
  no concrete `SubscriptionAccessPolicy`/`VideoAccessPolicy` yet (pending `billing`/`video`).
- **Security middleware** (`interfaces/http/middleware.py`) — `SecurityContextMiddleware`
  verifies an inbound bearer JWT and attaches the resulting `Principal` to
  `request.state.principal` (no enforcement); `SecurityHeadersMiddleware` adds standard
  defensive response headers.
- **Authentication dependencies** (`interfaces/http/deps.py`) — `get_principal` /
  `get_current_user` enforce that a `Principal` was resolved (401 if not); `require_permission`
  is a dependency factory that raises `NotImplementedError` pending a bound `PermissionEvaluator`
  and approved RBAC matrix — same "fail loudly, don't fake it" policy as `get_scope`.
- **DI wiring** (`core/di/bootstrap.py`) — `PasswordHasher` always bound; `TokenService` bound
  only when `AuthSettings.jwt_secret_key` is configured (left unbound otherwise, rather than
  signing with an empty key).

Deliberately **not** implemented: login/registration/refresh endpoints, the concrete RBAC
permission matrix, refresh-token persistence, session management, external identity providers,
and OAuth — all pending `modules/iam`'s application/domain layers in a later phase.

## Database Foundation (Phase 4.4)

Framework-only, no business entities/tables/repositories. Adds three dependencies:
SQLAlchemy (async engine/ORM), Alembic (migrations), and an async PostgreSQL driver. Originally
`asyncmy` (MySQL 8.x); replaced by `asyncpg`/PostgreSQL per
`docs/architecture/adr/0002-postgresql-migration.md` — see **Database Status** below for the
current, active configuration. Implemented:

- **Async engine + session factory** (`core/db/engine.py`) — `build_engine`/
  `build_session_factory`; `pool_pre_ping=True`, `expire_on_commit=False`.
- **Declarative base + naming convention** (`core/db/base.py`) — one shared `Base`/`MetaData`
  for every module's future ORM models, with `ix_`/`ux_`/`fk_`/`pk_` constraint naming
  (`.claude/rules/naming.md`).
- **Audit-column mixins** (`core/db/mixins.py`) — `UlidPrimaryKeyMixin`, `TimestampMixin`,
  `AuditActorMixin` (incl. `row_version` optimistic locking via `__mapper_args__`),
  `SoftDeleteMixin`, and the `AuditedTableMixin` bundle — the standard audit columns
  (Database Design §1) as composable mixins, not any concrete table.
- **ULID generator** (`core/ids/generator.py`) — `UlidGenerator` (stdlib-only, monotonic
  within a millisecond), resolving the Backend LLD §20.2 open item per Database Design §1's
  ULID/`CHAR(26)` decision.
- **SQLAlchemy Unit of Work** (`core/db/unit_of_work.py`) — `SqlAlchemyUnitOfWork`: opens a
  session per instance, buffers `DomainEvent`s, and writes them to the outbox in the same
  transaction as `commit()` — no module-specific repositories yet (added by each module's own
  UoW subclass later).
- **Outbox infrastructure** (`core/events/outbox.py`) — `OutboxRecord` ORM model (Database
  Design §8.8) and `OutboxWriter`, used by the UoW above. Reading/publishing pending rows
  (`OutboxPublisher`) remains a later-phase worker concern.
- **Repository infrastructure** (`core/db/repository.py`) — `SqlAlchemyRepositoryBase`: a
  generic, model-agnostic helper (session-bound CRUD, tenant/region-scope filtering,
  soft-delete-aware reads) that a module's concrete repository composes and adds its own
  aggregate mapping on top of.
- **DI wiring** (`core/di/bootstrap.py`) — `IdGenerator`/`OutboxWriter` always bound; `Engine`/
  `UnitOfWork` bound only when `DbSettings.url` is configured (same "fail loudly, don't fake
  it" policy as `TokenService`); the engine is disposed on app shutdown (`main.py`).
- **Database dependency wiring** (`interfaces/http/deps.py`) — `get_uow`: a request-scoped
  `UnitOfWork` FastAPI dependency, opened/closed per request.
- **Alembic integration** (`migrations/env.py`, `alembic.ini`) — `target_metadata =
  Base.metadata`; the connection URL is read from `raad.core.config.settings` (not
  `alembic.ini`) so there's one source of DB config; async-engine-to-sync-migration bridging
  via `AsyncConnection.run_sync`. Verified end-to-end against a real database server (reached
  the authentication stage through the full engine/driver/Alembic chain) — originally MySQL;
  now PostgreSQL after ADR-0002 (see **Database Status**).

Deliberately **not** implemented: any module ORM model, business table, or migration revision;
any module-specific repository; `application/`/`domain/` code for any module.

## Event Processing & Background Services Foundation (Phase 4.5)

Framework-only, no business events/workers. No new dependencies — the worker *runtime*
(Celery vs arq) and the *broker* (Redis Streams/RabbitMQ vs Kafka) are both still open items
(Backend LLD §20.1, Phase 2 §4.3), so everything here is a stdlib-`asyncio` abstraction, not
a commitment to either. Implemented:

- **Worker framework foundation** (`core/workers/base.py`) — `Worker`: a runtime-agnostic
  poll-loop lifecycle (`start`/`stop`, health tracking, a bad tick never kills the loop).
  Concrete workers only implement `run_once()`.
- **Worker lifecycle** (`core/workers/lifecycle.py`) — `WorkerLifecycle`: starts/stops a set
  of `(Worker, interval)` pairs together.
- **Worker health checks** (`core/workers/health.py`) — `WorkerHealth`, `WorkerHealthRegistry`.
- **Retry strategy** (`core/workers/retry.py`) — `RetryPolicy` interface,
  `ExponentialBackoffRetryPolicy` concrete (pure arithmetic, no I/O).
- **Dead Letter Queue foundation** (`core/workers/dlq.py`) — `DeadLetterQueue` interface only
  (needs a chosen broker).
- **Idempotency foundation** (`core/workers/idempotency.py`) — `IdempotencyStore` interface;
  `InMemoryIdempotencyStore` concrete but explicitly process-local/non-durable (dev/test only;
  replace before running >1 worker process).
- **Scheduler interfaces** (`core/workers/scheduler.py`) — `ScheduledJob`, `Scheduler`
  interface, `IntervalScheduler` concrete (simple polling, no cron parser); `LockPort`
  interface for the overlap guard (needs Redis — not wired).
- **Background logging** (`core/workers/logging.py`) — `bind_worker_context`, reusing the same
  `contextvars` mechanism as HTTP middleware (`core/logging/context.py`, extended with
  `worker_name`/`job_id`).
- **Event processor interfaces** (`core/events/processor.py`) — `EventProcessor`,
  `EventProcessorRegistry` (empty; modules register their own processors later).
- **Broker consumer interface** (`core/events/ports.py`) — `BrokerConsumer` (producer side,
  `BrokerPort`, already existed).
- **Outbox relay foundation** (`core/events/outbox.py`) — `SqlOutboxPublisher`: concrete
  `OutboxPublisher` querying unpublished rows and publishing via `BrokerPort` — broker-agnostic,
  verified with a fake broker/session; only bound in DI once a `BrokerPort` exists (never in
  this phase).
- **Worker configuration** (`core/config/settings.py`) — `WorkerSettings` (relay/scheduler
  intervals, retry tuning).
- **DI wiring** (`core/di/bootstrap.py`) — `RetryPolicy`/`IdempotencyStore`/
  `EventProcessorRegistry` always bound; `OutboxPublisher` bound only if a `BrokerPort` is
  ever bound (never in this phase).
- **Worker bootstrap** (`interfaces/workers/bootstrap.py`) — `python -m
  raad.interfaces.workers.bootstrap`: shares the HTTP app's `core.di` composition root,
  registers the two foundation workers (Outbox Relay, Scheduler — zero business jobs), and
  manages graceful shutdown on SIGINT/SIGTERM.
- **Foundation workers** (`interfaces/workers/outbox_relay.py`,
  `interfaces/workers/scheduler.py`) — `OutboxRelayWorker` (no-ops until an `OutboxPublisher`
  is bound), `SchedulerWorker` (ticks an empty `IntervalScheduler`).

Deliberately **not** implemented: any concrete broker/worker-runtime adapter, business
event processors, the notification/report workers (`notification_worker.py`/`report_worker.py`
remain empty), any scheduled business job (trip generation, subscription sweeps, retention,
reconciliation), and a durable idempotency/DLQ/lock store.

## IAM Domain Foundation (Phase 5.1)

The first module with real domain content — `modules/iam/domain/` — framework-free (no
SQLAlchemy/Pydantic/FastAPI, no I/O; verified by grep and by direct import in isolation).

- **Aggregate roots** (`entities.py`) — `User` (Database Design §4.3: single identity table
  for every principal — RAAD staff, org admins, drivers, parents — discriminated by `role`;
  enforces "at least one of email/phone" and the org-scoped-role-vs-staff-role invariant) and
  `RefreshToken` (§4.5). Behavior methods follow the LLD §5.2 shape
  (`activate(clock, actor_id) -> [UserActivated]`): a `core.time.Clock` is passed in rather
  than the aggregate calling `datetime.now()` itself, so behavior is deterministic/testable.
  Events are buffered (`pull_domain_events()`) for a future Unit of Work to commit — not
  implemented in this phase.
- **Value objects** (`value_objects.py`) — `UserId`/`RefreshTokenId`/`OrganizationId`
  (strongly-typed, non-empty ids; `OrganizationId` is a cross-module *reference* only, per
  "cross-context references are by ID only"), `Email`/`PhoneNumber` (self-validating, E.164
  for phone), `UserStatus`.
- **Domain events** (`events.py`) — factory functions returning the existing `DomainEvent`
  envelope (`core.events.base`, not a parallel type): `UserInvited`, `UserActivated`,
  `UserDisabled`, `UserLoggedIn`, `UserPasswordChanged`, `UserMfaEnabled`/`UserMfaDisabled`,
  `RefreshTokenIssued`, `RefreshTokenRevoked`.
- **Repository interfaces** (`repositories.py`) — `UserRepository`, `RefreshTokenRepository`.
  Declared fresh (plain `abc.ABC`) rather than extending `core.db.repository`'s interfaces,
  since that module co-locates a SQLAlchemy-dependent class in the same file — importing from
  it would make this domain layer require SQLAlchemy to load at all.
- **Domain services / policies** — none defined; both files carry a docstring explaining why
  (email/phone uniqueness needs a repository query, i.e. it's an application-layer concern;
  the RBAC matrix and `SubscriptionAccessPolicy`/`VideoAccessPolicy` live elsewhere).

Password/token *hashing* is deliberately not this layer's concern — `User`/`RefreshToken`
only store an opaque hash string produced by `core.security` (Phase 4.3); the domain never
sees a plaintext password/token or a hashing algorithm.

## IAM Application Layer (Phase 5.2)

`modules/iam/application/` — orchestration only, no FastAPI/SQLAlchemy in its own code, no
business rules (those stay in the domain). `infra/` and `api/` for `iam` remain unimplemented,
so nothing here is reachable yet — it's exercised directly with fake in-memory repositories.

- **Commands** (`commands.py`) — `InviteUserCommand`, `ActivateUserCommand`,
  `DisableUserCommand`, `ChangePasswordCommand`, `EnableMfaCommand`/`DisableMfaCommand`,
  `LoginCommand`, `RefreshAccessTokenCommand`, `LogoutCommand`. Admin/self-service commands
  carry the calling `Principal` as `actor`, matching the LLD §4.2 contract-skeleton shape
  exactly; login/refresh/logout are credential/token-based instead.
- **Queries & DTOs** (`queries.py`) — `GetUserByIdQuery`; `UserDTO`, `AuthResultDTO` (the
  domain/API boundary — neither layer depends on the other's internal shape).
- **Validators** (`validators.py`) — `ensure_email_available`/`ensure_phone_available`:
  I/O-requiring pre-condition checks (global uniqueness), which is exactly why they're an
  application concern and not a domain one (see `domain/services.py`'s docstring).
- **Ports** (`ports.py`) — `IamUnitOfWork`, extending the existing
  `core.db.unit_of_work.UnitOfWork` with `users`/`refresh_tokens` repository properties, per
  that module's own documented extension pattern.
- **Application services** (`services.py`) — `UserApplicationService` (invite/activate/
  disable/change-password/enable-mfa/disable-mfa/get-by-id) and `AuthApplicationService`
  (login/refresh-with-rotation/logout). Every handler follows the same shape: open
  `IamUnitOfWork`, validate pre-conditions, load/invoke the aggregate, record its
  `pull_domain_events()`, commit, return a DTO.
- **Package exports** (`__init__.py`) — the module's public application-layer surface.

Constructor-injected dependencies (`Clock`, `IdGenerator`, `TokenService`, `PasswordHasher`,
`PasswordPolicy`) are all existing `core` ports, reused as-is. Refresh tokens are stored hashed
(SHA-256, a fast lookup hash — not `PasswordHasher`'s slow KDF, since a signed JWT is already
high-entropy) and rotated on every successful refresh (old token revoked, new one issued).

## IAM Infrastructure Layer (Phase 5.3)

`modules/iam/infra/` — the first business tables in the schema (`users`, `refresh_tokens`).
`api/` for `iam` still doesn't exist, so nothing here is reachable over HTTP yet; it's wired
into `core/di` and exercised directly.

- **ORM models** (`models.py`) — `UserModel`/`RefreshTokenModel`, matching Database Design
  §4.3/§4.5 column-for-column: both CHECK constraints ("email or phone present",
  "org-scoped role requires organization_id"), the exact indexes
  (`ix_users__organization_id`/`__role`/`__status`, `ix_refresh_tokens__user_id`/
  `__expires_at`), unique constraints, and the `users.role`/`.status` `ENUM`s — originally
  verified by rendering `CREATE TABLE` DDL against the MySQL dialect; re-verified against
  PostgreSQL after ADR-0002 (native `ENUM` types, no MySQL-dialect-specific column types — see
  **Database Status**).
- **Mappers** (`mappers.py`) — `user_to_model`/`model_to_user`,
  `refresh_token_to_model`/`model_to_refresh_token`. The single translation point for a
  pre-existing casing mismatch: `core.tenancy.principal.Role` (Phase 4.3, already shipped)
  uses upper-case values, the approved `role` column uses lower-case — rather than changing
  either the shipped enum or the approved schema, the mapper translates.
  Round-tripped and verified.
- **Repositories** (`repositories.py`) — `SqlAlchemyUserRepository`,
  `SqlAlchemyRefreshTokenRepository`, composing `core.db.repository.SqlAlchemyRepositoryBase`.
  Return domain aggregates only, never ORM rows. Each keeps a small identity map of every
  aggregate it has returned or added and exposes `flush_tracked_changes()` — the bridge that
  makes in-place aggregate mutations (`user.activate()`, done directly by the unchanged Phase
  5.2 application code, which never re-calls `add()` for an update) actually reach the
  SQLAlchemy session before commit.
- **`SqlAlchemyIamUnitOfWork`** — extends the existing `SqlAlchemyUnitOfWork` (constructs the
  two repositories in `__aenter__`, calls `flush_tracked_changes()` on both before delegating
  to `super().commit()`, which still owns the actual outbox-write + session-commit behavior,
  unchanged).
- **Persistence wiring** (`core/di/bootstrap.py`) — binds `IamUnitOfWork ->
  SqlAlchemyIamUnitOfWork` alongside the existing generic `UnitOfWork` binding, only when
  `db.url` is configured. `migrations/env.py` now imports `iam.infra.models` so
  `UserModel`/`RefreshTokenModel` register onto `Base.metadata` for autogenerate.
- **Package exports** (`infra/__init__.py`).

Domain (`modules/iam/domain/`) and application (`modules/iam/application/`) are byte-for-byte
unchanged (verified via `git diff`) — this phase only added the layer that implements their
interfaces. No direct SQLAlchemy import outside `infra/` (verified by grep).

## IAM HTTP API (Phase 5.4)

`modules/iam/api/` — the first real business endpoints. Thin controllers only (Backend LLD
§16.2): parse request DTO → call one application-service method → return response DTO. No
business logic, no repository/SQLAlchemy access, no aggregate manipulation.

- **Auth** (`/api/v1/auth`): `POST /login`, `POST /refresh`, `POST /logout`, `GET /me` — all
  implemented and verified end-to-end (login, wrong-password rejection, refresh rotation,
  logout, `/me`) against a fake in-process `IamUnitOfWork`.
- **Users** (`/api/v1/users`): `POST /` (invite), `GET /{id}`, `PATCH /{id}`. Authorization
  uses the existing `require_permission`/`PermissionEvaluator` abstraction (Phase 4.3) — since
  no RBAC permission matrix is approved yet, these three routes currently return `500`
  (`NotImplementedError`) once authenticated, the same honest-incompleteness pattern every
  prior phase has used for RBAC-pending code paths.
- **Deliberately not implemented, confirmed with the user rather than silently resolved:**
  - `GET /users` (list) — no listing use-case exists in `UserApplicationService`, and
    `UserRepository`/`RefreshTokenRepository` (Phase 5.1) have no `list()` method; adding one
    means touching Domain and Application, both frozen this phase.
  - `DELETE /users/{id}` — Database Design §9 keeps "soft delete" (`deleted_at`) and
    "business status" (`user.disable()`) explicitly separate; the `User` aggregate has no
    soft-delete behavior, so a correct implementation needs a Domain addition out of scope.
- **`PATCH /users/{id}`** is limited to the transitions `UserApplicationService` actually
  exposes — `status` (`active`/`disabled`) and `mfa_enabled` — not a generic field-level
  update (`full_name`/`email`/`phone`), since no such Application-layer use-case exists yet.
- **Dependency wiring** (`api/deps.py`) — `get_iam_uow` resolves (but deliberately does
  **not** enter) a fresh `IamUnitOfWork` per call, since every application-service method
  already manages its own `async with uow:` (Phase 5.2); wrapping it again would double-enter
  the same instance and break session lifecycle. `core/di/bootstrap.py` now also binds
  `PasswordPolicy`, `UserApplicationService` (always), and `AuthApplicationService` (only
  alongside `TokenService`).
- Verified: OpenAPI generation (`/openapi.json` lists all 7 routes), Swagger UI (`/docs`
  returns 200), and the standard `ErrorEnvelope` on every error path (401/500 confirmed).

## Status

The phase log above (4.2–5.4) is a historical build-out record of IAM's own early phases and is
kept as-is for that reason — it does **not** describe current backend-wide status. **The
authoritative, currently-maintained status is `CLAUDE.md`'s "Repository Status" section** at the
repo root; this section is a short pointer to it, not a duplicate, to avoid the exact staleness
this section itself accumulated pre-Backend-Stabilization (it previously read "five of ten
bounded contexts implemented," "tests/architecture/ is currently empty" — both long false).

As of the Backend Stabilization phase (ADR-0004 through ADR-0008): **all ten** bounded contexts
are implemented end-to-end (domain → application → infrastructure → API → database migration);
RBAC (`role_permissions`) and `ScopeResolver` (`region_assignments`/`support_assignments`) both
resolve for real on every route; the Redis Streams event broker, Notification Worker, Report
Worker, and scheduled jobs are wired (ADR-0008); a real GitHub Actions CI gate exists
(`.github/workflows/backend-pipeline.yml`); `tests/architecture/` has ten automated boundary-gate
tests, and `tests/contract/` validates the built OpenAPI surface against the documented API
Contracts. See `CLAUDE.md`'s "Known gaps" for what genuinely remains.

**Technology stack (current):**

- **FastAPI** — async modular monolith, one router per bounded context.
- **PostgreSQL** — the active relational store (`docs/architecture/adr/0002-postgresql-migration.md`,
  superseding an earlier MySQL 8.x decision — see **Database Status** below).
- **SQLAlchemy 2.x (async)** — declarative ORM, one shared `Base`/`MetaData` per
  `core/db/base.py`'s naming convention.
- **Alembic** — schema migrations, one linear revision chain (see **Database Status**).
- **Clean Architecture** — `api → application → domain`; `infra` implements the interfaces
  `domain` defines; domain never imports FastAPI or SQLAlchemy (`.claude/rules/backend.md` #2),
  verified by direct grep across all five completed modules, not just asserted.
- **Domain-Driven Design** — aggregates with buffered domain events, value objects,
  domain-owned invariants; identical `_AggregateRoot` shape independently duplicated per module
  (deliberately — no shared-kernel package is approved).
- **Transactional Outbox** — every state change's domain events are written to the `outbox`
  table in the *same* transaction as the business rows (`core/events/outbox.py`,
  `SqlAlchemyUnitOfWork.commit()`) — no event without a committed change, no committed change
  silently missing its event. The publish/relay side exists but stays unbound until a broker
  is chosen (Phase 2 §4.3, still open — backend-wide, not module-specific).
- **Dependency Injection** — one composition root, `core/di/bootstrap.py`, binding every
  service, repository-bearing UnitOfWork, and cross-cutting port; unbound dependencies fail
  loudly (`LookupError`/`NotImplementedError`) rather than resolving to a fake.

## Database Status

- **PostgreSQL is the active database** — `RAAD_DB__URL` uses the `postgresql+asyncpg://` form
  (`.env.example`); the `asyncmy`/MySQL configuration referenced earlier in this file's phase
  log is historical only (`docs/architecture/adr/0002-postgresql-migration.md`).
- **Alembic migration chain** is a single linear sequence spanning all ten bounded contexts plus
  two shared-kernel revisions (`role_permissions`, `audit_entries`) — see `CLAUDE.md`'s
  "Migration status" for the exact current build order. No branches.
- **Zero migration drift verified** — `alembic check` reports "No new upgrade operations
  detected" against the live schema; the full chain has been round-tripped
  (`upgrade head → downgrade → upgrade head`) with no orphaned database objects. Every
  migration introducing a PostgreSQL native `ENUM` type includes an explicit `DROP TYPE` in its
  `downgrade()` — `alembic revision --autogenerate` does not emit this itself, and omitting it
  breaks re-upgrade after a downgrade.
- `migrations/env.py` imports `infra/models` from all ten modules plus `core.audit.writer`
  (ADR-0007), kept in sync 1:1 with which modules/shared-kernel packages have a non-empty
  model-bearing source file.
- Cross-context reference columns (e.g. `organization_id`) are indexed but never
  foreign-key-constrained, by design (`.claude/rules/database.md` #3) — preserves module
  extraction seams. In-context references (e.g. `refresh_tokens.user_id → users.id`) are real,
  database-enforced foreign keys.

## Roadmap

See `CLAUDE.md`'s "Known gaps" section for the currently-maintained, single source of truth on
what remains — this avoids the exact duplication-then-staleness this section itself suffered
from previously (it once listed nine of ten bounded contexts as "Planned" after they had already
shipped). In short: the event broker's *publish* side is wired (ADR-0008) but the
`PaymentProviderPort`/`VideoProviderPort` vendor adapters and the payment-callback signature
scheme remain deliberately unbound ("fail loudly, don't fake it"); no `list_all()` repository
method is yet filtered by the real `ScopeResolver`; and `ReportDefinition`
(Reporting)/`student.assignment_changed` (Notifications) are real, unresolved documentation
conflicts awaiting an approved doc update, not a code fix.
