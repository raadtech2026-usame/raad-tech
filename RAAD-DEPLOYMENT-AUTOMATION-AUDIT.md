# RAAD-TECH — SOURCE_COMMIT & DEPLOYMENT AUTOMATION DEEP AUDIT

**Target System:** RAAD-TECH Production School Bus Tracking Platform  
**Environment:** Hostinger VPS `srv2082072` (`72.62.7.212`), Coolify v4.6.0  
**Application Resource:** `m0lhtrori7rbplpzwzilohfz` (`raad-tech:main-e1x27rlmxndnxknajzbamdrh`)  
**Repository:** `raadtech2026-usame/raad-tech` (`main`)  
**Audit Timestamp:** 2026-11-05 16:30:00 UTC+3  
**Status:** COMPLETE (READ-ONLY INVESTIGATION)  

---

## 1. Executive Summary

A comprehensive read-only architectural investigation was conducted across the RAAD-TECH GitHub repository, GitHub Actions workflows, Coolify v4.6.0 source code and database, and the Hostinger production VPS (`72.62.7.212`).

### Core Conclusion: `SOURCE_COMMIT` Does NOT Need to Be Manually Updated
**VERIFIED FACT:** Manual updates to `SOURCE_COMMIT` are **not only unnecessary**, but the manual existence of `SOURCE_COMMIT` in Coolify’s Environment Variables table is the **primary root cause of the previous production deployment failure and stale commit freeze.**

Coolify v4.6.0 natively contains logic (`/var/www/html/app/Jobs/ApplicationDeploymentJob.php`, lines 4324–4333) designed to automatically inject the 40-character Git commit SHA (`$this->commit`) into `.env` as `SOURCE_COMMIT` for every deployment. However, Coolify's code only injects this dynamic value if `SOURCE_COMMIT` is **NOT** defined in the application's environment variables table. 

Because static records for `SOURCE_COMMIT` were manually inserted into Coolify's database on `2026-10-29 13:45:51 UTC` (IDs 83 and 84), Coolify's auto-injection was suppressed. The variable froze at stale commit `bbe21b8...`, causing Docker Compose to pull outdated container images while Coolify believed it was deploying newer commits.

### Key Audit Discoveries
1. **Coolify Native Auto-Injection [VERIFIED]:** When `SOURCE_COMMIT` is absent from Coolify's Environment Variables table, Coolify automatically runs `git ls-remote` on `refs/heads/main`, extracts the 40-character commit SHA, and populates `SOURCE_COMMIT` into `.env`.
2. **GitHub Actions Deploy Bug in Coolify v4.6.0 [VERIFIED]:** `.github/workflows/publish-images.yml` (line 134) uses `curl -X GET "${COOLIFY_URL}/api/v1/deploy..."`. In Coolify v4.6.0, `/api/v1/deploy` has been migrated to `POST` only; calling `GET` returns `405 Method Not Allowed` with message `"This endpoint has changed to a POST request."`.
3. **Application UUID Mismatch in Runbook [VERIFIED]:** Documentation in `docs/runbooks/ghcr-deployment.md` listed an obsolete application UUID (`wkhdh0xb83peateermo2s0vd`), whereas the active production application UUID is `m0lhtrori7rbplpzwzilohfz`.
4. **Race Condition Prevention [VERIFIED]:** GitHub push webhooks directly triggering Coolify would cause Docker Compose to attempt pulling GHCR images before GitHub Actions finishes building them (~5–8 min build duration). Automated deployments must be triggered exclusively by the `deploy` job in `.github/workflows/publish-images.yml` via API `POST` after all 5 images have been pushed to GHCR.

---

## 2. Current Production Deployment Architecture

