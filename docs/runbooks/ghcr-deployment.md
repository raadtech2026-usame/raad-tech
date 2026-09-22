# Runbook — Deploying RAAD from pre-built GHCR images

**Applies to:** the Coolify production stack on `srv1962912.hstgr.cloud` (187.7.22.79).
**Design record:** `docs/architecture/adr/0045-ci-image-build-and-registry-deployment.md`.
**Companion:** `docs/runbooks/coolify-deployment.md` (first-time Coolify resource setup, domains,
device-plane DNS/firewall). This runbook covers only the build/publish/deploy loop.

---

## 1. Architecture

```
git push origin main
        │
        ▼
GitHub Actions — .github/workflows/publish-images.yml
        │   5 parallel matrix jobs (ubuntu-latest, Buildx, registry cache)
        │   each tagged  :<full-40-char-commit-sha>  and  :main
        ▼
GHCR — ghcr.io/raadtech2026-usame/raad-{backend,frontend,device-gateway,jt1078-relay,backup}
        │   public packages: the VPS needs NO registry credential
        ▼
deploy job — runs only if ALL five builds succeeded (needs: build)
        │   GET https://coolify.raadsystems.tech/api/v1/deploy?uuid=<app-uuid>
        ▼
Coolify 4.3.21
        │   git clone → docker compose build      (no-op: nothing is buildable)
        │             → docker compose pull --ignore-buildable
        │             → docker compose up --pull always -d
        ▼
Production containers on the 4 vCPU VPS — pull only, never build
```

**Why:** building the seven services on the VPS saturated ~70–100% of all 4 cores for 1–2 minutes
per deploy (1-minute load average 5.41), which triggered Hostinger's CPU-limit warning. See
ADR-0045 for the full evidence.

---

## 2. Images

`backend`, `migrate` and `worker` all run **one** image (`raad-backend`); they differ only in
their `command:`.

| Image | Context | Dockerfile | Approx size |
|---|---|---|---|
| `raad-backend` | `backend` | `docker/backend.Dockerfile` | 376 MB |
| `raad-frontend` | `frontend` | `docker/frontend.Dockerfile` (`target: prod`) | 80 MB |
| `raad-device-gateway` | `services/device-gateway` | `docker/device-gateway.Dockerfile` | 215 MB |
| `raad-jt1078-relay` | `services/jt1078` | `docker/jt1078-relay.Dockerfile` | 842 MB (ffmpeg) |
| `raad-backup` | `.` | `docker/backup.Dockerfile` | 568 MB |

---

## 3. Image tagging

Production references **only** the full 40-character commit SHA:

```yaml
image: ghcr.io/raadtech2026-usame/raad-backend:${SOURCE_COMMIT}
```

`SOURCE_COMMIT` is written by **Coolify itself** into the `.env` it passes to compose, so the tag
always equals the commit being deployed. Nothing has to update it.

- It must be the **full** SHA — `SOURCE_COMMIT` is 40 characters, and a 7-character tag will not
  resolve. `${{ github.sha }}` is already full-length.
- There is **no `:-` fallback**, on purpose. An empty value produces an invalid image reference
  that fails at `pull`, *before* `up` touches a running container. A fallback to `main` would
  silently deploy the wrong code.
- The `:main` tag exists for humans. **Never reference it from the compose file.**

---

## 4. Required GitHub configuration

**Variables** (Settings → Secrets and variables → Actions → Variables). Not secret — they are
public URLs compiled into the JS bundle.

| Name | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://api.raadsystems.tech/api/v1` |
| `VITE_WS_BASE_URL` | `wss://api.raadsystems.tech` |
| `COOLIFY_DEPLOY_ENABLED` | `true` to let Actions trigger deploys; unset/absent = manual deploys |

**Secrets** (same page → Secrets).

| Name | Notes |
|---|---|
| `VITE_MAPBOX_ACCESS_TOKEN` | Mapbox **public** (`pk.`) token. Already public in the served bundle; held as a secret so it is masked in logs. |
| `VITE_STRIPE_PUBLISHABLE_KEY` | Currently **unset/empty** in production. Leave unset unless Stripe is configured — an unset secret interpolates to an empty string, matching today. |
| `COOLIFY_URL` | `https://coolify.raadsystems.tech` |
| `COOLIFY_API_TOKEN` | Coolify token with the **`deploy` ability only**. See §5. |
| `COOLIFY_APP_UUID` | `wkhdh0xb83peateermo2s0vd` |

