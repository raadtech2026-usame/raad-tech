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

# A failed backup must not cost a full interval. Sleeping the normal 24h after a failure means
# one transient outage leaves the platform with no fresh backup for a day — and because the loop
# fires a dump immediately on container start, the most likely failure (postgres not up yet after
# a host reboot) is exactly the one that would burn that whole day. Retry soon instead.
RETRY_MINUTES="${BACKUP_RETRY_MINUTES:-15}"

while true; do
  if /app/backup.sh; then
    sleep $((INTERVAL_HOURS * 3600))
  else
    echo "[backup-loop] backup.sh exited non-zero — retrying in ${RETRY_MINUTES}m" >&2
    sleep $((RETRY_MINUTES * 60))
  fi
done