```
                                  [Developer / Antigravity]
                                             │
                                     git push origin main
                                             │
                                             ▼
                               ┌───────────────────────────┐
                               │  GitHub Actions Pipeline  │
                               │  - backend-pipeline.yml   │
                               │  - publish-images.yml     │
                               └─────────────┬─────────────┘
                                             │ Builds 5 images in parallel
                                             ▼
                             ┌───────────────────────────────┐
                             │ GitHub Container Registry     │
                             │ (ghcr.io/raadtech2026-usame)  │
                             │ - raad-backend:<40-char-sha>  │
                             │ - raad-frontend:<40-char-sha> │
                             │ - raad-device-gateway:<sha>   │
                             │ - raad-jt1078-relay:<sha>     │
                             │ - raad-backup:<40-char-sha>   │
                             └───────────────┬───────────────┘
                                             │
                          deploy job (needs: build) triggers:
                          POST https://coolify.raadsystems.tech/api/v1/deploy
                                             │
                                             ▼
                             ┌───────────────────────────────┐
                             │ Hostinger VPS (72.62.7.212)   │
                             │ Coolify v4.6.0 (Docker Engine)│
                             │ App: m0lhtrori7rbplpzwzilohfz │
                             └───────────────┬───────────────┘
                                             │
                         git ls-remote -> resolves 40-char commit SHA
                         Writes SOURCE_COMMIT=<sha> into runtime .env
                         Executes: docker compose pull && up -d
                                             │
                                             ▼
                             ┌───────────────────────────────┐
                             │ 9 Healthy Production Services │
                             │ - backend (raad-backend)      │
                             │ - worker (raad-backend)       │
                             │ - migrate (raad-backend)      │
                             │ - frontend (raad-frontend)    │
                             │ - device-gateway              │
                             │ - jt1078-relay                │
                             │ - backup                      │
                             │ - postgres:16-alpine          │
                             │ - redis:7-alpine              │
                             └───────────────────────────────┘
```

### Verified Running Production Stack (Hostinger VPS `72.62.7.212`)
Inspected via `docker ps` on 2026-11-05:
| Container Name | Image Reference | Repo Digest | Status |
|---|---|---|---|
| `backend-m0lhtrori7rbplpzwzilohfz-20261105T121925` | `ghcr.io/raadtech2026-usame/raad-backend:64b8176b8b81b6b25900b39d8648e4683da5897e` | `sha256:431443c734bc5709e8949517781ab9a57723522d26be323dc063e78fb55cb9a0` | Up (healthy) |
| `worker-m0lhtrori7rbplpzwzilohfz-20261105T121926` | `ghcr.io/raadtech2026-usame/raad-backend:64b8176b8b81b6b25900b39d8648e4683da5897e` | `sha256:431443c734bc5709e8949517781ab9a57723522d26be323dc063e78fb55cb9a0` | Up (healthy) |
| `frontend-m0lhtrori7rbplpzwzilohfz-20261105T121925` | `ghcr.io/raadtech2026-usame/raad-frontend:64b8176b8b81b6b25900b39d8648e4683da5897e` | `sha256:49155590fd28a7b97791262beaba7a8c4daf4c32b1e5a58b94052f20162d1e9b` | Up (healthy) |
| `device-gateway-m0lhtrori7rbplpzwzilohfz-20261105T121925` | `ghcr.io/raadtech2026-usame/raad-device-gateway:64b8176b8b81b6b25900b39d8648e4683da5897e` | `sha256:f65ee2ede1664475eaa3b891343fa37891c401d5babab8d6b44d8ab0a6bce58a` | Up (healthy) |
| `jt1078-relay-m0lhtrori7rbplpzwzilohfz-20261105T121925` | `ghcr.io/raadtech2026-usame/raad-jt1078-relay:64b8176b8b81b6b25900b39d8648e4683da5897e` | `sha256:678a665504daa0e52c88b6a2c399d4dfed2de470dc1fa5852fe4908c46af0276` | Up (healthy) |
| `backup-m0lhtrori7rbplpzwzilohfz-20261105T121925` | `ghcr.io/raadtech2026-usame/raad-backup:64b8176b8b81b6b25900b39d8648e4683da5897e` | `sha256:3866eadf1f673dc5ff82583cab0f63776e4baa3c3c6ac0fb36d17997eb600db2` | Up |
| `postgres-m0lhtrori7rbplpzwzilohfz-20261105T121926` | `postgres:16-alpine` | `sha256:ba35775c74291079d84c6c9a3bf00473ce3620f545fc9c1db13e5361394c8b3d` | Up (healthy) |
| `redis-m0lhtrori7rbplpzwzilohfz-20261105T121926` | `redis:7-alpine` | `sha256:ebf9b9776f82ea751d36ecb0596b4ef841cf673e3ae8c7ff8bf5ddb8bc66f8e7` | Up (healthy) |
| `prometheus-m0lhtrori7rbplpzwzilohfz-20261105T121926` | `prom/prometheus:v2.53.0` | `sha256:1f156d68b9816cb15cf015403063f28cf692d47781b490f23f81e35d1f8f9064` | Up |

