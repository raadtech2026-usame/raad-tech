#!/bin/sh
# testing/backups/test_backup_restore.sh — automated round-trip test for scripts/db/backup.sh
# and scripts/db/restore.sh, against a live PostgreSQL server. Not part of backend/tests/ (that
# taxonomy is fixed to the `raad` Python package's own unit/integration/contract/architecture
# layers, .claude/rules/testing.md #1) — this tests standalone shell tooling that operates on a
# whole database, a cross-cutting operational concern, matching testing/load/'s existing
# precedent for where that kind of concern lives (.claude/rules/testing.md #2).
#
# Creates two disposable, uniquely-named databases on the target server, seeds a marker row,
# backs up, restores into the second database, asserts the marker round-tripped, then drops both
# — never touches any pre-existing database. Requires PGHOST/PGPORT/PGUSER/PGPASSWORD (or a
# libpq-recognized equivalent, e.g. a .pgpass file / trust auth) pointing at a real, reachable
# PostgreSQL server, and pg_dump/pg_restore/psql/createdb/dropdb on PATH.
#
# Usage: PGHOST=localhost PGUSER=raad PGPASSWORD=raad sh testing/backups/test_backup_restore.sh

set -eu

if [ -d "/usr/lib/postgresql/16/bin" ] && [ "${PATH#*/usr/lib/postgresql/16/bin}" = "$PATH" ]; then
  export PATH="/usr/lib/postgresql/16/bin:$PATH"
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
BACKUP_SH="$REPO_ROOT/scripts/db/backup.sh"
RESTORE_SH="$REPO_ROOT/scripts/db/restore.sh"

: "${PGHOST:?PGHOST must be set (a reachable PostgreSQL server)}"
: "${PGUSER:?PGUSER must be set}"

RUN_ID="$$_$(date -u +%s)"
DRILL_DB="raad_test_backup_${RUN_ID}"
RESTORE_DB="raad_test_restore_${RUN_ID}"
WORK_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t raad_backup_test)"

cleanup() {
  status=$?
  dropdb --if-exists "$DRILL_DB" >/dev/null 2>&1 || true
  dropdb --if-exists "$RESTORE_DB" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
  exit "$status"
}
trap cleanup EXIT INT TERM

echo "[test] creating throwaway databases: $DRILL_DB, $RESTORE_DB"
createdb "$DRILL_DB"
createdb "$RESTORE_DB"

echo "[test] verifying PostgreSQL client and server version compatibility"
PG_DUMP_VER="$(pg_dump --version)"
PG_RESTORE_VER="$(pg_restore --version)"
PSQL_VER="$(psql --version)"
echo "[test] pg_dump: $PG_DUMP_VER"
echo "[test] pg_restore: $PG_RESTORE_VER"
echo "[test] psql: $PSQL_VER"

PG_DUMP_MAJOR="$(echo "$PG_DUMP_VER" | sed -E 's/.*PostgreSQL[^0-9]*([0-9]+).*/\1/')"
PG_RESTORE_MAJOR="$(echo "$PG_RESTORE_VER" | sed -E 's/.*PostgreSQL[^0-9]*([0-9]+).*/\1/')"

SERVER_NUM="$(psql -v ON_ERROR_STOP=1 -d "$DRILL_DB" -tAc "SHOW server_version_num;")"
SERVER_VER="$(psql -v ON_ERROR_STOP=1 -d "$DRILL_DB" -tAc "SHOW server_version;")"
SERVER_MAJOR=$((SERVER_NUM / 10000))
echo "[test] server_version: $SERVER_VER (major: $SERVER_MAJOR)"

if [ "$PG_DUMP_MAJOR" != "$SERVER_MAJOR" ]; then
  echo "[test] FAIL: pg_dump major version ($PG_DUMP_MAJOR) does not match target server major version ($SERVER_MAJOR)" >&2
  exit 1
fi

if [ "$PG_RESTORE_MAJOR" != "$SERVER_MAJOR" ]; then
  echo "[test] FAIL: pg_restore major version ($PG_RESTORE_MAJOR) does not match target server major version ($SERVER_MAJOR)" >&2
  exit 1
fi

echo "[test] version check passed: pg_dump, pg_restore, and PostgreSQL server are all major version $SERVER_MAJOR"

echo "[test] seeding marker row into $DRILL_DB"
psql -v ON_ERROR_STOP=1 -d "$DRILL_DB" \
  -c "CREATE TABLE backup_drill_marker (id serial PRIMARY KEY, note text NOT NULL);" \
  -c "INSERT INTO backup_drill_marker (note) VALUES ('automated-round-trip-test');" \
  >/dev/null

echo "[test] running backup.sh"
BACKUP_DIR="$WORK_DIR" BACKUP_RETENTION_DAYS=14 PGDATABASE="$DRILL_DB" sh "$BACKUP_SH"

DUMP_FILE="$(find "$WORK_DIR" -name 'raad_*.dump' -type f | head -n1)"
if [ -z "$DUMP_FILE" ]; then
  echo "[test] FAIL: backup.sh did not produce a dump file in $WORK_DIR" >&2
  exit 1
fi

echo "[test] verifying dump is structurally valid (pg_restore --list)"
pg_restore --list "$DUMP_FILE" | grep -q "backup_drill_marker" || {
  echo "[test] FAIL: dump does not contain the expected table" >&2
  exit 1
}

echo "[test] running restore.sh into $RESTORE_DB"
sh "$RESTORE_SH" --target-url "postgresql://${PGUSER}@${PGHOST}:${PGPORT:-5432}/${RESTORE_DB}" \
  --confirm "$DUMP_FILE"

echo "[test] asserting the marker row round-tripped"
RESULT="$(psql -v ON_ERROR_STOP=1 -d "$RESTORE_DB" -tAc \
  "SELECT note FROM backup_drill_marker WHERE note = 'automated-round-trip-test';")"

if [ "$RESULT" != "automated-round-trip-test" ]; then
  echo "[test] FAIL: marker row missing or wrong after restore (got: '$RESULT')" >&2
  exit 1
fi

echo "[test] PASS: backup.sh + restore.sh round-trip verified"
