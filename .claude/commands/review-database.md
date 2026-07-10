# Command: Review Database

## Purpose
Invoke the "Database Review" skill against a pending or existing migration.

## Usage
`/review-database <migration-revision-or-table-name>`

## Behavior
1. Loads `.claude/skills/database-review.md`.
2. Validates naming, audit columns, tenancy discriminator, cross-context FK policy, and
   partitioning/retention needs against `.claude/rules/database.md` and `.claude/rules/naming.md`.
3. Reports findings; flags anything that would require a follow-up migration to fix cleanly.

## Preconditions
- Target migration exists under `backend/migrations/versions/`, or the table is already defined.