---

## 3. Exact Purpose and Location of `SOURCE_COMMIT`

### A. Purpose
In `docker/docker-compose.coolify.full.yml`, all RAAD container services specify:
```yaml
image: ghcr.io/raadtech2026-usame/<service-name>:${SOURCE_COMMIT}
```
The parameter `${SOURCE_COMMIT}` provides an **immutable release contract**:
1. It guarantees that every service (`backend`, `frontend`, `gateway`, `relay`, `backup`) runs the exact same code artifact compiled from that specific Git commit.
2. It eliminates cache pollution and ambiguity caused by mutable tags like `:latest` or `:main`.
3. It has no default fallback (`:-`) by design, ensuring that if `${SOURCE_COMMIT}` is unresolved, `docker compose pull` fails immediately *before* terminating any running containers.

### B. Where `SOURCE_COMMIT` is Defined and Consumed
1. **GitHub Actions:**
   - In `.github/workflows/publish-images.yml` (line 92):
     `tags: ${{ env.REGISTRY }}/${{ env.OWNER }}/${{ matrix.image }}:${{ github.sha }}`
   - Images are published directly to GHCR using GitHub's 40-character commit SHA `${{ github.sha }}`.
2. **Coolify Source Code:**
   - Location: Container `coolify`, path `/var/www/html/app/Jobs/ApplicationDeploymentJob.php`.
   - Lines 3473–3488:
     ```php
     $lsRemoteOutput = $this->saved_outputs->get('git_commit_sha');
     preg_match('/\b([0-9a-fA-F]{40})(?=\s*\t)/', $output, $matches);
     if (isset($matches[1])) {
         $this->commit = $matches[1];
         $this->application_deployment_queue->commit = $this->commit;
         $this->application_deployment_queue->save();
     }
     ```
   - Lines 4324–4333:
     ```php
     if (! $forBuildTime || $this->application->settings->include_source_commit_in_build) {
         if ($this->application->environment_variables->where('key', 'SOURCE_COMMIT')->isEmpty()) {
             if (! is_null($this->commit)) {
                 $coolify_envs->put('SOURCE_COMMIT', $this->commit);
             } else {
                 $coolify_envs->put('SOURCE_COMMIT', 'unknown');
             }
         }
     }
     ```
3. **Coolify Runtime `.env` File:**
   - Location: `/data/coolify/applications/m0lhtrori7rbplpzwzilohfz/.env`
   - Line: `SOURCE_COMMIT=64b8176b8b81b6b25900b39d8648e4683da5897e`
   - Generated at deploy time by `save_runtime_environment_variables()` (line 2145) and passed to Docker Compose.

---

## 4. Whether Manual Updates Are Genuinely Necessary

### Answer: ABSOLUTELY NOT.
Manual updates are an artifact of a historical configuration accident, directly contradicting the original architectural specification in ADR-0045:

