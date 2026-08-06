# Runbook: Coolify deployment (Hostinger VPS)

ADR-0022 (`docs/architecture/adr/0022-payment-provider-architecture.md`, "Coolify vs nginx"
decision). An **alternative** path to `docs/runbooks/vps-deployment.md`, not a replacement — that
guide (generic VPS, this stack's own `nginx`/`certbot`) remains fully valid. Pick exactly one path
per deployment; never run both `docker-compose.prod.yml` and `docker-compose.coolify.yml` against
the same stack.

**Disclosed scope, matching this project's own established practice for every deployment runbook
(`tls-setup.md`, `redis-operations.md`, `vps-deployment.md`):** no Hostinger VPS or live Coolify
instance exists in this development environment, so the Coolify-UI-specific steps below (Steps
2–4) are written from Coolify's own published documentation, not independently exercised against a
running instance — the same disclosed-limitation posture those other runbooks already carry for
their own mechanisms. `docker-compose.coolify.yml` itself **is** verified — structurally validated
(YAML parses, `!reset`/`profiles` merge correctly) and a hand-written Compose-merge simulation
confirmed the final `postgres`/`redis`/`backend`/`frontend` services publish no host ports, the
`frontend` service builds with `target: prod` and the SPA-fallback mount, and `nginx`/`certbot`
(gated behind the `gateway` Compose profile, `docker/.env.example`) are excluded entirely — the
same "structural validation, no Docker daemon in this sandbox" limitation `docker-compose.prod.yml`
itself has always carried.

## Why this path exists

`docs/runbooks/vps-deployment.md` assumes you run and maintain this stack's own `nginx`/`certbot`
services for reverse-proxying and TLS. Coolify is a self-hostable PaaS that already runs its own
reverse proxy (Traefik) with automatic Let's Encrypt TLS, a web dashboard for managing
deployments/domains/environment variables, and git-push-to-deploy — running this stack's own
`nginx`/`certbot` *as well* would be a second, conflicting proxy in front of the same containers.
`docker-compose.coolify.yml` is a small overlay (like `docker-compose.prod.yml`, layered on the
same base `docker-compose.yml`) that un-publishes `postgres`/`redis`/`backend`'s host ports (Coolify
reaches them over the Docker network Coolify itself manages) and builds `frontend` as its static
`prod` bundle with the SPA-fallback fix — `nginx`/`certbot` are excluded simply by never activating
the `gateway` Compose profile they're gated behind, not by deleting anything.

## Prerequisites

- A Hostinger VPS (or any VPS — nothing below is Hostinger-specific beyond "any VPS with a public
  IP and root SSH access"; Hostinger is this deployment's chosen provider). Same minimum sizing as
  `vps-deployment.md`: 2 vCPU / 4 GB RAM / 40 GB disk.
- A domain name, with the ability to create `A` records — plan on **two** subdomains (e.g.
  `app.yourdomain.example` for the frontend, `api.yourdomain.example` for the backend). Coolify's
  per-service domain assignment is one FQDN per service; a single shared domain with path-based
  routing (`/api` vs `/`) would need hand-written Traefik labels this guide does not attempt, since
  it can't be verified against a live instance here — the two-subdomain shape is the
  Coolify-native, UI-driven path the approved design chose.
- This repository, reachable by Coolify either as a public/private Git remote it can clone
  (Coolify's own "Docker Compose" resource type deploys straight from a repo) or pushed to
  manually.

## Step 1 — Install Coolify on the VPS

Per Coolify's own published install instructions (coolify.io/docs) — a single script that
provisions Docker (if not already present) and Coolify's own containers:

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

Once it finishes, Coolify's own dashboard is reachable at `http://<vps-ip>:8000` — create the
admin account on first visit. From here on, most steps happen through Coolify's UI, not SSH.

**Firewall**: same posture as `vps-deployment.md`'s Step 2 (SSH/80/443 only from the public
internet) — Coolify's installer opens what it needs for its own dashboard/proxy; consult Coolify's
own firewall guidance if you lock the VPS down with `ufw` before installing it, since Coolify's
dashboard port (8000) and its Traefik ports (80/443) both need to stay reachable for the flow
below.

## Step 2 — Create the Docker Compose resource

In Coolify's dashboard: New Resource → Docker Compose (or "Docker Compose Empty," per Coolify's
own naming — consult its current UI, this may have changed since this guide was written) → point
it at this repository and the two compose files together:

```
docker/docker-compose.yml
docker/docker-compose.coolify.yml
```

(Exact mechanism for supplying two `-f` files to a single Coolify resource — a combined file, or
Coolify's own multi-file support — depends on the Coolify version; consult its current docs. If
Coolify's version in use only accepts one file, concatenate `docker-compose.yml` +
`docker-compose.coolify.yml` into a single file for this deployment rather than editing either
tracked file in place.)

## Step 3 — Environment variables

Coolify's per-resource "Environment Variables" UI is where every value `docker/.env.example`
documents goes — **never** a committed `.env` file for this path. Set at minimum:

