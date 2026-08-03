# Scripts

Developer and operational helper scripts. No business logic — thin wrappers around tooling.

## Structure

- `db/migrate.sh` — run Alembic migrations against the target environment. *(placeholder)*
- `db/seed.sh` — seed reference/lookup data for local development. *(placeholder)*
- `db/backup.sh` — dump the database to a timestamped, compressed, `pg_restore`-compatible file;
  prune old local dumps; optionally push off-site via `rclone`. Real, tested — see
  `docs/runbooks/backup-and-restore.md`.
- `db/restore.sh` — restore a dump produced by `backup.sh` into a target database. Real, tested
  — same runbook.
- `db/backup-loop.sh` — the periodic-schedule wrapper `docker-compose.yml`'s `backup` service
  runs; calls `backup.sh` on an interval. Not meant to be run standalone outside that service.
- `dev/bootstrap.sh` — one-shot local environment bootstrap (dependencies, env files, containers).
  *(placeholder)*
- `ci/` — helper scripts invoked from CI/CD pipelines. *(placeholder)*

## Status

Mostly structural scaffold — `migrate.sh`/`seed.sh`/`bootstrap.sh`/`ci/` remain empty
placeholders. `db/backup.sh`/`db/restore.sh`/`db/backup-loop.sh` are the first real scripts here
(Priority 1 Item 1, `PROJECT_STATUS.md`) — round-trip tested in
`testing/backups/test_backup_restore.sh` and CI.
