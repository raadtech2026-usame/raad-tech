# Docker

Container definitions and Compose orchestration for the whole RAAD platform — local development
and the production VPS, from the same files (ADR-0013: `docs/architecture/adr/
0013-platform-dockerization.md`). MVP orchestration is Docker Compose per
`docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §11.1; Kubernetes is the documented
(not yet built) scale-out target.

## Services

| Service | Image | Role |
|---|---|---|
| `postgres` | `postgres:16-alpine` | Business API's database (ADR-0002). |
| `redis` | `redis:7-alpine` | `tracking`'s `RedisLatestPositionPort` + the Redis Streams event broker (ADR-0008), shared with `device-gateway` (ADR-0010, ADR-0012). |
| `migrate` | built from `backend.Dockerfile` | One-off `alembic upgrade head`, then exits. Not a platform service — exists so `backend`/`worker` never race each other applying migrations. |
| `backend` | built from `backend.Dockerfile` | The FastAPI Business API (`uvicorn raad.main:app`). |
| `worker` | built from `backend.Dockerfile` (same image, different `command:`) | `python -m raad.interfaces.workers.bootstrap` — Notification/Report Workers, outbox relay, and the three scheduled jobs (Backend LLD §11.1). Not one of the platform pieces originally named, but required for those to actually run anywhere in this stack. |
| `device-gateway` | built from `device-gateway.Dockerfile` | The multi-vendor device-plane gateway (ADR-0009/ADR-0010) — terminates bus terminal TCP connections on `7808` (dormant JT/T 808) and `7809` (LSZ MDVR, the actually-integrated hardware). |
| `backup` | built from `backup.Dockerfile` | Priority 1 Item 1 (`PROJECT_STATUS.md`) — periodically `pg_dump`s `postgres` into the `raad_backups_data` volume, prunes local dumps past `BACKUP_RETENTION_DAYS`, and pushes off-site via `rclone` if `BACKUP_RCLONE_REMOTE` is configured. See `docs/runbooks/backup-and-restore.md`. |
| `frontend` | built from `frontend.Dockerfile` | React web dashboard. Dev: Vite dev server w/ HMR on `5173`. Prod: its own `nginx:alpine` serving the built static bundle on `80`. |
| `nginx` | stock `nginx:1.27-alpine` | The platform's single public entrypoint — reverse-proxies `/api`, `/ws`, `/health` to `backend` and everything else to `frontend`. No custom Dockerfile: its config is bind-mounted from `infrastructure/nginx/conf.d/` (dev: `dev.conf`; prod: `prod.conf` or, once TLS is bootstrapped, `prod-tls.conf` — both mounted via nginx's own official templating mechanism so `${DOMAIN_NAME}` resolves for real). |
| `certbot` | stock `certbot/certbot:latest` (prod only) | Priority 1 Item 2 (`PROJECT_STATUS.md`) — obtains and renews the Let's Encrypt certificate `prod-tls.conf` serves, via the webroot HTTP-01 challenge. Reloads `nginx` after a real renewal by sharing its PID namespace (`kill -HUP 1`), not the Docker socket. See `docs/runbooks/tls-setup.md`. |
| `prometheus` | stock `prom/prometheus:v2.53.0` | Priority 1 Item 5 (`PROJECT_STATUS.md`) — scrapes `backend`'s `/metrics` (`raad_http_requests_total`, `raad_dependency_up`, `raad_process_start_time_seconds`; `core/observability/metrics.py`, a hand-rolled exposition endpoint, no `prometheus-client` dependency). Not published to a host port by default — reachable inside the Docker network only until fronted by `nginx` or given its own auth. Grafana dashboards are not built this phase (no live Prometheus target existed to design meaningful panels against) — see `docs/runbooks/monitoring.md`. |

`services/jt1078/` has no service here — still a structural scaffold with no approved language/
runtime (`services/jt1078/README.md`), so there is nothing to containerize yet.

## Files

- `docker-compose.yml` — the base file. Alone, it fully starts a working dev stack.
- `docker-compose.dev.yml` — hot-reload/DX overrides (bind-mounted source, `uvicorn --reload`).
  Optional — the base file already runs correctly without it, just without live-reload.
- `docker-compose.prod.yml` — generic-VPS overrides: `frontend` builds its static bundle instead
  of running the Vite dev server, `nginx` serves `prod.conf`/`prod-tls.conf` instead of `dev.conf`
  (plus a `certbot` service and its two volumes, Priority 1 Item 2), and only `nginx` keeps a
  published host port (`80` always, `443` once TLS is bootstrapped). A real `docker/.env` on the
  VPS (same shape as `.env.example`, never committed) is all that's needed; see that file's own
  comments for `RAAD_ENVIRONMENT=prod`'s fail-loud JWT-secret check.
- `docker-compose.coolify.yml` — **alternative** to `docker-compose.prod.yml` (ADR-0022), for a
  Coolify-managed deployment (Coolify's own Traefik owns reverse-proxy/TLS instead of this
  stack's `nginx`/`certbot`, which never start on this path — see the `gateway` Compose profile
  below). Pick exactly one of `docker-compose.prod.yml` / `docker-compose.coolify.yml`, never
  both. Full guide: `docs/runbooks/coolify-deployment.md`.
- `.env.example` — the one Compose-level env template. Copy to `docker/.env` before first run.
  Sets `COMPOSE_PROFILES=gateway` by default — Compose's own mechanism (read automatically from
  `.env`, no flag needed) for including `nginx` (and, in `docker-compose.prod.yml`, `certbot`) in
  every command below; the Coolify path (its own separate environment-variables UI, never this
  file) deliberately leaves it unset instead, since Coolify already runs its own reverse proxy.
- `backend.Dockerfile` — builds the Business API image; also reused for `migrate`/`worker`.
- `frontend.Dockerfile` — multi-stage (`deps` → `dev` / `build` → `prod`); `target` picks dev
  vs. prod.
- `device-gateway.Dockerfile` — builds the device-plane gateway image.
- `backup.Dockerfile` — builds `FROM postgres:16-alpine` (reuses its `pg_dump`/`pg_restore`)
  plus `rclone` for the optional off-site copy; the only Dockerfile here whose build context is
  the repo root rather than one component's own directory, since `scripts/db/*.sh` live outside
  any single deployable.

There is no `jt808.Dockerfile`, `jt1078.Dockerfile`, `worker.Dockerfile`, or `nginx.Dockerfile`
(all four were named in this file's original placeholder listing):
`jt808.Dockerfile` → renamed `device-gateway.Dockerfile` once that deployable absorbed the
JT/T 808 code as one vendor adapter among several (ADR-0010); `jt1078.Dockerfile` doesn't exist
yet because that service still has no approved runtime to build; `worker.Dockerfile` doesn't
exist because `worker` reuses `backend.Dockerfile` verbatim, just with a different `command:`;
`nginx.Dockerfile` doesn't exist because the gateway needs no custom image at all — a stock
`nginx:1.27-alpine` plus a bind-mounted config file is sufficient (the frontend's *own* prod-stage
nginx lives inside `frontend.Dockerfile` instead, since it needs the multi-stage build's output).

## Running it

All commands assume `docker/.env` exists (`cp docker/.env.example docker/.env`, then edit — at
minimum set a real `RAAD_AUTH__JWT_SECRET_KEY` before ever setting `RAAD_ENVIRONMENT=prod`).

**Dev, with hot reload (recommended):**

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up -d --build
```

**Dev, bare minimum (single file, still fully functional — just rebuild to see changes):**

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

**Production (VPS):**

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d --build
```

**Stop (any of the above):** replace `up -d --build` with `down`.

Once up, everything is reachable through Nginx at `http://localhost:${NGINX_PORT:-80}/` — the
web dashboard at `/`, the API at `/api/v1/...`, WebSockets at `/ws/tracking`/`/ws/notifications`,
health checks at `/health*`. `postgres`/`redis`/`backend` also publish their own ports in dev
(`docker compose ps` for the exact mapping) for direct debugging; `docker-compose.prod.yml`
un-publishes all of them except `nginx`.

## First login — bootstrapping the Founder account

`migrate` only applies schema (Alembic) — it never creates a user. A fresh `up` therefore leaves
`users` genuinely empty by design, not by omission: this project deliberately does **not**
auto-seed a default account. `backend/raad/interfaces/cli/bootstrap_founder.py`'s own module
docstring gives the reasoning (also recorded in ADR-0013's own follow-up Verification entry) — a
migration-seeded row would be a fixed, version-controlled credential (the hardcoded-backdoor
shape this is required *not* to be), and an HTTP "create the first user" endpoint would have to be
reachable without authentication, a new public attack surface with no equivalent anywhere else in
this API. Instead, run the existing bootstrap CLI once, behind your own deployment's access
boundary, against the running `backend` container:

```bash
docker compose -f docker/docker-compose.yml exec \
  -e RAAD_BOOTSTRAP_FOUNDER_EMAIL="founder@yourorg.example" \
  -e RAAD_BOOTSTRAP_FOUNDER_PASSWORD="<a strong password of your own choosing>" \
  backend python -m raad.interfaces.cli.bootstrap_founder --full-name "Your Name"
```

These two `-e` flags are deliberately not part of `docker-compose.yml`'s own `environment:` block
or `docker/.env` — nothing this codebase treats as a password sits in a persistent container
environment 24/7 for a step meant to run exactly once. The command refuses to run (no rows
touched) if `users` already has any row at all, so it's safe to keep this command around; it will
only ever succeed on a genuinely fresh database. Full operator guide, including troubleshooting an
interrupted bootstrap: `docs/runbooks/founder-bootstrap.md`.

The web login form (`frontend/src/app/LoginPage.tsx`) has no placeholder/example credentials on
either field — there is nothing to type until you've run the command above with an email/password
of your own choosing.

## Backups

The `backup` service runs continuously alongside the rest of the stack — no separate step is
needed to get automated local dumps once `docker compose up` includes it (it always does; it's
in the base file, not a prod-only overlay). It ships **local-only** by default: set
`BACKUP_RCLONE_REMOTE` in `docker/.env` to also push each dump off-site, or the service logs a
loud, repeated warning on every run reminding you it hasn't been configured. Full operator guide
— manual backup/restore, disaster recovery, configuring off-site storage —
`docs/runbooks/backup-and-restore.md`.

## TLS

Not enabled by default — a fresh `docker/.env` (nothing filled in) runs `nginx` on plain HTTP
exactly as before, via `NGINX_PROD_CONF=prod.conf`. Enabling real HTTPS is a one-time, two-phase
bootstrap (get the first certificate while still on plain HTTP, then switch configs) documented
in full — DNS prerequisite, exact commands, verifying auto-renewal, troubleshooting —
in `docs/runbooks/tls-setup.md`. Once bootstrapped, the `certbot` service renews automatically;
no further manual steps.

## Deploying to a real VPS

This section (and everything above it) assumes Docker and the repo already exist on a machine.
Provisioning that machine in the first place — OS baseline, firewall, installing Docker itself,
first boot, DNS/TLS handoff — is `docs/runbooks/vps-deployment.md` (Priority 1 Item 7), for the
generic-VPS/nginx/certbot path above. For a Coolify-managed deployment (Hostinger VPS or any other)
instead, see `docs/runbooks/coolify-deployment.md` — installing Coolify itself, connecting this
repo, and its own UI-driven environment-variable/domain assignment replace Steps 2–7 of the
generic guide. If a deployment goes bad, `docs/runbooks/rollback.md` covers application-code
rollback, migration rollback (and when it's genuinely *not* safely reversible), and the
last-resort full backup restore — identically for either deployment path.

## Status

Docker itself: implemented (ADR-0013). TLS: mechanism implemented (Priority 1 Item 2,
`PROJECT_STATUS.md`) but not live-tested against a real domain in this repository's own
development — see the runbook's own disclosed testing scope. `services/jt1078/` still has no
approved runtime to containerize.
