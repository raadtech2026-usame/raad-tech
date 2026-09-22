# ADR-0045: Build container images in CI and deploy pre-built images from GHCR

- **Status:** Accepted
- **Date:** 2026-09-22
- **Amends:** ADR-0022 (Payment Provider Architecture — the Coolify deployment decision in its
  §"Deployment — a Coolify overlay"). ADR-0022's choice of Coolify-on-Hostinger is unchanged;
  only *where the image is built* changes.
- **Supersedes:** nothing. No prior ADR describes the build pipeline.

## Context

Hostinger sent an "Action required: Your VPS has exceeded its CPU limit" warning for
`srv1962912.hstgr.cloud` on 2026-09-22. A read-only audit of the VPS established the following,
with evidence rather than inference:

- The VPS is **4 vCPU / 16 GB**, and is **94.83% idle averaged over 15 days** (`/proc/stat`
  since boot: 26,955,577 busy jiffies of 521,734,489). Today's average was 6.26% busy.
- `sar` retains 10 days of 10-minute samples. The **highest 10-minute average in that whole
  window is 21.6%**. Baseline is ~6.3%.
- Today's only elevated sample was `16:10:03` at **17.60% busy with a 1-minute load average of
  5.41 on 4 CPUs** — genuine saturation, more runnable tasks than cores.
- Coolify's own `application_deployment_queues` table shows a deployment at **16:08:29–16:11:04
  (155 s)**. **Every CPU peak across all ten retained days correlates 1:1 with a deployment
  record.** There is no unexplained peak anywhere in the data.
- Reconstructing CPU-seconds for that window: ~263 CPU-seconds of excess over 94 s of build =
  **~2.8 of 4 cores, ~70% of the box**, with instantaneous peaks necessarily higher.
- Steal time is 0.43%, so the hypervisor is **not** throttling the guest.
- No malware, no runaway process, no restart loop, no OOM, zero container restarts.

The cause is therefore not load, growth, or compromise. It is that Coolify's `dockercompose`
build pack runs `docker compose build` **on the production VPS**, and a Docker build saturates
every available core for as long as it runs.

Two further facts shaped the design, both read from Coolify 4.3.21's own
`app/Jobs/ApplicationDeploymentJob.php` on the server rather than assumed:

1. The deployment job **already** runs `docker compose ... pull --ignore-buildable` (line 924)
   followed by `up --pull always --build -d` (line 4242). `--ignore-buildable` pulls exactly
   those services that have no `build:` section.
2. The same compose file **already** deploys four image-only services this way
   (`postgres:16-alpine`, `redis:7-alpine`, `prom/prometheus:v2.53.0`, `nginx:1.27-alpine`).

So deploying pre-built images requires **no new Coolify capability** — only the removal of the
`build:` sections.

## Decision

### 1. GitHub Actions builds the images; the VPS only pulls

`.github/workflows/publish-images.yml` builds and pushes on every push to `main`. The VPS never
runs `docker build` again.

### 2. Five images, not seven services

`backend`, `migrate` and `worker` are the same image built from the same context and Dockerfile,
differing only in the `command:` their compose service supplies. Coolify was building that
identical image **three times per deploy**. They now share one `raad-backend` image.

| Image | Context | Dockerfile | Notes |
|---|---|---|---|
| `raad-backend` | `backend` | `docker/backend.Dockerfile` | used by backend, migrate, worker |
| `raad-frontend` | `frontend` | `docker/frontend.Dockerfile` | `target: prod`; 4 `VITE_*` build args |
| `raad-device-gateway` | `services/device-gateway` | `docker/device-gateway.Dockerfile` | |
| `raad-jt1078-relay` | `services/jt1078` | `docker/jt1078-relay.Dockerfile` | 842 MB — apt-installs ffmpeg |
| `raad-backup` | `.` | `docker/backup.Dockerfile` | root context; see §6 |

### 3. GHCR, with public packages

**Registry: GHCR.** Decisive reason, not preference: **Coolify 4.3.21 has no registry-credential
store** — there is no such table, and its source's only mechanism is a manual server-side
`docker login` (the error string at line 2308 says exactly that). `/root/.docker/config.json`
does not exist on the VPS. A private registry would therefore mean a long-lived PAT on the
production host that Coolify cannot rotate, whose expiry breaks a deploy months later. Public
packages remove that failure mode entirely: **the VPS needs no registry credential at all.**

