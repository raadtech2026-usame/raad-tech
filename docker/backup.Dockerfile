# RAAD Platform — backup service image (Priority 1 Item 1, docs/runbooks/backup-and-restore.md).
#
# Built FROM postgres:16-alpine (not python:3.11-slim, unlike backend.Dockerfile) specifically
# because that image already ships pg_dump/pg_restore/psql matching the exact server version
# this platform runs (ADR-0002) — installing a separate PostgreSQL client toolchain into a
# generic base image would be strictly more moving parts for the same result.
#
# rclone (MIT license, https://rclone.org) is the one new dependency this Priority 1 item adds —
# a single static Go binary, not a Python/Node package, so it never touches pyproject.toml or
# package.json. Chosen because it speaks one config format across 40+ storage backends (S3,
# Backblaze B2, DigitalOcean Spaces, SFTP, ...) rather than committing this repo to one vendor's
# SDK before a real off-site destination is actually provisioned — see backup.sh's own comments
# for the "configured or loudly skipped, never silently skipped" contract this implies.
#
# Build context is the repo root (not a component subdirectory like backend.Dockerfile's
# ../backend) — the only Dockerfile in docker/ that needs this, because scripts/db/*.sh live at
# the repo root, outside any single deployable's own directory.

FROM postgres:16-alpine

RUN apk add --no-cache rclone

WORKDIR /app

COPY scripts/db/backup.sh /app/backup.sh
COPY scripts/db/restore.sh /app/restore.sh
COPY scripts/db/backup-loop.sh /app/backup-loop.sh
RUN chmod +x /app/backup.sh /app/restore.sh /app/backup-loop.sh

# No CMD/ENTRYPOINT here — docker-compose.yml's `backup` service supplies the run loop directly
# as its `command:`, the same "image defines the tools, Compose defines the schedule" split
# `backend.Dockerfile` already documents for how `migrate`/`worker` reuse one image.