`GITHUB_TOKEN` needs no setup — the workflow requests `packages: write` itself, and the repository
default is `read`.

---

## 5. Creating the Coolify deploy token (least privilege)

Do this in the **Coolify UI**, not the database.

1. Coolify → *Keys & Tokens* → *API tokens* → **Create New Token**
2. Name: `github-actions-deploy-only`
3. Permissions: tick **`deploy` only**. Coolify treats `deploy` as exclusive, which is what you
   want — `/api/v1/deploy` requires only `api.ability:deploy`.
4. Copy the token **once** and paste it straight into the GitHub secret `COOLIFY_API_TOKEN`.

> **Do not reuse the existing tokens.** At the time of writing the instance had
> `raad-production` with `["root"]` and `RAAD Claude Production Deployment` with
> `["deploy","read","read:sensitive","write"]`. `read:sensitive` can read environment-variable
> **values**, i.e. every production secret. Neither belongs in a CI system.

---

## 6. How to deploy

### Normal path (once `COOLIFY_DEPLOY_ENABLED=true`)

Push to `main`. Actions builds all five images, and only if **every** build succeeds does it call
the Coolify deploy API. Watch it with:

```bash
gh run watch                                    # the build
gh run list --workflow=publish-images.yml       # history
```

### Manual path (the default until you opt in)

1. Push to `main`; wait for **Publish Images** to go green.
2. Confirm the five tags exist:
   ```bash
   SHA=$(git rev-parse origin/main)
   for i in backend frontend device-gateway jt1078-relay backup; do
     docker manifest inspect ghcr.io/raadtech2026-usame/raad-$i:$SHA >/dev/null \
       && echo "OK   raad-$i" || echo "MISSING raad-$i"
   done
   ```
3. Coolify → the `raad-tech:main` application → **Deploy**.

**A missing tag is a safe failure.** `pull` runs before `up`, so the deploy aborts with
`manifest unknown` and the running containers are never touched.

---

## 7. Post-deployment verification

Run in this order; later checks depend on earlier ones.

| # | Check | Command / expectation |
|---|---|---|
| 1 | Images are pulled, not built | `docker inspect -f '{{.Config.Image}}' <container>` → starts with `ghcr.io/` |
| 2 | Commit matches | `docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' <c> \| grep SOURCE_COMMIT` equals the deployed SHA |
| 3 | Container health | `docker ps` → all `(healthy)`; `migrate` `Exited (0)` |
| 4 | Postgres / Redis | `healthy`; data volumes unchanged (`wkhdh0xb83peateermo2s0vd_raad-postgres-data`) |
| 5 | Backend | `curl -s https://api.raadsystems.tech/api/v1/health/ready` |
| 6 | Frontend | `curl -sI https://app.raadsystems.tech` → `200` |
| 7 | WebSocket | `/ws/tracking`, `/ws/notifications` connect |
| 8 | JT808 | port 7808 reachable; wait for the real MDVR to register — **do not fabricate device traffic** |
| 9 | JT1078 | `video.raadsystems.tech` reachable; a real `POST /video/live` produces `0x9101` and a WS-FLV viewer |
| 10 | CPU | `uptime` during deploy — load should stay near 1, not 5+ |

---

## 8. Rollback

Rollback is **code and image together**, because they share one identifier.

```
Coolify → application → Deployments → pick the previous successful deployment → Redeploy
```

Coolify checks out that commit, so `SOURCE_COMMIT` becomes that SHA and compose pulls **that
commit's images**. Equivalently, pin `git_commit_sha` to the older full SHA and deploy, then set
it back to `HEAD` afterwards.

**Three things that would silently break rollback:**

1. **GHCR retention.** Old SHA tags are what rollback pulls. Keep ≥30 days / ≥20 versions. Do not
   add an aggressive cleanup policy.
2. `/etc/cron.d/docker-image-prune` runs `docker image prune -af --filter until=24h` daily, so
   rollback depends on re-pulling from GHCR — it is never an offline operation.
3. **Rollback does not revert database migrations.** If the bad commit ran an irreversible
   Alembic migration, rolling the image back does not roll the schema back. See
   `docs/runbooks/rollback.md`.

