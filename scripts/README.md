# Scripts

Developer and operational helper scripts. No business logic — thin wrappers around tooling.

## Structure

- `db/migrate.sh` — run Alembic migrations against the target environment.
- `db/seed.sh` — seed reference/lookup data for local development.
- `dev/bootstrap.sh` — one-shot local environment bootstrap (dependencies, env files, containers).
- `ci/` — helper scripts invoked from CI/CD pipelines.

## Status

Structural scaffold only. All scripts are empty placeholders.
