# Rule: Naming

Derived from `docs/business/RAAD_Phase3.2_Database_Design_v1.md` §1 (database) and existing
Phase 3.1/3.3 conventions (backend/API).

## Database

| Element | Convention | Example |
|---|---|---|
| Table names | `snake_case`, plural | `student_assignments` |
| Column names | `snake_case`, singular | `assigned_at` |
| Primary key | `id` (ULID/UUIDv7) | `id` |
| Foreign key | `<referenced_singular>_id` | `vehicle_id`, `route_id` |
| Tenant key | `organization_id` on every tenant-owned table | |
| Booleans | `is_`/`has_` prefix | `is_active` |
| Timestamps | `_at` suffix, UTC | `created_at`, `deleted_at` |
| JSON columns | `_json` suffix | `metadata_json` |
| Indexes | `ix_<table>__<cols>` (secondary), `ux_<table>__<cols>` (unique), `fk_<table>__<ref>` | `ix_trips__org_status` |

## Backend module code

- Modules: `snake_case`, matching bounded-context names exactly (`fleet_device`, not `fleet-device`
  or `FleetDevice`).
- Domain events: `PascalCase`, past-tense (`TripStarted`, `DeviceOfflineDetected`).
- REST routes: `kebab-case` resource paths under `/api/v1` (`/student-assignments`).

## Frontend

- Feature folders: `kebab-case`, matching backend context names where practical
  (`fleet-devices`, `transport-ops`).
- Components: `PascalCase`.

## Cross-cutting

- Environment variables: `SCREAMING_SNAKE_CASE`.
- No abbreviations that aren't already used in the approved documentation — use the Ch. 6 ubiquitous
  language verbatim (Organization, Vehicle, Device, Driver, Student, Parent, Route, Stop, Trip,
  Subscription).
