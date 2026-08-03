# Infrastructure

Configuration and Infrastructure-as-Code for RAAD's runtime dependencies and cross-cutting
operational concerns. Contains configuration templates and placeholders only — no live secrets.

## Structure

| Path | Purpose |
|---|---|
| `nginx/` | Reverse proxy / TLS termination configuration for the client-facing edge. |
| `redis/` | Redis configuration (hot state: device sessions, latest positions, pub/sub, caches). |
| `mysql/` | MySQL 8.x initialization scripts and configuration templates. |
| `monitoring/` | Prometheus + Grafana configuration for platform observability. |
| `logging/` | Centralized logging configuration. |
| `deployment/` | Deployment manifests — `compose/` for MVP (Docker Compose), `k8s/` as the documented scale-out target (not used at MVP). |
| `backups/` | No configuration lives here — the backup job itself is the `backup` Docker Compose service (`docker/backup.Dockerfile`, `docker/docker-compose.yml`), not a file mounted from this directory. See `docs/runbooks/backup-and-restore.md`. |

Source of truth: `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §11 (Deployment
Architecture).

## Note

MVP orchestration is Docker Compose (see `../docker/`); this directory holds the configuration those
containers mount, plus the documented Kubernetes seam for future scale.

## Status

Structural scaffold only for `nginx/`'s TLS half, `redis/`, `mysql/` (orphaned — the project has
run PostgreSQL since ADR-0002; nothing here reads this directory), `monitoring/`, `logging/`, and
`deployment/` — all still empty templates pending real values. `backups/` is the one exception:
the actual, working mechanism (`PROJECT_STATUS.md` Priority 1 Item 1) lives in `docker/` and
`scripts/db/` instead of here — see the table above.
