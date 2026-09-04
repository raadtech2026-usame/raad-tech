#!/bin/sh
# scripts/db/backup.sh — dumps the RAAD PostgreSQL database to a timestamped, compressed,
# pg_restore-compatible file; prunes local dumps older than BACKUP_RETENTION_DAYS; optionally
# pushes the fresh dump off-site via rclone if BACKUP_RCLONE_REMOTE is configured. See
# docs/runbooks/backup-and-restore.md for the full operational guide.
#
# Connection resolution order: a connection URL passed as $1, then $BACKUP_DATABASE_URL, then
# the standard libpq PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE env vars (what docker-compose.yml's
# `backup` service sets, mapped from the same POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB values
# `postgres` itself uses) — never RAAD_DB__URL, which carries a `+asyncpg` driver suffix pg_dump
# does not understand.
#
# Deliberately POSIX `sh`, not bash — Alpine (this script's actual runtime, docker/
# backup.Dockerfile) ships busybox ash, not bash, and adding bash would be an unnecessary
# dependency for what this script needs. Runnable directly on any host with pg_dump installed
# too (e.g. for a manual/local dry run), not only inside the container.

set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
TARGET_URL="${1:-${BACKUP_DATABASE_URL:-}}"

if [ -z "$TARGET_URL" ]; then
  : "${PGHOST:?PGHOST (or a connection URL as \$1/BACKUP_DATABASE_URL) must be set}"
  : "${PGUSER:?PGUSER must be set}"
  : "${PGDATABASE:?PGDATABASE must be set}"
  # pg_dump reads PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE from the environment directly in
  # this branch — no explicit connection string needed.
  DB_LABEL="$PGDATABASE"
else
  DB_LABEL="$(printf '%s' "$TARGET_URL" | sed -E 's#.*/([^/?]+).*#\1#')"
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date -u +%Y%m%d_%H%M%S)"
DUMP_FILE="$BACKUP_DIR/raad_${DB_LABEL}_${TIMESTAMP}.dump"

# A failed pg_dump still leaves its --file target behind: an empty (or partial) .dump carrying a
# plausible name and a fresh timestamp, indistinguishable at a glance from a real backup. That
# artifact is more dangerous than no file at all — it is precisely what makes a wholly broken
# backup schedule read as merely "intermittent" to anyone listing this directory, and it cost
# this project a real recovery window on 2026-09-04.
#
# The DUMP_SIZE check further down cannot do this job: `set -e` aborts the script at the failing
# pg_dump line, so that check is unreachable in the exact case it was written for. It stays as a
# belt-and-braces guard for a pg_dump that *succeeds* while writing nothing; this trap is what
# actually handles failure.
cleanup_partial_dump() {
  _status=$?
  if [ "$_status" -ne 0 ] && [ -e "$DUMP_FILE" ]; then
    echo "[backup] FAILED (exit $_status) — removing partial dump so it can never be" >&2
    echo "[backup] mistaken for a usable backup: $DUMP_FILE" >&2
    rm -f "$DUMP_FILE"
  fi
}
trap cleanup_partial_dump EXIT

# Never log a connection string with its password in the clear — redact user:PASS@ down to
# user:***@ for display only; $TARGET_URL itself (passed to pg_dump below) is untouched.
LOG_TARGET="${TARGET_URL:-$PGHOST/$PGDATABASE}"
if [ -n "$TARGET_URL" ]; then
  LOG_TARGET="$(printf '%s' "$TARGET_URL" | sed -E 's#://([^:/@]+):[^@]*@#://\1:***@#')"
fi
echo "[backup] starting: target=$LOG_TARGET -> $DUMP_FILE"

# Compose's `depends_on: condition: service_healthy` orders the *initial* `compose up` only. It
# does not apply when Docker's own restart policy brings this container back — a daemon restart
# or host reboot — where `backup` can and does start before postgres accepts connections. The
# loop runs a dump immediately on start, so that race produced a failed backup (and, before the
# trap above, a zero-byte file) every single time the machine was restarted.
WAIT_SECONDS="${BACKUP_WAIT_FOR_DB_SECONDS:-120}"
POLL_SECONDS=3

wait_for_database() {
  _waited=0
  while :; do
    if [ -n "$TARGET_URL" ]; then
      if pg_isready -d "$TARGET_URL" >/dev/null 2>&1; then return 0; fi
    else
      if pg_isready >/dev/null 2>&1; then return 0; fi
    fi
    if [ "$_waited" -ge "$WAIT_SECONDS" ]; then
      echo "[backup] FATAL: database still not accepting connections after ${WAIT_SECONDS}s" >&2
      return 1
    fi
    if [ "$_waited" -eq 0 ]; then
      echo "[backup] database not ready yet — waiting up to ${WAIT_SECONDS}s for it"
    fi
    sleep "$POLL_SECONDS"
    _waited=$((_waited + POLL_SECONDS))
  done
}

wait_for_database

if [ -n "$TARGET_URL" ]; then
  pg_dump --format=custom --file="$DUMP_FILE" "$TARGET_URL"
else
  pg_dump --format=custom --file="$DUMP_FILE"
fi

DUMP_SIZE="$(wc -c < "$DUMP_FILE")"
if [ "$DUMP_SIZE" -eq 0 ]; then
  echo "[backup] FATAL: $DUMP_FILE is empty — pg_dump produced no data" >&2
  rm -f "$DUMP_FILE"
  exit 1
fi
echo "[backup] wrote $DUMP_FILE (${DUMP_SIZE} bytes)"

# --- Local retention -------------------------------------------------------------------------
find "$BACKUP_DIR" -name 'raad_*.dump' -type f -mtime "+${RETENTION_DAYS}" -print -delete 2>/dev/null | \
  while IFS= read -r pruned; do echo "[backup] pruned (older than ${RETENTION_DAYS}d): $pruned"; done

# --- Off-site copy (optional, pluggable) — see docs/runbooks/backup-and-restore.md's
# "Configuring off-site storage" section for how to point this at a real destination. Never
# silently skipped: an unconfigured remote is a loud, repeated warning, not a quiet no-op,
# matching this codebase's existing "fail loudly, don't fake it" posture for other unbound
# integrations (CLAUDE.md — PaymentProviderPort/VideoProviderPort).
if [ -n "${BACKUP_RCLONE_REMOTE:-}" ]; then
  echo "[backup] pushing to off-site remote: $BACKUP_RCLONE_REMOTE"
  rclone copy "$DUMP_FILE" "$BACKUP_RCLONE_REMOTE"
  echo "[backup] off-site copy complete"
else
  echo "[backup] WARNING: BACKUP_RCLONE_REMOTE is not set — this backup exists ONLY on this" >&2
  echo "[backup] WARNING: host's local disk. A VPS/disk failure right now would still mean" >&2
  echo "[backup] WARNING: total data loss. See docs/runbooks/backup-and-restore.md's" >&2
  echo "[backup] WARNING: 'Configuring off-site storage' section before relying on this in" >&2
  echo "[backup] WARNING: production." >&2
fi

echo "[backup] done"
