# Docker

Container definitions and Compose orchestration for local development, staging, and production.
MVP orchestration is Docker Compose per `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md`
§11.1; Kubernetes is the documented (not yet built) scale-out target.

## Files (placeholders)

- `docker-compose.yml` — base service definitions (business API, workers, JT808 server, JT1078
  server, MySQL, Redis, broker).
- `docker-compose.dev.yml` — local development overrides.
- `docker-compose.prod.yml` — production overrides.
- `backend.Dockerfile`, `frontend.Dockerfile`, `jt808.Dockerfile`, `jt1078.Dockerfile`,
  `worker.Dockerfile` — per-deployable build definitions.

## Status

Structural scaffold only. All files are empty placeholders pending tooling decisions.