| Variable | What to set it to |
|---|---|
| `COMPOSE_PROFILES` | Leave **unset** (or explicitly empty) — this is what keeps `nginx`/`certbot` from starting alongside Coolify's own Traefik. Do not copy `docker/.env.example`'s own `COMPOSE_PROFILES=gateway` default into Coolify. |
| `POSTGRES_PASSWORD`, `RAAD_AUTH__JWT_SECRET_KEY`, `REDIS_PASSWORD` | Real, generated values — identical guidance to `vps-deployment.md`'s Step 4 table. |
| `RAAD_ENVIRONMENT` | `prod`. |
| `RAAD_CORS__ALLOWED_ORIGINS` | `["https://app.yourdomain.example"]` — the frontend's own domain from Step 4 below. Load-bearing here specifically (unlike the nginx path, where frontend/backend share one origin through the gateway): with two Coolify-assigned subdomains, the browser's requests from the frontend's origin to the backend's origin are genuinely cross-origin. |
| `VITE_API_BASE_URL` | `https://api.yourdomain.example/api/v1`. |
| `VITE_WS_BASE_URL` | `wss://api.yourdomain.example`. |
| `VITE_MAPBOX_ACCESS_TOKEN` | As in `vps-deployment.md`, if live tracking is in this deployment's launch scope. |
| `VITE_STRIPE_PUBLISHABLE_KEY` | Stripe's own *publishable* key (`https://dashboard.stripe.com/apikeys`) — safe to set here, unlike the next row. |
| `RAAD_PAYMENT__PROVIDER` | `stripe`, once you're ready to accept real payments (ADR-0022) — leave unset until then; `POST /billing/payments` fails loudly with no bound provider rather than faking a charge, so there's no harm in deploying with this unset first and setting it later. |
| `RAAD_PAYMENT__PROVIDER_CREDENTIALS` | `{"secret_key":"sk_live_...","webhook_secret":"whsec_..."}` — Stripe's real *secret* key and webhook signing secret. Composition-root/env-var only (ADR-0022) — this is exactly the kind of value that must live in Coolify's own environment-variable store, never in a committed file or in `SystemSetting` (`org_admin` holds `admin.settings.read`/`.update` too). |
| `BACKUP_RCLONE_REMOTE` | As in `vps-deployment.md`, if an off-site backup destination is already provisioned. |

## Step 4 — Assign domains

In Coolify's per-service configuration (reachable from the resource's own service list once the
compose file is parsed): assign `app.yourdomain.example` to the `frontend` service (port 80) and
`api.yourdomain.example` to the `backend` service (port 8000). Coolify issues/renews TLS for both
automatically once DNS resolves — no `certbot`/`prod-tls.conf` step to run yourself, unlike the
`vps-deployment.md` path.

## Step 5 — Deploy and verify

Trigger a deploy from Coolify's UI (or `git push` if Coolify's own auto-deploy webhook is
configured). Once containers report healthy:

```bash
curl -s https://api.yourdomain.example/health/ready | python3 -m json.tool
```

Same expected shape as `vps-deployment.md`'s Step 5:
`{"status":"ready","checks":{"database":"ok","redis":"ok","broker":"ok"}}`.

## Step 6 — Bootstrap the Founder account

Identical command to `vps-deployment.md`'s Step 6/`docker/README.md`'s "First login" section, run
against the `backend` container — Coolify's dashboard has its own "Execute Command" / terminal
feature per-service that reaches the same container `docker compose exec` would:

```bash
docker compose exec \
  -e RAAD_BOOTSTRAP_FOUNDER_EMAIL="founder@yourorg.example" \
  -e RAAD_BOOTSTRAP_FOUNDER_PASSWORD="<a strong password of your own choosing>" \
  backend python -m raad.interfaces.cli.bootstrap_founder --full-name "Your Name"
```

(Full guide: `docs/runbooks/founder-bootstrap.md`.)

## Step 7 — Confirm the platform is actually usable end to end

- `https://app.yourdomain.example` loads the login page; log in with the Founder credentials from
  Step 6.
- Open the browser's network tab and confirm `/ws/tracking`/`/ws/notifications` actually upgrade to
  a WebSocket connection against `wss://api.yourdomain.example` — Traefik passes `Upgrade`/
  `Connection` headers through by default for HTTP routers, per Coolify/Traefik's own
  documentation, but this specific behavior has not been independently exercised against a live
  Coolify instance in this environment; verify it for real on first deploy.
- `/org/billing` → confirm the "Online payment is not available yet" state renders honestly if
  `RAAD_PAYMENT__PROVIDER` is still unset, or that a real test-mode card completes a payment if
  you've already set Stripe test credentials (`https://dashboard.stripe.com/test/apikeys`, test
  card `4242 4242 4242 4242`) before switching to live keys.
- Run through `vps-deployment.md`'s own Step 8 checklist (Redis persistence, `/metrics`, a real
  backup/restore drill) — none of that is Coolify-specific, it applies identically here.

## What this guide deliberately doesn't cover

- **Single-domain, path-based routing** (`yourdomain.example/` for the frontend and
  `yourdomain.example/api` for the backend, avoiding the two-subdomain CORS requirement above) —
  possible with hand-written Traefik labels Coolify would respect, but not attempted here: writing
  label syntax that has never been checked against a live Traefik/Coolify instance would be exactly
  the kind of guessed-not-verified implementation this codebase's own architecture work
  (ADR-0009/0010's LSZ protocol adapters, for one) explicitly avoids. The two-subdomain shape above
  is the Coolify-native path its own UI is built around.
- **Migrating an existing `docker-compose.prod.yml` deployment to Coolify in place** — this guide
  assumes a fresh deployment. Moving a live deployment (data, DNS, TLS) between the two paths is a
  cutover with its own risks (a brief DNS-propagation window where old and new certificates/proxies
  could both be live) not addressed here.
- Everything `vps-deployment.md`'s own "What this guide deliberately doesn't cover" section already
  states (infrastructure-as-code, CI/CD-driven deploys beyond Coolify's own git-push flow,
  multi-instance/HA) — identically out of scope here.