**Packages are public, and this discloses nothing new.** Verified rather than assumed:

- The repository is already **public** (`gh repo view` → `"visibility":"PUBLIC"`), so the source
  in these images is already public.
- The only credential baked into any image is the frontend's `VITE_MAPBOX_ACCESS_TOKEN`. It was
  confirmed to be a **Mapbox public token** (prefix `pk.`, 94 chars — `sk.` would be a secret
  token), and it is **already served to every anonymous visitor** in the deployed bundle at
  `https://app.raadsystems.tech/assets/index-*.js`.
- `VITE_STRIPE_PUBLISHABLE_KEY` is **empty** (length 0) and appears nowhere in the bundle.
- No backend secret is in any image: all five Dockerfiles copy source and install dependencies;
  every runtime secret is injected by Coolify as an environment variable at run time.

**Residual item, flagged not resolved:** whether that Mapbox `pk.` token has URL restrictions
configured in the Mapbox account cannot be checked from the repository or the VPS. That risk is
unchanged by this ADR — the token is already public either way — but it is worth confirming.

### 4. Immutable full-SHA tags, resolved by Coolify itself

Production references `ghcr.io/raadtech2026-usame/raad-<svc>:${SOURCE_COMMIT}` — the **full
40-character** commit SHA.

The keystone: Coolify writes `SOURCE_COMMIT` into the `.env` file it passes to
`docker compose pull`/`up` (verified present in
`/data/coolify/applications/<uuid>/.env`, and on the running containers as
`SOURCE_COMMIT=93ded1be21d21a475efbc7232220f0e034bf00c1`). So the tag **always equals the commit
being deployed**, with no tag plumbing, no per-deploy variable to update, and no way for the
running stack to reference an image built from different source than the checkout.

The short SHA would not work: `SOURCE_COMMIT` is the full 40 characters. `${{ github.sha }}` in
Actions is likewise full-length.

**No `:-` fallback on that variable, deliberately.** An empty value yields an invalid image
reference, which fails at `pull` — *before* `up` touches a running container. A fallback to a
mutable tag such as `main` would instead silently deploy the wrong code. A `main` tag is
published for human convenience and is never referenced by the production compose file.

### 5. Compose expresses this via `build: !reset null`

Compose has no other way to delete an inherited mapping, and any surviving fragment of a `build:`
block would make the service "buildable" again — precisely what `pull --ignore-buildable` skips.
The merge was validated locally with `docker compose config`: all seven build sections are
removed and seven `image:` lines emitted.

`scripts/regenerate-coolify-compose.sh` performs the whole regeneration (merge → re-prepend
header → re-apply both patches) and **fails loudly if any `build:` section survives**, so the
CPU regression this ADR removes cannot be silently reintroduced.

**One previously-required patch is now obsolete.** The generated file used to rewrite every
`build.context` to be repository-root-relative, working around confirmed upstream Coolify bug
`coollabsio/coolify#5182`. With no build contexts left, that patch — and the documented coupling
risk of having to undo it if #5182 were ever fixed — is gone.

### 6. Adjacent defects fixed in the same change

Each was found by the audit, and each is deployment-related rather than an unrelated improvement.

- **Healthcheck cadence.** Measured **~86 `docker exec`s/minute** across the box (~124,000/day),
  of which this stack contributed ~50/min. Moved to `interval: 30s` with `start_interval: 2s`,
  so `depends_on: condition: service_healthy` still releases dependents promptly (Docker 29.8.0
  on the VPS supports `start_interval`). The Python probes are **kept deliberately**:
  `python:3.11-slim` ships no `curl`, `wget` or `nc` — verified by `command -v` inside each
  running container — so a shell probe would mean adding a package to every image, which works
  against the goal.