**Known-good anchor at cutover:** `93ded1be21d21a475efbc7232220f0e034bf00c1` — the last commit
deployed by the old on-VPS build path. Its images were built on the VPS and are **not** in GHCR,
so rolling back *to it* means restoring `build:` sections, not pulling. The first GHCR-built
commit is the first true rollback target for the new scheme.

---

## 9. Regenerating the compose file

`docker/docker-compose.coolify.full.yml` is **generated**. Never hand-edit it.

```bash
./scripts/regenerate-coolify-compose.sh
git diff -- docker/docker-compose.coolify.full.yml
```

The script merges `docker-compose.yml` + `docker-compose.coolify.yml`, re-prepends the header
(`docker compose config` strips comments), re-applies both post-generation patches, and **fails if
any `build:` section survives** — the guard that stops the CPU regression being reintroduced.

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `manifest unknown` / `not found` at pull | Images for that SHA were never built, or the workflow failed | Check `gh run list`; re-run the workflow. Production is untouched. |
| Image tag ends in `:` | `SOURCE_COMMIT` empty | Deliberate hard failure. Check Coolify resolved the commit; never add a `:-` fallback. |
| `denied` / `unauthorized` at pull | A GHCR package is still **private** | Package → Settings → Change visibility → Public. (GHCR packages default to private even for public repos.) |
| Coolify builds instead of pulling | A `build:` section came back | Re-run the regeneration script; it fails loudly on this. |
| Map missing but app loads | `VITE_MAPBOX_ACCESS_TOKEN` not set in **GitHub** | It moved from Coolify's env store to GitHub. Set the secret and rebuild. |
| Deploy job fails to reach Coolify | Port 8000 is filtered upstream | Use `https://coolify.raadsystems.tech` (443), not `:8000`. |
| Container `unhealthy` right after deploy | Probe cadence | Steady-state interval is 30 s but `start_interval` is 2 s during `start_period`; needs Docker ≥ 25. |

---

## 11. Security notes

- The VPS holds **no registry credential**. Public GHCR packages are what make that possible.
- Nothing secret is in any image. All five Dockerfiles copy source and install dependencies;
  every runtime secret arrives as a Coolify environment variable. **Never add a non-public value
  as a build arg** — a build arg is baked into the image layer permanently and cannot be redacted.
- The workflow runs on `push: [main]` and `workflow_dispatch` only, **never** `pull_request`. On a
  public repository a fork PR must not reach `packages: write` or the build-arg secrets.
- `COOLIFY_API_TOKEN` is passed to `curl` via an environment variable, never on the command line,
  and the response is filtered to named fields rather than echoed.
- The deploy token carries the **`deploy` ability only** — it cannot read environment-variable
  values, unlike the pre-existing `root` and `read:sensitive` tokens.

---

## 12. Deferred — not done by ADR-0045

| Item | Status |
|---|---|
| **Redis credential rotation** | The stack runs with the compose default placeholder password, visible in the container healthcheck config. Rotation must update backend, worker, device-gateway, jt1078-relay and the healthcheck **simultaneously** — a single Coolify env change plus one redeploy does this atomically, since every consumer reads `REDIS_PASSWORD` from the same store and all containers are recreated together. Redis has no published host port and is reachable only on the Docker network, which bounds the exposure. Do it as its own change, with a verification pass. |
| **Firewall for 8000/8080** | Not changed. Both are bound to `0.0.0.0` with `ufw` inactive, but verified **filtered upstream** by Hostinger: 443/7808/7910 connect from the internet, 8000/8080/6001/6002 time out. Already mitigated; a host rule was judged not worth the lockout risk. Re-check if the Hostinger firewall is ever altered. |
| **SSH password authentication** | `PasswordAuthentication yes` wins via `/etc/ssh/sshd_config.d/50-cloud-init.conf` (first match wins, ahead of `60-cloudimg-settings.conf`). Key-only auth would be an improvement; not changed here because a mistake locks everyone out. |
| **Branch protection on `main`** | Not enabled, so as not to block this cutover. Enable once the pipeline is proven — require the **Publish Images** check, which prevents merging a commit whose images cannot build. |
| **Database polling** | **No defect.** The audit's "~90 txn/s" was wrong: `pg_stat_database` is not reset by a container restart and the data volume persists, so the window was the database's lifetime, not the container's uptime. `stats_reset` is NULL; the true rate is ~1.4 txn/s, matching the configured worker intervals. No change made. |
