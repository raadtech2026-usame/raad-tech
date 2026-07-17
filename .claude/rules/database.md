# Rule: Database

Derived from `docs/business/RAAD_Phase3.2_Database_Design_v1.md` and
`docs/architecture/adr/0002-postgresql-migration.md` (superseding the original MySQL 8.x decision).

1. **Engine:** PostgreSQL, via the `asyncpg` async driver. **Migrations:** Alembic, revisions in
   `backend/migrations/versions/`. MySQL-specific implementation patterns (e.g. the generated-column
   partial-unique-constraint emulation) are not carried over where PostgreSQL provides a native,
   better-suited feature for the same requirement (ADR-0002) — PostgreSQL native `ENUM` types are
   the one deliberate exception, kept because they are already the better pattern, not a MySQL
   workaround.
2. **Multi-tenancy:** shared schema, `organization_id` on every tenant-owned table.
3. **Cross-context references are by ID only** — not hard-FK-constrained across module boundaries,
   to preserve module seams. In-context FKs are enforced by the database.
4. **Standard audit columns** on every business table: `id, created_at, updated_at, created_by,
   updated_by, deleted_at, row_version`.
5. **Soft delete via `deleted_at`**, filtered by default at the repository layer — except: audit,
   outbox, and financial rows are never hard-deleted; `vehicle_positions` is hard-pruned via
   partition drops, not per-row soft delete.
6. **`vehicle_positions` is partitioned by time** (RANGE, monthly, by `event_time`), indexed by
   `(vehicle_id, event_time)` and `(trip_id, event_time)`. Raw high-frequency positions have a
   bounded retention window (recommend 90 days, configurable); trip summaries and geofence events
   are retained long-term.
7. **`audit_entries` is append-only and immutable** — no `updated_at`/`deleted_at`.
8. See `.claude/rules/naming.md` for the full naming convention table.
