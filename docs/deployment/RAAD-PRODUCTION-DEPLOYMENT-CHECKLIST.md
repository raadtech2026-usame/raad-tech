# RAAD-TECH — Production Deployment Checklist

**Target:** RAAD-TECH Production Platform  
**VPS:** Hostinger `srv2082072` (`72.62.7.212`), Ubuntu 24.04 LTS  
**Coolify:** v4.6.0 (Application UUID `m0lhtrori7rbplpzwzilohfz`)  
**Remediation Branch:** `perf/production-remediation` -> `main`  
**Target Migration Revision:** `c3d4e5f6a7b8`  

---

## 1. Pre-Deployment Readiness (Safety Gate)

Before triggering any changes on production:

- [ ] **Verify Local Test Suites Pass:**
  ```powershell
  cd backend
  .\.venv\Scripts\python.exe -m unittest discover -s tests/unit
  .\.venv\Scripts\python.exe -m unittest discover -s tests/architecture
  .\.venv\Scripts\python.exe -m unittest discover -s tests/contract
  cd ../frontend
  npm test
  npm run build
  ```
- [ ] **Verify Git State & Branch:**
  Ensure all changes are committed on branch `perf/production-remediation`. Never merge broken code to `main`.
- [ ] **Capture On-Demand Pre-Deployment Database Dump:**
  SSH to VPS `72.62.7.212` and run:
  ```bash
  docker exec raad-backup /app/backup.sh
  ```
  Verify backup file creation and non-zero size:
  ```bash
  cat /var/lib/docker/volumes/m0lhtrori7rbplpzwzilohfz_raad_backups_data/_data/.latest_status
  ```
- [ ] **Record Current Production Alembic Revision:**
  ```bash
  docker exec -t raad-postgres psql -U raad -d raad -c "SELECT version_num FROM alembic_version;"
  ```
  *(Expected: `b2c3d4e5f6a7`)*

---

## 2. Infrastructure & Ingress Hardening (Hostinger & Coolify)

### A. Close Public Port 8000 on Hostinger Firewall
Public port 8000 is currently exposed to the internet, allowing unencrypted HTTP traffic to bypass Traefik.
- [ ] Navigate to Hostinger Control Panel -> VPS `srv2082072` -> Security -> Firewall.
- [ ] Select Firewall Group `357633`.
- [ ] Locate rule for Port 8000 TCP (Allow 0.0.0.0/0).
- [ ] Delete or disable this rule. Port 8000 must only be accessible over internal Docker networks (`172.18.0.0/16`).

### B. Configure Traefik Ingress for Coolify Dashboard
Currently `https://coolify.raadsystems.tech` returns 503 because Coolify's web UI is not routed through Traefik under its own FQDN.
- [ ] In Coolify Settings -> Instance Settings -> Server URL:
  Set to `https://coolify.raadsystems.tech`.
- [ ] Ensure DNS for `coolify.raadsystems.tech` points to `72.62.7.212`.
- [ ] Traefik will issue a Let's Encrypt TLS certificate and route `coolify.raadsystems.tech` directly to Coolify (port 8000 internal).

### C. Apex Domain Redirect (`raadsystems.tech` -> `app.raadsystems.tech`)
- [ ] In Cloudflare / Hostinger DNS, configure a redirect rule:
  `https://raadsystems.tech/*` -> `https://app.raadsystems.tech/$1` (301 Permanent).

---

## 3. Code Integration & Image Build

- [ ] **Create Pull Request:**
  Create PR from `perf/production-remediation` to `main`.
- [ ] **Review Changes:**
  Verify diff matches the approved remediation scope:
  - `infrastructure/nginx/conf.d/frontend.conf`
  - `backend/raad/core/config/settings.py`
  - `backend/raad/main.py`
  - `backend/migrations/versions/20261106_1800_c3d4e5f6a7b8_outbox_pending_partial_index.py`
  - `backend/raad/core/events/outbox.py`
  - `backend/raad/modules/video/...`
  - `backend/raad/modules/school_erp/...`
  - `docker/docker-compose.yml`
  - `docker/docker-compose.coolify.full.yml`
  - `scripts/db/backup.sh`
- [ ] **Merge PR to `main`:**
  Merge using standard PR workflow.