> **ADR-0045 (§4):**  
> *"The keystone: Coolify writes `SOURCE_COMMIT` into the `.env` file it passes to `docker compose pull`/`up`... So the tag **always equals the commit being deployed**, with no tag plumbing, no per-deploy variable to update, and no way for the running stack to reference an image built from different source than the checkout."*

### Why Manual Updates Were Happening
In Coolify's PostgreSQL database (`coolify-db`), the table `environment_variables` contained two manual records:
- `id: 83`, `key: 'SOURCE_COMMIT'`, `created_at: 2026-10-29 13:45:51`
- `id: 84`, `key: 'SOURCE_COMMIT'`, `created_at: 2026-10-29 13:45:51`

Because these records existed, Coolify's internal condition:
`$this->application->environment_variables->where('key', 'SOURCE_COMMIT')->isEmpty()`
evaluated to **FALSE**. Coolify skipped automatic population of `$this->commit` and substituted the hardcoded database value instead.

---

## 5. Root Cause of the Previous Stale Commit Incident

The incident where Coolify remained stuck on commit `bbe21b8e223f8c2911da894b875643608b6ed7b8` (causing Alembic migration failure on revision `f7b8c9d0e1a2`) occurred through this sequence:

1. **2026-10-29 13:45:51 UTC:** During initial setup or troubleshooting, `SOURCE_COMMIT` was manually added to Coolify's Environment Variables UI.
2. **Subsequent Commits:** Developers pushed new commits to `main`.
3. **Coolify Checkout vs. Docker Pull Discrepancy:**
   - In deployment #26, Coolify executed Git clone and correctly fetched commit `64b8176...`.
   - When writing the runtime `.env` file, Coolify checked if `SOURCE_COMMIT` was set in the environment variables list. Finding record 83 (`bbe21b8...`), it wrote `SOURCE_COMMIT=bbe21b8...` into `/data/coolify/applications/m0lhtrori7rbplpzwzilohfz/.env`.
   - Docker Compose pulled `ghcr.io/raadtech2026-usame/raad-backend:bbe21b8...`.
   - The migration container executed Alembic with the stale code, attempting to create duplicate indexes that already existed, throwing `DuplicateTableError: relation "ix_students__organization_id_full_name" already exists`.
4. **Log Redaction Obscured Root Cause:**
   Because `SOURCE_COMMIT` was registered as a secret environment variable in Coolify, Coolify's log sanitizer replaced occurrences of the commit SHA in logs with `<REDACTED>`, masking the fact that the old SHA was being pulled.

---

## 6. GitHub-to-GHCR-to-Coolify Deployment Flow

```
1. Developer merges PR to 'main'
         │
         ▼
2. GitHub Actions: backend-pipeline.yml (Unit & Integration tests)
         │ (runs on ubuntu-latest)
         ▼
3. GitHub Actions: publish-images.yml (Trigger: push to main)
         │
         ├── Builds raad-backend (backend, worker, migrate)
         ├── Builds raad-frontend
         ├── Builds raad-device-gateway
         ├── Builds raad-jt1078-relay
         └── Builds raad-backup
         │
         ▼
4. Images Pushed to GHCR:
   ghcr.io/raadtech2026-usame/raad-*:<github.sha>
         │
         ▼
5. deploy job (gated on 'needs: build')
   Sends API Request:
   POST https://coolify.raadsystems.tech/api/v1/deploy?uuid=m0lhtrori7rbplpzwzilohfz&force=false
         │
         ▼
6. Coolify ApplicationDeploymentJob
   ├── Fetches git refs/heads/main -> extracts 40-char SHA
   ├── Checks environment_variables table: SOURCE_COMMIT is EMPTY
   ├── Injects SOURCE_COMMIT=<40-char-sha> into runtime .env
   ├── Runs: docker compose pull --ignore-buildable
   ├── Runs: docker compose up -d (with migrate service dependency)
   └── Executes container healthchecks -> SUCCESS
```

