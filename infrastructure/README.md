# Infrastructure

Configuration and Infrastructure-as-Code for RAAD's runtime dependencies and cross-cutting
operational concerns. Contains configuration templates and placeholders only — no live secrets.

## Structure

| Path | Purpose |
|---|---|
| `nginx/` | Reverse proxy / TLS termination configuration for the client-facing edge. |
| `redis/` | No configuration lives here (Priority 1 Item 4, resolved the same way `backups/` was): Redis is hardened directly in `docker/docker-compose.yml`'s `redis` service (persistence, `maxmemory`/eviction, auth) — a mounted `redis.conf` would need its own envsubst-capable entrypoint (Redis's stock image has no equivalent to nginx's built-in templating) for no real benefit over Compose's own `${VAR}` substitution in `command:`, which already covers every tunable this deployment needs. See `docs/runbooks/redis-operations.md`. |
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

Structural scaffold only for `mysql/` (orphaned — the project has run PostgreSQL since
ADR-0002; nothing here reads this directory), `monitoring/`, `logging/`, and `deployment/` — all
still empty templates pending real values. `backups/` and `redis/` are both resolved the same
way: the actual, working mechanism (`PROJECT_STATUS.md` Priority 1 Items 1 and 4 respectively)
lives in `docker/` instead of here — see the table above. `nginx/`'s TLS half is likewise
resolved (Priority 1 Item 2, `prod-tls.conf`); only `nginx/`'s Kubernetes-scale-out seam (a
separate, later concern) remains a placeholder.
