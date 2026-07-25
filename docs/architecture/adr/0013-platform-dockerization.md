# ADR-0013: Platform Dockerization

## Status
Accepted. Implemented this session — see Verification below for what was actually run and
confirmed against a live Docker Desktop/WSL2 environment (already confirmed reachable per
ADR-0012), not just asserted. **Follow-up pass (same day): a fresh-deployment login gap was
reported** (`docker compose down -v` → `up --build` → the web login rejects any credentials,
`401 UNAUTHENTICATED`) — root-caused, not a bug in the stack itself: `migrate` only applies
schema, and this project deliberately does not auto-seed a default account (a pre-existing,
already-implemented decision, `backend/raad/interfaces/cli/bootstrap_founder.py` +
`docs/runbooks/founder-bootstrap.md`, commit `8cdfc31`, predating this ADR). The actual gap was
this ADR's own omission: `docker/README.md` never mentioned that CLI because it was never
discovered while writing the original Docker stack. Closed by documenting the exact
`docker compose exec` invocation in `docker/README.md`'s new "First login" section — no code
changed. See the "Follow-up: Founder bootstrap" entry under Verification below for the full,
live-reproduced record.

## Context
`docker/docker-compose.yml` defined only `redis` (ADR-0012); every other service and all five
Dockerfiles named in `docker/README.md`'s original placeholder listing were unfilled. The user
asked for the whole dev-relevant platform — Frontend, Backend, PostgreSQL, Device Gateway, Redis,
Nginx — to start and stop with one Compose command, with the same Compose file/images working
unmodified on Windows (dev) and the production VPS (Phase 2 §11.1's own "MVP orchestration is
Docker Compose" decision, not revisited here, only finally implemented).

## Decision

### 1. A `worker` container, beyond the six named services
`interfaces/workers/bootstrap.py` (`python -m raad.interfaces.workers.bootstrap`) is the real,
already-built process the Notification Worker, Report Worker, outbox relay, and the three
scheduled jobs (retention/subscription-sweep/payment-reconciliation) all run under — a separate
OS process from `uvicorn`, per Backend LLD §11.1 and how this codebase already implemented it
(not merely how it could theoretically run). Without a container running it, none of those fire
anywhere in the dockerized stack. Confirmed with the user before implementing: add it as a 7th
service, reusing `backend.Dockerfile` verbatim with only `command:` differing — no new code, no
new image, no `worker.Dockerfile`.

### 2. A `migrate` one-off job
`alembic upgrade head`, then exits (`restart: "no"`), gating `backend`/`worker` startup via
`depends_on: condition: service_completed_successfully`. Not a platform service — exists so two
containers never race each other applying migrations, and so schema state is deterministic on
every `up`.

### 3. Two-layer Nginx/Frontend, confirmed with the user over the single-layer alternative
`frontend` serves itself: dev = Vite dev server (`--host 0.0.0.0`, HMR intact); prod = its own
`nginx:1.27-alpine` stage (`docker/frontend.Dockerfile`'s multi-stage `build` → `prod`) serving
the compiled bundle. The outer `nginx` service's only job is reverse-proxying `/api`, `/ws`,
`/health` to `backend` and everything else to `frontend` — same image, same role, in both
environments; only the config file it mounts differs (`infrastructure/nginx/conf.d/dev.conf` vs.
`prod.conf`). Rejected alternative: a single gateway-only Nginx serving the static bundle
directly out of a Docker volume populated by a one-off build step. Two containers in prod instead
of one, but each Dockerfile/config stays legible on its own — no "a named volume inherits image
content on first mount" behavior for a reader to already know about.

### 4. One base Compose file, dev/prod override layers
`docker-compose.yml` alone starts a complete, working dev stack — `docker compose -f
docker/docker-compose.yml up -d --build`. `docker-compose.dev.yml` layers bind-mounted source +
`uvicorn --reload` for hot iteration (optional — the base file runs correctly without it).
`docker-compose.prod.yml` layers exactly three things: `frontend`'s `build.target: prod` (+ its
Vite build-time `ARG`s), the gateway's `prod.conf` mount, and un-publishing every host port except
`nginx`'s. No `environment:` overrides live in the prod file at all — every app setting is already
`${VAR:-dev-default}`-substituted from one `docker/.env`, so a real VPS `.env` (never committed,
same shape as `docker/.env.example`) is the only thing that changes between environments.
`RAAD_ENVIRONMENT=prod` in that file trips `Settings.validate_on_startup()`'s existing
fail-loud check if a real `RAAD_AUTH__JWT_SECRET_KEY` was never set — no new safety mechanism
invented, just wired through Compose.

### 5. Base images
`python:3.11-slim` (backend/worker/migrate/device-gateway — matches
`.github/workflows/backend-pipeline.yml`'s own `actions/setup-python@v5` pin exactly),
`node:20-alpine` (frontend dev/build stages), `postgres:16-alpine` (major version matches that
same CI workflow's Postgres service container), `redis:7-alpine` (unchanged from ADR-0012),
`nginx:1.27-alpine` (gateway + frontend's prod stage).

### 6. `services/jt1078/` excluded
Still a structural scaffold with no approved language/runtime (`services/jt1078/README.md`) —
nothing to containerize. Matches the six services the user actually named; not a gap introduced
by this ADR.

## Options Considered

### Skip the `worker` container, ship exactly the six named services (rejected)
Would leave notifications, report rendering, the outbox relay, and every scheduled job silently
inert in the dockerized environment with no error or signal that anything was missing — a correct
literal reading of the request, but not a working platform. Raised explicitly with the user via
`AskUserQuestion` rather than decided unilaterally either way; user chose to include it.

### `env_file:` pointing at `backend/.env`/`services/device-gateway/.env` (rejected)
Those two files already exist and are documented for running each deployable directly, without
Docker. Pointing Compose at them too would mean keeping two copies of the same values in sync (one
for "run it directly," one for "run it in Docker") with no mechanism enforcing agreement between
them. `docker/.env` is the single source Compose reads from instead; each deployable's own
`.env.example` is left untouched, still valid for its own non-Docker workflow.

## Consequences
- `docker compose -f docker/docker-compose.yml [-f docker/docker-compose.dev.yml] up -d --build`
  is a genuine one-command start for the full dev stack (Postgres, Redis, migrations, the Business
  API, the worker process, the Device Gateway, the frontend, and the Nginx gateway fronting all of
  it); `down` is the matching one-command stop.
- The exact same base file plus `docker-compose.prod.yml` is the VPS deployment path — no
  parallel prod-only service definitions to drift from the dev ones.
- TLS termination at the Nginx gateway is not implemented — no domain name or certificate
  material exists yet; `infrastructure/nginx/conf.d/prod.conf`'s own comment marks where that
  goes once one does.
- `docker/README.md`'s original placeholder file listing (`jt808.Dockerfile`, `jt1078.Dockerfile`,
  `worker.Dockerfile`, plus an implied `nginx.Dockerfile`) no longer matches reality; that file was
  rewritten to explain each rename/merge/exclusion rather than silently dropping the old names.

## Verification
All run live against Docker Desktop/WSL2 (Docker 29.6.2, Compose v5.3.1) in this environment —
recorded honestly rather than asserted, per this repo's own ADR-0012 precedent.

- **Config validity:** `docker compose -f docker-compose.yml -f docker-compose.dev.yml config
  --quiet` and the equivalent `-prod.yml` merge both exit 0.
- **Dev stack, full `up -d --build`:** all 8 services reached running state; `migrate` exited 0
  (schema at head); `postgres`/`redis`/`backend`/`frontend`/`nginx`/`device-gateway` all reached
  Docker `healthy`; `worker` has no HTTP surface to heartbeat, confirmed running and processing
  events via its own structured logs instead (`workers_started`, plus one pre-existing
  `DevicePositionReported` entry — leftover Redis Streams backlog from ADR-0012's own prior
  session, not new — correctly retried then dead-lettered, proving the DLQ path live).
- **End-to-end routing through `nginx`:** `GET /health/ready` → `200 {"status":"ready"}`;
  `POST /api/v1/auth/login` with an empty body → `422` with the documented
  `{"error":{"code":"VALIDATION_ERROR",...}}` envelope (`.claude/rules/api.md` #4) — proves the
  `/api/` proxy reaches the real router, not a stub; `GET /` returns the real Vite-served app
  shell (`<title>RAAD — Web Dashboard</title>`, live HMR client script), proving the `/` → Vite
  dev server proxy.
- **Device Gateway:** both `7808` and `7809` accept TCP connections from the host; container logs
  show real `connection_accepted`/`connection_closed` cycles.
- **A real bug was found and fixed, not just infrastructure verified:** BusyBox `wget` (used in
  the `frontend`/`nginx` healthchecks) resolves `localhost` to `::1` first inside these Alpine
  images and — unlike Python's `urllib`/`socket.create_connection`, used in `backend`'s/
  `device-gateway`'s healthchecks — does not fall back to the IPv4 address Vite/nginx actually
  bind, so both healthchecks failed with "Connection refused" until pointed at `127.0.0.1`
  explicitly. Confirmed via `docker exec ... wget` against both `127.0.0.1` (succeeds) and
  `localhost` (fails) before concluding this, not assumed.
- **A second real bug, in `docker-compose.prod.yml` itself:** `ports: []` does not clear a
  service's published ports under this Compose version — `ports:` merges additively across `-f`
  layers by default, so the base file's ports survived unchanged. Confirmed via `docker compose
  config` showing `published: "8000"` still present for `backend` after the override. Fixed with
  the Compose Specification's explicit `!reset` merge-control tag (`ports: !reset []`); re-checked
  afterward — only `device-gateway` (`7808`/`7809`, deliberately still public: real bus hardware
  connects to it directly, not through `nginx`) and `nginx` (`80`) remain published in the prod
  merge.
- **Prod frontend build — pre-existing failure found and fixed, outside this ADR's original
  scope, confirmed with the user before fixing:** `docker/frontend.Dockerfile`'s `prod` target
  runs `tsc -b` (via `npm run build`) before `vite build`; this failed on a pre-existing
  TypeScript error in `frontend/src/shared/map/providers/MapboxMapProvider.test.ts:87` (a mocked
  `once("error", handler)` callback typed as zero-argument, called with one) — from the earlier
  Mapbox work (commit `8983dbb`, ADR-0011), confirmed via `git log`/`git status` to predate and be
  untouched by this session before the fix. Fixed by typing the mock's handler to accept the same
  `{ error?: unknown }` shape `MapboxMapProvider.mount()`'s real `once("error", ...)` handler
  actually reads, and passing a matching value instead of a triple-cast — the full frontend test
  suite (50 files / 306 tests) and the `prod` Docker build both pass after the fix.

### Follow-up: Founder bootstrap wiring (same day)
Reported symptom: all 7 containers healthy, migrations applied, but `POST /api/v1/auth/login`
returns `401` for every credential on a freshly-created deployment, and the login page appeared
to suggest `founder@raadtech.example` would work. Investigated rather than patched around:

- **Confirmed there is no auto-seed anywhere.** `grep`'d every migration for `INSERT`: only
  `role_permissions` (permission *grants* for the `founder` role name, ADR-0004) and
  `organization`'s starter regions — never a `users` row. No other script creates one either
  (`scripts/db/seed.sh` is an empty placeholder).
- **Confirmed a bootstrap path already exists and is not stale.** `backend/raad/interfaces/cli/
  bootstrap_founder.py` (git history: commit `8cdfc31`, well before ADR-0009) — its own module
  docstring already gives the "why manual, not auto-seed or an HTTP endpoint" reasoning quoted in
  Status above. Its three `UserApplicationService` calls (`invite_user`/`change_password`/
  `activate_user`) and `IamUnitOfWork.users.list_all()` guard were checked against the current
  `iam` module and still match exactly — not bit-rotted.
- **Checked the "misleading placeholder" claim directly against the source, not assumed true.**
  `frontend/src/app/LoginPage.tsx`'s two `Input` fields carry no `placeholder` prop at all, and a
  repo-wide case-insensitive search for `founder@raadtech` and `raadtech.example` (including the
  approved design mockup HTML) returned zero matches anywhere. Reported back rather than
  "fixed": there was nothing in the actual running UI to remove.
- **Live reproduction, this environment:** `docker compose down -v` → `up -d --build` (fresh
  Postgres/Redis volumes) → `POST /api/v1/auth/login` → `401 {"error":{"code":
  "UNAUTHENTICATED",...}}`, confirming the report exactly.
- **Fix applied and live-verified:**
  `docker compose exec -e RAAD_BOOTSTRAP_FOUNDER_EMAIL=... -e RAAD_BOOTSTRAP_FOUNDER_PASSWORD=...
  backend python -m raad.interfaces.cli.bootstrap_founder --full-name "..."` → `Founder account
  created and activated`; the same `/auth/login` call that returned `401` moments earlier now
  returns `200` with a real `access_token`/`refresh_token`/`principal` (`role: "founder"`).
  Re-running the identical bootstrap command a second time correctly refused (`Refusing to
  bootstrap: 1 user(s) already exist`, exit 1) — the idempotency/no-duplicate-users guarantee
  holds under a real repeated invocation, not just by reading the code.
- **No code changed.** The fix is entirely documentation: `docker/README.md` gained a "First
  login — bootstrapping the Founder account" section with the exact command (the bootstrap
  email/password are passed as ad hoc `docker compose exec -e` flags, deliberately kept out of
  `docker-compose.yml`'s persistent `environment:` block and out of `docker/.env` — a one-time-use
  password has no reason to sit in a container's environment indefinitely); `docker/.env.example`
  gained a comment pointing to it. `CLAUDE.md`'s IAM bullet also gained one sentence — the
  bootstrap CLI/runbook existed before this session but was never recorded there, a genuine,
  separate, pre-existing documentation gap surfaced by this investigation, not caused by it.

## Post-fix state
- `docker/docker-compose.yml`: `frontend`/`nginx` healthchecks target `127.0.0.1`, not
  `localhost`.
- `docker/docker-compose.prod.yml`: `ports: !reset []` (not `ports: []`) on
  `postgres`/`redis`/`backend`/`frontend`.
- `frontend/src/shared/map/providers/MapboxMapProvider.test.ts`: the one-line mock-typing fix
  above (test file only — no production frontend code changed).
- `docker/README.md`: new "First login — bootstrapping the Founder account" section.
- `docker/.env.example`: a comment documenting (not defaulting) `RAAD_BOOTSTRAP_FOUNDER_EMAIL`/
  `RAAD_BOOTSTRAP_FOUNDER_PASSWORD`.
- `CLAUDE.md`: IAM bounded-context bullet now mentions `bootstrap_founder.py`/the runbook.

## References
- `docs/architecture/adr/0008-redis-streams-event-broker.md`
- `docs/architecture/adr/0009-mdvr-vendor-protocol-device-plane.md`
- `docs/architecture/adr/0010-device-gateway-multi-vendor-architecture.md`
- `docs/architecture/adr/0012-development-redis-environment.md`
- `docker/README.md`, `docker/docker-compose.yml`, `docker/docker-compose.dev.yml`,
  `docker/docker-compose.prod.yml`, `docker/.env.example`
- `backend/raad/interfaces/cli/bootstrap_founder.py`, `docs/runbooks/founder-bootstrap.md`
