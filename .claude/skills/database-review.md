# Skill: Database Review

## Purpose
Validate that a new migration or schema change follows RAAD's database conventions and multi-tenancy
model before it is applied.

## Workflow
1. Confirm naming: table/column conventions, PK/FK conventions, `organization_id` presence on
   tenant-owned tables — per `.claude/rules/naming.md` and `.claude/rules/database.md`.
2. Confirm standard audit columns are present on business tables (`created_at, updated_at,
   created_by, updated_by, deleted_at, row_version`), with the documented exceptions (append-only
   audit/outbox/financial tables, `vehicle_positions`).
3. Confirm cross-context references are ID-only, not hard-FK'd across module boundaries.
4. Confirm partitioning/retention is addressed for any high-write-volume table (positions,
   notifications, audit at scale).
5. Confirm the migration is reversible where feasible, and gated through CI/CD (never applied
   manually to production).
6. Confirm the change doesn't silently widen a module's data access beyond its own tables.

## When to use
Before any Alembic migration is merged.