---

## 7. Comparison of Deployment Models

| Evaluation Metric | Model A: Direct GitHub Build on VPS | Model B: GHCR Images (Manual Coolify Update) | Model C: GHCR Images (Fully Automated CI/CD) |
|---|---|---|---|
| **Build Location** | Hostinger VPS (4 vCPUs) | GitHub-hosted runners (ubuntu-latest) | GitHub-hosted runners (ubuntu-latest) |
| **VPS CPU Impact** | ❌ **Critical Hazard**: Saturated 70–100% CPU across 4 cores, load avg 5.41 | ✅ **Zero build load**: Pulls pre-built layers only | ✅ **Zero build load**: Pulls pre-built layers only |
| **Manual Steps** | None (auto-build on push) | ❌ **High friction**: Human must edit Coolify env var for every commit | ✅ **Zero manual steps**: Fully automated push-to-deploy |
| **Rollback Safety** | ❌ Rebuilding old commit may fail due to dependency drift | ⚠️ Manual env var edit required to target old commit | ✅ **Instant & Deterministic**: Target SHA image pulled immediately |
| **Failure Mode** | Build failure brings down deploy container | Human forgets to update SHA → deploys stale code | Broken build halts in CI before touching production |
| **Security** | Secrets exposed during build on VPS | Public GHCR images, runtime secrets in Coolify | Public GHCR images, deploy-only token in GitHub |
| **Verdict** | **REJECTED** (Per ADR-0045) | **REJECTED** (Incident-prone, caused outage) | **RECOMMENDED** |

---

## 8. Recommended Architecture and Justification

### Recommended: Model C (Automated GitHub Actions GHCR Pipeline + Native Coolify Auto-Commit)

#### Justification:
1. **Preserves ADR-0045 Benefits:** Offloads all CPU-intensive image construction to GitHub Actions, keeping Hostinger VPS load average ~0.2–0.5.
2. **Restores Coolify's Intended Native Design:** Leverages Coolify's existing `ApplicationDeploymentJob.php` code to inject `$this->commit` automatically without maintaining custom sidecar scripts.
3. **Completely Eliminates Human Error:** No engineer or administrator ever needs to open Coolify to update `SOURCE_COMMIT`.
4. **Enforces Strict Ordering:** Coolify is triggered *only* after all 5 GHCR image tags exist.
5. **Deterministic Rollbacks:** Coolify's native UI "Rollback" feature will automatically pull the corresponding SHA-tagged GHCR images for earlier deployments.

---

## 9. Required Code and Configuration Changes

### A. Fix HTTP Method in `.github/workflows/publish-images.yml`
In `.github/workflows/publish-images.yml` lines 134–137, change `-X GET` to `-X POST` and add the `Content-Type` header:

```diff
-          curl --fail-with-body -sS -X GET \
-            -H "Authorization: Bearer ${COOLIFY_API_TOKEN}" \
-            "${COOLIFY_URL}/api/v1/deploy?uuid=${COOLIFY_APP_UUID}&force=false" \
-            -o response.json
+          curl --fail-with-body -sS -X POST \
+            -H "Authorization: Bearer ${COOLIFY_API_TOKEN}" \
+            -H "Content-Type: application/json" \
+            "${COOLIFY_URL}/api/v1/deploy?uuid=${COOLIFY_APP_UUID}&force=false" \
+            -o response.json
```

### B. Update Documentation in `docs/runbooks/ghcr-deployment.md`
Update `COOLIFY_APP_UUID` in documentation:
```diff
- | `COOLIFY_APP_UUID` | `wkhdh0xb83peateermo2s0vd` |
+ | `COOLIFY_APP_UUID` | `m0lhtrori7rbplpzwzilohfz` |
```

---

## 10. Required Coolify Configuration Changes

