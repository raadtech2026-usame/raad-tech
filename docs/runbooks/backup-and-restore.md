# Runbook: Database backup and restore

## When you need this

Three situations:

1. **Routine operation** — nothing to do. The `backup` Docker Compose service runs automatically
   alongside the rest of the stack (`docker/docker-compose.yml`) and dumps the database on a
   schedule (`BACKUP_INTERVAL_HOURS`, default every 24h). This runbook is for the other two
   situations.
2. **You need to restore data** — a bad migration, an operator mistake, or (see Disaster Recovery
   below) a lost VPS.
3. **You want to prove backups actually work** before you need one — the whole point of a
   restore drill is finding out a backup is unusable *before* it's the only copy of the data
   that exists.

## Prerequisites

- `pg_dump`/`pg_restore`/`psql` reachable — either exec into the running `backup` container
  (`docker compose exec backup sh`, which already has them) or run
  `scripts/db/{backup,restore}.sh` directly from a host with the PostgreSQL client tools
  installed.
- A connection URL or the standard `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`
  environment variables pointing at the server you mean to touch. **`restore.sh` never guesses a
  target** — you must always pass `--target-url` explicitly, precisely so a mistyped invocation
  cannot silently overwrite the wrong database.

## Running a manual backup

Inside the running container (no need to wait for the schedule):

```bash
docker compose -f docker/docker-compose.yml exec backup /app/backup.sh
```

Or directly, against any reachable server:

```bash
sh scripts/db/backup.sh "postgresql://user:password@host:5432/dbname"
```

Output is a single `.dump` file named `raad_<database>_<UTC timestamp>.dump` in `BACKUP_DIR`
(`/backups` inside the container — the `raad_backups_data` volume — or wherever you point
`BACKUP_DIR` when running standalone).

## What it does

1. Runs `pg_dump --format=custom` — PostgreSQL's own binary, compressed, `pg_restore`-compatible
   format (chosen over a plain SQL dump specifically so restores below can use `--clean
   --if-exists`, which plain-SQL dumps don't support as cleanly).
2. Verifies the resulting file is non-empty — an empty "successful" dump is worse than an
   obvious failure, so this exits non-zero and deletes the empty file rather than leaving a
   silently-broken backup on disk.
3. Prunes local dumps older than `BACKUP_RETENTION_DAYS` (default 14).
4. If `BACKUP_RCLONE_REMOTE` is configured, pushes the fresh dump there via `rclone copy`. If
   not, logs a loud, repeated warning — **never a silent skip** — because a local-only backup on
   the same disk as the database it's backing up does not protect against the failure mode that
   actually matters (losing the whole VPS).

Every log line shows the connection target with its password redacted (`user:***@host/db`) —
never the real credential, even in this script's own stdout.

## Running a restore drill (do this before you need it)

**Never restore into a database you care about without testing on a throwaway one first.**

```bash
# 1. Create a scratch database on the same (or a test) server.
createdb -h <host> -U <user> raad_restore_drill

# 2. Restore into it.
sh scripts/db/restore.sh \
  --target-url "postgresql://user:password@host:5432/raad_restore_drill" \
  --confirm \
  /backups/raad_<database>_<timestamp>.dump

# 3. Spot-check the data, then drop the scratch database.
psql "postgresql://user:password@host:5432/raad_restore_drill" -c "\dt"
dropdb -h <host> -U <user> raad_restore_drill
```

`restore.sh` refuses to run at all without `--confirm` — it prints exactly what it's about to
overwrite and exits `1`. This is deliberate friction: `pg_restore --clean --if-exists` drops
every existing object in the target database before recreating it from the dump. There is no
"undo."

## Disaster recovery — restoring onto a brand-new host

1. Provision the new host, install/start PostgreSQL (or bring up this platform's own `postgres`
   Compose service — same image, same version).
2. `createdb` the target database (`restore.sh` restores objects *into* an existing database; it
   does not create one).
3. Get the most recent dump onto the new host — from the off-site remote if one was configured
   (`rclone copy <remote>:path/to/dump.dump .`), or from wherever the old host's disk/volume was
   backed up if not.
4. Run `restore.sh --target-url <new-host-url> --confirm <dump-file>`.
5. Run `alembic upgrade head` from `backend/` if the dump predates a migration that has since
   landed (a dump captures schema *and* data as of the moment it was taken — if the code has
   moved on since, migrations still need to catch the schema up).
6. Point the application's `RAAD_DB__URL` at the new host and restart.

## Configuring off-site storage

No off-site destination is provisioned in this repository by default (Priority 1 Item 1 shipped
the mechanism, not a specific vendor choice — see `PROJECT_STATUS.md`). To turn it on:

1. Pick any [rclone-supported backend](https://rclone.org/overview/) — S3, Backblaze B2,
   DigitalOcean Spaces, Cloudflare R2, SFTP to a second server, etc.
2. Configure that remote (`rclone config`, run once, produces an `rclone.conf`) and make it
   available to the `backup` container — either bind-mount a real `rclone.conf` into
   `/root/.config/rclone/rclone.conf`, or set the equivalent `RCLONE_CONFIG_<REMOTE>_*`
   environment variables (rclone reads either).
3. Set `BACKUP_RCLONE_REMOTE=<remote-name>:<bucket-or-path>` in `docker/.env`.
4. Restart the `backup` service and confirm the "pushing to off-site remote" log line appears
   (not the unconfigured warning) on the next run.

## Verifying it worked

```bash
# The dump exists and is non-empty:
docker compose -f docker/docker-compose.yml exec backup ls -la /backups

# It's structurally valid and lists the expected tables:
docker compose -f docker/docker-compose.yml exec backup pg_restore --list /backups/<file>.dump
```

The automated round-trip test (`testing/backups/test_backup_restore.sh`, also run in CI on every
change to `backend/**`) does exactly this plus a full restore and data-integrity check — see it
for the canonical, scripted version of the "Running a restore drill" steps above.

## Troubleshooting

**"pg_dump produced no data" / the script exits with `[backup] FATAL: ... is empty`.** The
connection succeeded but the dump is empty — check the target database name is actually the one
you meant (`PGDATABASE`/the URL's path segment), not an empty/wrong database.

**Restore fails with a role/owner error.** `restore.sh` already passes `pg_restore --no-owner`,
which skips restoring the original role/ownership commands the dump recorded — this is what
lets a dump taken against one environment's roles restore cleanly into another's. If you still
see a role error, check the connecting user in `--target-url` itself has privileges to create
objects in the target database.

**The off-site warning keeps appearing even after setting `BACKUP_RCLONE_REMOTE`.** Confirm the
`backup` container actually restarted after the `.env` change (`docker compose up -d backup`) —
Compose does not hot-reload environment variables into a running container.
