#!/bin/sh
# scripts/tls/certbot-renew-loop.sh — the `certbot` Docker Compose service's long-running
# process: checks for due renewals on a schedule, reloads nginx only when a renewal actually
# happens. Mirrors scripts/db/backup-loop.sh's shape exactly (its own file, not inlined into
# docker-compose.prod.yml's `command:`, so its arithmetic never has to coexist with Compose's
# own ${VAR} interpolation syntax in the same string).
#
# `certbot renew` itself is a no-op for any certificate not within its renewal window (Let's
# Encrypt recommends renewing at 30 days before a 90-day expiry) — safe to call on every tick.
# `kill -HUP 1` reaches nginx's master process because this service shares nginx's PID namespace
# (docker-compose.prod.yml's `pid: "service:nginx"`) — the lower-privilege alternative to
# mounting the Docker socket just to run `docker exec nginx nginx -s reload`.

set -eu

INTERVAL_HOURS="${CERTBOT_RENEW_INTERVAL_HOURS:-12}"

echo "[certbot-renew-loop] checking for due renewals every ${INTERVAL_HOURS}h"

while true; do
  certbot renew \
    --webroot --webroot-path /var/www/certbot \
    --deploy-hook "kill -HUP 1" \
    --non-interactive \
    || echo "[certbot-renew-loop] certbot renew exited non-zero — will retry next cycle" >&2
  sleep $((INTERVAL_HOURS * 3600))
done