### A. Remove Static `SOURCE_COMMIT` from Environment Variables
In Coolify's database or UI, delete environment variable records with `key = 'SOURCE_COMMIT'`:
```sql
DELETE FROM environment_variables 
WHERE key = 'SOURCE_COMMIT' AND resourceable_id = 1;
```
*(Once deleted, Coolify automatically injects the latest Git commit SHA into `.env` at every deployment).*

### B. Disable GitHub Webhook Auto-Deploy on Coolify Application
To prevent Coolify from triggering premature pulls while GitHub Actions is still compiling images:
- Application Settings -> Ensure `is_auto_deploy_enabled` is set to `false` (or remove the GitHub Push Webhook in GitHub repo settings). Deployments must only be triggered via the CI deploy job.

### C. Create Deploy-Only API Token in Coolify
In Coolify Dashboard -> *Keys & Tokens* -> *API Tokens*:
1. Create a new token: `github-actions-deploy-only`.
2. Grant permission: **`deploy` only** (do not grant `root` or `read:sensitive`).
3. Store the generated token in GitHub Secrets as `COOLIFY_API_TOKEN`.

---

## 11. GitHub Actions Implementation Plan

### Required GitHub Repository Configuration
Configure in GitHub: `Settings` → `Secrets and variables` → `Actions`:

#### 1. Repository Variables (`vars.*`):
| Variable Name | Recommended Value | Purpose |
|---|---|---|
| `COOLIFY_DEPLOY_ENABLED` | `true` | Enables the `deploy` step in `publish-images.yml` |
| `VITE_API_BASE_URL` | `https://api.raadsystems.tech/api/v1` | Compiled into frontend JS bundle |
| `VITE_WS_BASE_URL` | `wss://api.raadsystems.tech` | Compiled into frontend JS bundle |

#### 2. Repository Secrets (`secrets.*`):
| Secret Name | Recommended Value | Purpose |
|---|---|---|
| `COOLIFY_URL` | `https://coolify.raadsystems.tech` | Coolify base URL |
| `COOLIFY_APP_UUID` | `m0lhtrori7rbplpzwzilohfz` | Production Application UUID |
| `COOLIFY_API_TOKEN` | *(From Coolify Step 10.C)* | Least-privilege deploy token |
| `VITE_MAPBOX_ACCESS_TOKEN` | *(Public `pk.*` Mapbox token)* | Inlined into frontend assets |
| `VITE_STRIPE_PUBLISHABLE_KEY` | *(Empty / Optional)* | Stripe token |

---

## 12. Rollback and Release Consistency Strategy

### A. How Rollback Operates
1. In Coolify Dashboard -> Application -> *Deployments*.
2. Select any previously successful deployment (e.g., commit `64b8176...`) and click **Redeploy / Rollback**.
3. Because `SOURCE_COMMIT` is no longer a static environment variable, Coolify sets `$this->commit = <rollback-sha>` and writes that SHA into `.env`.
4. Docker Compose executes `docker compose pull` for that exact immutable SHA from GHCR and starts the previous containers.

### B. Critical Rollback Safeguards
1. **GHCR Retention Policy:** Retain SHA-tagged images in GHCR for at least 30 days (minimum 20 versions).
2. **Alembic Reversibility:** As documented in `docs/runbooks/rollback.md`, rolling back container images does not automatically rollback database migrations. Database migrations must always be backward-compatible (expand-and-contract pattern).

---

## 13. Risks and Safeguards

| Identified Risk | Impact | Mitigating Safeguard |
|---|---|---|
| **GitHub Actions Build Failure** | New code is not deployed | Gated by `needs: build`. The deploy job will not run; production containers are untouched. |
| **Premature Deployment Race** | Coolify pulls non-existent image | Direct GitHub push webhooks are disabled; Coolify is triggered *only* after all 5 GHCR image pushes complete. |
| **Coolify API Token Compromise** | Unauthorized deploy triggers | Token is given `deploy` ability ONLY. It cannot read environment variables, database credentials, or server files. |
| **Coolify Native Auto-Commit Failure** | `SOURCE_COMMIT` defaults to `unknown` | Docker Compose has no `:-` fallback. If `SOURCE_COMMIT` is invalid, `pull` fails cleanly before stopping containers. |

