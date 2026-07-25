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
| `frontend` | built from `frontend.Dockerfile` | React web dashboard. Dev: Vite dev server w/ HMR on `5173`. Prod: its own `nginx:alpine` serving the built static bundle on `80`. |
| `nginx` | stock `nginx:1.27-alpine` | The platform's single public entrypoint — reverse-proxies `/api`, `/ws`, `/health` to `backend` and everything else to `frontend`. No custom Dockerfile: its config is bind-mounted from `infrastructure/nginx/conf.d/` (`dev.conf` or `prod.conf`). |

`services/jt1078/` has no service here — still a structural scaffold with no approved language/
runtime (`services/jt1078/README.md`), so there is nothing to containerize yet.

## Files

- `docker-compose.yml` — the base file. Alone, it fully starts a working dev stack.
- `docker-compose.dev.yml` — hot-reload/DX overrides (bind-mounted source, `uvicorn --reload`).
  Optional — the base file already runs correctly without it, just without live-reload.
- `docker-compose.prod.yml` — VPS overrides: `frontend` builds its static bundle instead of
  running the Vite dev server, `nginx` serves `prod.conf` instead of `dev.conf`, and only `nginx`
  keeps a published host port. No `environment:` overrides live here — a real `docker/.env` on
  the VPS (same shape as `.env.example`, never committed) is all that's needed; see that file's
  own comments for `RAAD_ENVIRONMENT=prod`'s fail-loud JWT-secret check.
- `.env.example` — the one Compose-level env template. Copy to `docker/.env` before first run.
- `backend.Dockerfile` — builds the Business API image; also reused for `migrate`/`worker`.
- `frontend.Dockerfile` — multi-stage (`deps` → `dev` / `build` → `prod`); `target` picks dev
  vs. prod.
- `device-gateway.Dockerfile` — builds the device-plane gateway image.

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

## Status

Implemented (ADR-0013). Not yet covered: TLS termination at the Nginx gateway (no domain/cert
material exists yet — see `infrastructure/nginx/conf.d/prod.conf`'s own comment for where that
goes) and `services/jt1078/` (still no approved runtime).
