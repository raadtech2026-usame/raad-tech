#!/bin/sh
# scripts/db/restore.sh — restores a dump produced by scripts/db/backup.sh into a target
# database. Destructive by design (pg_restore --clean drops existing objects in the target
# before recreating them) — requires an explicit --target-url and --confirm, and never falls
# back to any "current"/implicit database the way backup.sh's env-var branch does, specifically
# so a mistyped invocation cannot silently wipe the wrong database. The target database itself
# must already exist (CREATE DATABASE first) — this restores objects into it, it does not create
# the database. See docs/runbooks/backup-and-restore.md for the full disaster-recovery
# procedure.
#
# Usage: restore.sh --target-url <postgres-url> --confirm <dump-file>
#
# Deliberately POSIX `sh` — see backup.sh's own header comment for why.

set -eu

TARGET_URL=""
CONFIRMED=0
DUMP_FILE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --target-url)
      TARGET_URL="${2:-}"
      shift 2
      ;;
    --confirm)
      CONFIRMED=1
      shift
      ;;
    *)
      DUMP_FILE="$1"
      shift
      ;;
  esac
done

if [ -z "$TARGET_URL" ] || [ -z "$DUMP_FILE" ]; then
  echo "usage: restore.sh --target-url <postgres-url> --confirm <dump-file>" >&2
  exit 2
fi

# Never log a connection string with its password in the clear — redact user:PASS@ down to
# user:***@ for display only; $TARGET_URL itself (passed to pg_restore below) is untouched.
LOG_TARGET="$(printf '%s' "$TARGET_URL" | sed -E 's#://([^:/@]+):[^@]*@#://\1:***@#')"

if [ "$CONFIRMED" -ne 1 ]; then
  echo "[restore] refusing to run without --confirm — this REPLACES every object in:" >&2
  echo "[restore]   $LOG_TARGET" >&2
  echo "[restore] re-run with --confirm once you are certain that is the intended target." >&2
  exit 1
fi

if [ ! -f "$DUMP_FILE" ]; then
  echo "[restore] FATAL: dump file not found: $DUMP_FILE" >&2
  exit 1
fi

echo "[restore] restoring $DUMP_FILE -> $LOG_TARGET"
pg_restore --clean --if-exists --no-owner --dbname="$TARGET_URL" "$DUMP_FILE"
echo "[restore] done"