---

## 14. Step-by-Step Implementation Plan

> [!IMPORTANT]
> The following plan is submitted for review and approval. In accordance with user operating instructions, no modifications have been executed during this audit.

### Phase 1: Coolify Clean-up (Estimated duration: 3 minutes)
1. Open Coolify Dashboard (or execute via `coolify-db` query):
   Delete `SOURCE_COMMIT` from Environment Variables.
2. In Coolify -> Keys & Tokens -> API Tokens:
   Generate `github-actions-deploy-only` with `deploy` ability only.
3. In Coolify -> Application Settings:
   Ensure `is_auto_deploy_enabled` is set to `false` (relying exclusively on CI trigger).

### Phase 2: GitHub Repository Configuration (Estimated duration: 3 minutes)
1. In GitHub repo Settings -> Secrets and variables -> Actions:
   - Set secret `COOLIFY_URL` = `https://coolify.raadsystems.tech`
   - Set secret `COOLIFY_APP_UUID` = `m0lhtrori7rbplpzwzilohfz`
   - Set secret `COOLIFY_API_TOKEN` = `<token from Phase 1>`
   - Set variable `COOLIFY_DEPLOY_ENABLED` = `true`

### Phase 3: Codebase Updates (Estimated duration: 2 minutes)
1. In `.github/workflows/publish-images.yml`:
   Change `-X GET` to `-X POST` on line 134.
2. In `docs/runbooks/ghcr-deployment.md`:
   Update documentation with verified UUID `m0lhtrori7rbplpzwzilohfz`.
3. Commit and push changes to `main`.

### Phase 4: End-to-End Verification (Estimated duration: 7 minutes)
1. Monitor GitHub Actions `publish-images.yml`.
2. Confirm matrix build succeeds and `deploy` job executes with HTTP 200/201.
3. On VPS, confirm Coolify deployment starts automatically, pulls new commit images, and reports all 9 containers healthy.

---

## 15. Verification Checklist

- [x] VPS SSH connectivity verified (`72.62.7.212`, key authentication).
- [x] All 9 production containers verified healthy on commit `64b8176b8b81b6b25900b39d8648e4683da5897e`.
- [x] Database health and Alembic HEAD revision `b2c3d4e5f6a7` verified intact.
- [x] Coolify source code inspected at `/var/www/html/app/Jobs/ApplicationDeploymentJob.php`.
- [x] Verified Coolify native auto-injection logic for `SOURCE_COMMIT` (lines 4324–4333).
- [x] Verified suppression mechanism caused by manual environment variable records 83 and 84.
- [x] Verified Coolify API controller requirement for `POST /api/v1/deploy` (lines 14–25, `OtherController.php`).
- [x] Verified all 5 production image digests in GHCR and Docker daemon.
- [x] Verified zero container modifications, zero file modifications, and zero secret exposures during audit.

---

## 16. Unknowns & Unverified Items

1. **GitHub Repository Settings State [NOT VERIFIED]:**
   - Direct inspection of GitHub Actions Secrets and Variables (`COOLIFY_DEPLOY_ENABLED`, `COOLIFY_API_TOKEN`) could not be executed via `gh` CLI because `gh` is not installed on this local Windows machine. These values must be inspected and set via the GitHub web UI.
2. **Mapbox Public Token Domain Whitelist [NOT VERIFIED]:**
   - Whether the Mapbox `pk.*` token has URL restrictions configured in the Mapbox management console cannot be inspected from the codebase or VPS (identical to ADR-0045 status).
