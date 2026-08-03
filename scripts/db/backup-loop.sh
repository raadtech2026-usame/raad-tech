#!/bin/sh
# scripts/db/backup-loop.sh — the `backup` Docker Compose service's long-running process: calls
# backup.sh, sleeps BACKUP_INTERVAL_HOURS, repeats. Kept as its own file (not inlined into
# docker-compose.yml's `command:`) specifically so its `$((...))` shell arithmetic never has to
# coexist with Compose's own `${VAR}` interpolation syntax in the same string — one template
# system per file. No cron daemon: one less moving part than installing/configuring crond for a
# single periodic command.

set -eu

INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"

echo "[backup-loop] running every ${INTERVAL_HOURS}h"

while true; do
  /app/backup.sh || echo "[backup-loop] backup.sh exited non-zero — will retry next cycle" >&2
  sleep $((INTERVAL_HOURS * 3600))
done