- **device-gateway healthcheck log noise.** Its probe dialled `localhost:7809` every 10 s and
  emitted `connection_accepted` + `connection_closing` + `connection_closed` each time:
  ~26,000 lines/day that buried real device events while JT/T 808 behaviour is under active
  investigation. Those three are now logged at DEBUG **only when the peer is loopback**. This is
  sound rather than heuristic: a terminal reaches the process through Docker's published port and
  can never present `127.0.0.1`. An unclassifiable peer defaults to INFO, so the fix cannot
  silence what it failed to identify. (Note `7809` is the dormant LSZ adapter; real MDVRs use
  `7808`.)
- **Build context.** `raad-backup` shipped **168 MB** of repository-root context (backend/ 103 MB,
  `.git` 42 MB) to add three 16 KB shell scripts. A root `.dockerignore` reduces it to `scripts/`
  (24 KB), written as an allowlist so it cannot silently regrow. `services/jt1078` gained the
  `.dockerignore` it was missing.

### 7. Deployment trigger

Coolify's Git auto-deploy is disabled and GitHub Actions becomes the sole trigger, gated on
`needs: build` so a partially-built commit is structurally undeployable. Until then the workflow
publishes images and deployment stays a manual action, controlled by the repository variable
`COOLIFY_DEPLOY_ENABLED`.

The API call uses a **`deploy`-ability-only** Coolify token. The two existing tokens are
over-privileged for this purpose — one is `["root"]`, the other
`["deploy","read","read:sensitive","write"]`, and `read:sensitive` can read environment-variable
values. Coolify's own UI treats `deploy` as exclusive (`$this->permissions = ['deploy']`), and
`/api/v1/deploy` requires only `api.ability:deploy`.

Coolify is reachable at `https://coolify.raadsystems.tech`, so a GitHub-hosted runner can reach
it over 443. This matters because port 8000 is **not** publicly reachable (below).

## Consequences

**Good**

- The deploy-time CPU spike leaves the VPS entirely; the only remaining work is a pull plus
  container recreation.
- Rollback improves: redeploying an older commit now *pulls that commit's image* instead of
  rebuilding it, so it is both faster and genuinely reproducible.
- A malicious dependency executes `pip install`/`npm ci` on a disposable runner rather than
  beside the production database.
- Builds are parallel across five runners instead of serial on 4 shared vCPUs, and `raad-backend`
  is built once instead of three times.
- Cost is **zero**: public repositories get free standard-runner Actions minutes, and public GHCR
  packages are free to store and pull.

**Costs and risks**

- A deploy now depends on GHCR being reachable. If GHCR is down, the running containers keep
  running and the deploy simply waits; previously the VPS could build offline.
- **GHCR retention becomes a rollback dependency.** Do not add an aggressive retention policy —
  old SHA tags are what rollback pulls. Keep ≥30 days / ≥20 versions.
- Total lead time from push to production rises by the CI build (~2–4 min cold, under a minute
  warm), while VPS impact drops sharply.
- `start_interval` requires Docker Engine ≥ 25 wherever this compose file is run.

**Explicitly not changed:** no runtime behaviour, no port, no volume, no network, no environment
variable, no protocol handling, no JT808/JT1078 logic beyond the log *level* above, and no
database or Redis configuration.

## Things this ADR deliberately does not do

- **Redis credential rotation.** The deployed stack's Redis password is the compose default
  placeholder, visible in the container healthcheck config. Rotating it requires coordinating
  backend, worker, device-gateway, jt1078-relay and the healthcheck simultaneously, and is a
  separate change with its own plan (`docs/runbooks/ghcr-deployment.md` §"Deferred"). Redis is
  not published to the host and is reachable only on the Docker network.
- **Firewall changes.** Ports 8000 (Coolify) and 8080 (Traefik dashboard) are bound to `0.0.0.0`
  with `ufw` inactive, but were confirmed **filtered upstream** — 443/7808/7910 connect from the
  internet while 8000/8080/6001/6002 time out. The exposure is already mitigated by Hostinger's
  cloud firewall, and a host-level rule was judged not worth the lockout risk.
- **Database polling.** The audit's "~90 transactions/second" figure was **wrong** and is
  retracted here: `pg_stat_database` counters are not reset by a container restart and the data
  volume persists, so the correct window is the database's lifetime, not the container's uptime.
  `stats_reset` is NULL and the true rate is **~1.4 txn/s**, consistent with the configured worker
  poll intervals. There is no polling defect and no change was made.