- [ ] **Wait for GitHub Actions Image Publishing:**
  Workflow `.github/workflows/publish-images.yml` will trigger and build images tagged with `${GITHUB_SHA}`:
  - `ghcr.io/raadtech2026-usame/raad-backend:${SOURCE_COMMIT}`
  - `ghcr.io/raadtech2026-usame/raad-frontend:${SOURCE_COMMIT}`
  - `ghcr.io/raadtech2026-usame/raad-device-gateway:${SOURCE_COMMIT}`
  - `ghcr.io/raadtech2026-usame/raad-backup:${SOURCE_COMMIT}`

---

## 4. Production Deployment Execution (Coolify)

- [ ] **Trigger Redeployment in Coolify:**
  - Navigate to Coolify Dashboard -> Projects -> RAAD-TECH -> Stack `m0lhtrori7rbplpzwzilohfz`.
  - Click **Deploy**.
  - Monitor deployment logs as Coolify pulls fresh container images from GHCR.
- [ ] **Verify Database Migration Execution:**
  The `migrate` container automatically runs:
  ```bash
  alembic upgrade head
  ```
  Verify migration log output shows:
  ```
  Running upgrade b2c3d4e5f6a7 -> c3d4e5f6a7b8, events: add partial index on outbox(created_at) for unpublished events
  ```
- [ ] **Verify PostgreSQL Status & Applied Tuning:**
  SSH to VPS and inspect PostgreSQL settings:
  ```bash
  docker exec -t raad-postgres psql -U raad -d raad -c "SHOW shared_buffers; SHOW effective_cache_size; SHOW random_page_cost; SHOW work_mem; SHOW jit;"
  ```
  *Expected values:*
  - `shared_buffers`: `1GB`
  - `effective_cache_size`: `4GB`
  - `random_page_cost`: `1.1`
  - `work_mem`: `16MB`
  - `jit`: `off`
- [ ] **Verify Alembic Revision:**
  ```bash
  docker exec -t raad-postgres psql -U raad -d raad -c "SELECT version_num FROM alembic_version;"
  ```
  *Expected value: `c3d4e5f6a7b8`*
- [ ] **Verify Partial Index Existence on `outbox`:**
  ```bash
  docker exec -t raad-postgres psql -U raad -d raad -c "\d outbox"
  ```
  Confirm `ix_outbox__pending_created_at` is listed.

---

## 5. Post-Deployment Verification & Smoke Tests

### A. Frontend Gzip & Caching Verification
Run from an external terminal:
```bash
curl -I -H "Accept-Encoding: gzip" https://app.raadsystems.tech/
```
Verify `Content-Encoding: gzip` or `Vary: Accept-Encoding`.

Test asset caching header:
```bash
# Pick an asset from index HTML
curl -I https://app.raadsystems.tech/assets/index-Dze_FsD_.js
```
Verify:
- `Cache-Control: public, max-age=31536000, immutable`
- `Content-Encoding: gzip`

Test `index.html` non-caching:
```bash
curl -I https://app.raadsystems.tech/index.html
```
Verify:
- `Cache-Control: no-cache, no-store, must-revalidate`

### B. CORS Preflight Max-Age Verification
```bash
curl -X OPTIONS https://api.raadsystems.tech/health \
  -H "Origin: https://app.raadsystems.tech" \
  -H "Access-Control-Request-Method: GET" \
  -I
```
Verify:
- `Access-Control-Allow-Origin: https://app.raadsystems.tech`
- `Access-Control-Max-Age: 86400`

### C. Container Healthchecks Verification
```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```
Verify that all containers show `(healthy)`:
- `raad-postgres` (healthy)
- `raad-redis` (healthy)
- `raad-backend` (healthy)
- `raad-frontend` (healthy)
- `raad-device-gateway` (healthy)
- `raad-backup` (healthy)
- `raad-prometheus` (healthy)

### D. User Acceptance Smoke Test
1. Log in to `https://app.raadsystems.tech`.
2. Observe page loading speed (sub-second render from disk cache).
3. Navigate to Fleet Tracking page — confirm map renders and telemetry streams.
4. Navigate to School ERP / Finance page — confirm invoice batches display immediately.
5. Verify no console errors in browser DevTools.
