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

# Never log a connection string with its password in the clear — redact user:PASS@ down to
# user:***@ for display only; $TARGET_URL itself (passed to pg_dump below) is untouched.
LOG_TARGET="${TARGET_URL:-$PGHOST/$PGDATABASE}"
if [ -n "$TARGET_URL" ]; then
  LOG_TARGET="$(printf '%s' "$TARGET_URL" | sed -E 's#://([^:/@]+):[^@]*@#://\1:***@#')"
fi
echo "[backup] starting: target=$LOG_TARGET -> $DUMP_FILE"

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
