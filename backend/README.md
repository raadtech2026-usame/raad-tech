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

## Migrations

Alembic. `alembic.ini` at the repo root of this deployable; revisions live in `migrations/versions/`.

## Tests

`tests/unit`, `tests/integration`, `tests/contract`, `tests/architecture` (the last enforces module
dependency-direction and import-boundary rules — see `.claude/rules/testing.md`).

## Status

Structural scaffold only. No routes, models, or business logic are implemented yet.
