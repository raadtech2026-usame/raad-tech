# Runbook: VPS deployment (fresh server, start to finish)

Priority 1 Item 7 (`PROJECT_STATUS.md`). Everything downstream of "you have a fresh Linux VPS
and a domain" — the part `docker/README.md` didn't cover (it documents *running* the stack, once
Docker and the repo already exist on a machine; this is provisioning that machine in the first
place). Doesn't repeat what already has its own runbook — `docs/runbooks/tls-setup.md`,
`redis-operations.md`, `backup-and-restore.md`, `founder-bootstrap.md` are each linked at the
point they're needed, not duplicated here.

## Prerequisites

- A VPS running a recent Ubuntu/Debian LTS (this guide assumes Ubuntu 22.04+; adjust package
  manager commands for another distro). Minimum sizing for a pilot: 2 vCPU / 4 GB RAM / 40 GB
  disk — Postgres, Redis, the backend, worker, device-gateway, nginx, and prometheus all run on
  one box at MVP scale (`.claude/rules/architecture.md` #7: no premature microservices).
- Root or sudo SSH access.
- A domain name, with the ability to create an `A` record pointing at the VPS's public IP
  (required before Step 6/TLS — not required to bring the stack up on plain HTTP first).
- This repository, either cloned directly on the VPS or deployed via your own CI/CD pushing to
  it — this guide assumes a direct `git clone`, the simplest path for a first pilot deployment.

## Step 1 — OS baseline

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ufw fail2ban git
```

`fail2ban` isn't wired to anything RAAD-specific — it's generic SSH brute-force protection,
independent of this platform's own application-level login rate limiting (Priority 1 Item 3,
`docs/runbooks` has no separate entry for it since it's standard VPS hygiene, not this codebase's
own concern).

## Step 2 — Firewall

Only SSH, HTTP, and HTTPS are ever meant to be reachable from the public internet — every other
service (`postgres`, `redis`, `backend`, `prometheus`, etc.) stays internal to the Docker network,
enforced by `docker-compose.prod.yml`'s own `ports: !reset []` overrides (nothing new to configure
there; this step is the network-level backstop in front of it):

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Confirm: `sudo ufw status verbose` should list exactly OpenSSH/80/443 as allowed, everything else
implicitly denied. Do **not** open 5432 (Postgres), 6379 (Redis), 8000 (backend), 7808/7809
(device-gateway), or 9090 (Prometheus, if you ever add a `ports:` mapping for local debugging per
`monitoring.md`) — none of these are meant to be reachable from outside the VPS, ever, in this
topology.

## Step 3 — Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

Log out and back in (or `newgrp docker`) for the group change to take effect. Docker's own
installer already enables and starts the daemon, including on boot — no separate systemd unit is
needed; every service in `docker-compose.yml` already carries `restart: unless-stopped`, so a
host reboot brings the whole stack back automatically once Docker itself is running again.

Verify: `docker run hello-world` and `docker compose version` (Compose V2, bundled with the
Docker installer above — this repo's own compose files use no V1-only syntax).

## Step 4 — Clone and configure

```bash
git clone <your-repository-url> raad
cd raad
cp docker/.env.example docker/.env
```

Edit `docker/.env` — **every value that matters for a real deployment, one place**:

| Variable | What to set it to |
|---|---|
| `POSTGRES_PASSWORD` | A real, generated password — never the `raad`/`raad` dev default. |
| `RAAD_AUTH__JWT_SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` — `Settings.validate_on_startup()` refuses to boot with `RAAD_ENVIRONMENT=prod` and this unset, so this one is enforced, not just advisory. |
| `REDIS_PASSWORD` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` — see `docs/runbooks/redis-operations.md`. |
| `RAAD_ENVIRONMENT` | `prod` — gates the JWT-secret check above and any other environment-specific behavior. |
| `RAAD_CORS__ALLOWED_ORIGINS` | `["https://your-real-domain.example"]` — must match whatever origin the browser actually loads the frontend from. |
| `DOMAIN_NAME`, `TLS_EMAIL` | Your real domain/contact email — needed for Step 6, harmless to set now. |
| `BACKUP_RCLONE_REMOTE` | Leave empty for now if no off-site destination is provisioned yet (`docs/runbooks/backup-and-restore.md`'s "Configuring off-site storage") — the backup service runs local-only with a loud warning until you do. |
| `VITE_MAPBOX_ACCESS_TOKEN` | A real token from `https://account.mapbox.com/` if live-tracking maps are part of this deployment's launch scope. |

Never commit this file — `docker/.env` is gitignored (`.gitignore`'s existing `.env`/`.env.*`
rule).

## Step 5 — First boot (plain HTTP)

Bring the stack up **without** TLS first — `docker-compose.prod.yml`'s default
(`NGINX_PROD_CONF=prod.conf`) stays plain HTTP until you deliberately opt in, precisely so this
step always succeeds regardless of DNS/certificate state:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d --build
docker compose -f docker/docker-compose.yml ps
```

Every service should show `healthy` (or `running` for the ones with no healthcheck, like
`migrate`, which exits 0 once done and stays stopped — that's correct, not a failure). If
anything is `unhealthy`, check its logs before proceeding:

```bash
docker compose -f docker/docker-compose.yml logs <service> --tail 100
```

**Verify the real dependency health check** (Priority 1 Item 5) — this is the single most useful
first signal that the whole stack is actually wired together correctly, not just that individual
containers started:

```bash
curl -s http://localhost/health/ready | python3 -m json.tool
```

Expect `{"status": "ready", "checks": {"database": "ok", "redis": "ok", "broker": "ok"}}`. If
`redis`/`broker` show `"down"` here (the exact response this sandbox itself has produced all
through this Priority 1 program, since no Redis is reachable in the *development* sandbox) but
you've genuinely brought up the `redis` service, check `docker compose logs redis` and confirm
`REDIS_PASSWORD` matches between the `redis` service and `RAAD_REDIS__URL`/`RAAD_BROKER__URL`
(`docker-compose.yml`'s own `${REDIS_PASSWORD}` substitution handles this automatically as long
as `docker/.env` has one value, not two different ones typed in different places).

## Step 6 — Bootstrap the Founder account

`users` starts genuinely empty by design — see `docker/README.md`'s own "First login" section for
the full reasoning. Run once:

```bash
docker compose -f docker/docker-compose.yml exec \
  -e RAAD_BOOTSTRAP_FOUNDER_EMAIL="founder@yourorg.example" \
  -e RAAD_BOOTSTRAP_FOUNDER_PASSWORD="<a strong password of your own choosing>" \
  backend python -m raad.interfaces.cli.bootstrap_founder --full-name "Your Name"
```

(Full guide, including recovering a locked-out Founder: `docs/runbooks/founder-bootstrap.md` /
`founder-password-recovery.md`.)

## Step 7 — DNS and TLS

Point your domain's `A` record at the VPS's public IP now, if you haven't already — propagation
can take anywhere from minutes to a couple of hours. Once it resolves (`dig +short
your-domain.example` returns the VPS IP), follow `docs/runbooks/tls-setup.md`'s two-phase
bootstrap in full: it gets a real Let's Encrypt certificate (staging first, then production) and
switches `NGINX_PROD_CONF` to `prod-tls.conf`. Auto-renewal is then fully automatic (`certbot`
service, no further manual steps).

## Step 8 — Confirm the platform is actually usable end to end

- `https://your-domain.example/health/ready` → `{"status":"ready", ...}` (now over HTTPS).
- Log into the web dashboard with the Founder credentials from Step 6.
- `docs/runbooks/redis-operations.md`'s "First real verification" section — confirm `--requirepass`
  is actually enforced and persistence survives a container restart.
- `docs/runbooks/monitoring.md` — confirm `/metrics` returns real data and, if you're running
  Prometheus somewhere that scrapes it, that the `raad-backend` target shows `UP`.
- Run a manual backup and a restore drill once for real (`docs/runbooks/backup-and-restore.md`)
  before this deployment is holding any data you'd actually miss.

## What this guide deliberately doesn't cover

- **Infrastructure-as-code** (Terraform/Ansible/CloudFormation) — this is a manual, one-VPS
  runbook by design, matching this platform's actual current scale
  (`.claude/rules/architecture.md` #7). `infrastructure/deployment/k8s/` remains the documented,
  not-yet-built scale-out target.
- **CI/CD-driven deploys** — `.github/workflows/backend-pipeline.yml` is test-only today (no
  deploy step); this guide assumes a manual `git pull && docker compose up -d --build` on the VPS
  itself, or your own separately-built deploy automation pushing to it.
- **Multi-instance/HA** — one VPS, one instance of every service. `interfaces/http/realtime.
  ConnectionManager` and `core.workers.idempotency.InMemoryIdempotencyStore` are both explicitly
  flagged elsewhere in this codebase as needing a shared (Redis-backed) implementation before
  they'd be correct across more than one API process.
