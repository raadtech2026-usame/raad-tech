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
| `backups/` | Backup job configuration (MySQL automated backups, point-in-time recovery). |

Source of truth: `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §11 (Deployment
Architecture).

## Note

MVP orchestration is Docker Compose (see `../docker/`); this directory holds the configuration those
containers mount, plus the documented Kubernetes seam for future scale.

## Status

Structural scaffold only. All configuration files are empty templates pending real values.
