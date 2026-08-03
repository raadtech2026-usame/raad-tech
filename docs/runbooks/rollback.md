# Runbook: Rolling back a bad deployment

Priority 1 Item 7 (`PROJECT_STATUS.md`). What to do when a deployment (a `git pull` + `docker
compose up -d --build`) goes bad — a new bug in production, a migration that broke something, a
container that won't come up healthy. Distinct from `docs/runbooks/backup-and-restore.md`'s
disaster-recovery drill, which is for *data* loss (a lost VPS, a corrupted database) — this
runbook is for a *bad code/schema change* where the data itself is still fine.

## First: is this actually a rollback situation?

Check `docker compose ps` and `/health/ready` (Priority 1 Item 5) before assuming the deploy
itself is the problem — a single unhealthy container after a routine restart is often a transient
startup-ordering issue (`depends_on: condition: service_healthy` already sequences
`postgres`/`redis`/`migrate` before `backend`/`worker`, but a slow cold start can still trip a
healthcheck's first few retries). Give it the healthcheck's own `retries × interval` window
before concluding a rollback is actually needed.

## The two things that can go wrong independently

1. **Application code** (a new bug, a broken route, a bad frontend build) — reversible by
   checking out a previous commit and rebuilding. No data is touched.
2. **A database migration** (a new Alembic revision that's part of the bad deploy) — reversible
   with `alembic downgrade`, but **only safely so if the migration is genuinely reversible and no
   application code already committed after it depends on the new schema being present**. This
   is the harder case; read the "Migration rollback" section below carefully before running it.

A bad deploy might involve either, both, or neither (sometimes "rollback" just means restarting a
container that's stuck, no code/schema change at all).

## Application-code rollback (no migration involved)

```bash
cd raad
git log --oneline -10           # find the last known-good commit
git checkout <known-good-commit-or-tag>
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d --build
docker compose -f docker/docker-compose.yml ps
curl -s http://localhost/health/ready | python3 -m json.tool
```

`--build` matters — without it, Compose reuses the already-built (bad) image even though the
checked-out source changed. `git checkout <commit>` leaves the repo in a detached-HEAD state,
which is fine for this one-off rebuild; once confirmed stable, either `git checkout main` and
`git revert` the bad commit(s) properly (preserving history, per `.claude/rules/git.md` #1: new
commits, not destructive rewrites) or fix forward from the known-good commit — don't leave the
VPS permanently on a detached HEAD.

## Migration rollback (a bad deploy that included a new Alembic revision)

**Check first what actually changed:**

```bash
docker compose -f docker/docker-compose.yml exec backend alembic current
docker compose -f docker/docker-compose.yml exec backend alembic history | head -5
```

**If the migration is purely additive** (a new nullable column, a new table, a new index —
exactly the shape every migration in this chain's own precedent already follows, per
`docs/business/RAAD_Phase3.2_Database_Design_v1.md` and this repository's own migration history)
and the application code rollback above already removed the code that *reads* the new
column/table, downgrading is safe:

```bash
docker compose -f docker/docker-compose.yml exec backend alembic downgrade -1
```

**If the migration dropped or altered a column already in use** — every migration this Priority 1
program itself added (`d4fbe03f2b94`/`a1c9e4f2b871`/`f3d8b1a4e6c2`) was purely additive, but this
codebase's own history has real precedent for destructive migrations too (ADR-0016's billing
cutover, `f4a1c9e7b302`, dropped `organizations.billing_model` and
`subscriptions.subscriber_type`/`subscriber_id` outright) — a downgrade of one of *those* can
lose data that was written to the now-removed structure in the meantime. **Stop and assess before
running `alembic downgrade`** in this case — restoring from the most recent backup
(`docs/runbooks/backup-and-restore.md`) into a scratch database first, to confirm exactly what
the downgrade would discard, is safer than guessing. Check the migration file's own
`downgrade()` function directly — a destructive `upgrade()` (a `DROP COLUMN`) usually means an
*irreversible* `downgrade()` too (the dropped data is simply gone, `ALTER TABLE ... ADD COLUMN`
can restore the column but never its old values) — that migration's own docstring/downgrade
implementation is the authoritative answer, not an assumption from this runbook.

**After any migration downgrade**, redeploy the matching (older) application code — a downgraded
schema paired with code that still expects the newer schema is its own new bad state:

```bash
git checkout <commit-before-the-bad-migration>
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d --build
```

## Frontend-only rollback

The frontend is a static build (`frontend.Dockerfile`'s prod target) served by its own container.
A frontend-only bad deploy (backend/schema unaffected) needs only:

```bash
git checkout <known-good-commit>
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d --build frontend
```

## Last resort: full restore from backup

If the above isn't enough to recover (e.g. the bad deploy corrupted data through legitimate
application writes, not just a schema mismatch), the actual data-recovery path is
`docs/runbooks/backup-and-restore.md`'s restore procedure — restoring the most recent pre-incident
`pg_dump` into the live database. This is a genuinely destructive operation (overwrites current
data) — `restore.sh` requires explicit `--target-url` and `--confirm` specifically so this step is
never accidental.

## Post-rollback checklist

- [ ] `docker compose ps` — every service `healthy`.
- [ ] `curl -s http://localhost/health/ready` — `"status": "ready"`, all configured dependencies
      `"ok"`.
- [ ] `alembic current` matches what the currently-deployed application code actually expects
      (no schema/code version mismatch left behind).
- [ ] A quick manual smoke test of the affected feature — Priority 1's own repeated theme this
      whole program is that live behavior has caught real bugs no unit test did; the same applies
      to confirming a rollback actually fixed the problem, not just that containers report
      healthy.
- [ ] Root-cause the original bad deploy before re-attempting it — `.claude/rules/workflow.md`'s
      own discipline (tests, live verification, review) exists specifically to catch these before
      they reach production; note what slipped through for next time.
