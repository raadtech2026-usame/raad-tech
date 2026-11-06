# RAAD-TECH — Production Rollback Plan

**Target:** RAAD-TECH Production Platform  
**VPS:** Hostinger `srv2082072` (`72.62.7.212`), Ubuntu 24.04 LTS  
**Application Platform:** Coolify 4.6.0  
**Rollback Revision Target:** `b2c3d4e5f6a7` (down from `c3d4e5f6a7b8`)  

---

## 1. Rollback Criteria & Decision Triggers

Initiate this rollback procedure immediately if any of the following occur during or after deployment:
1. **Critical Service Failure:** Backend, Worker, or Frontend containers fail to enter `healthy` status within 5 minutes of deployment.
2. **Database Migration Failure:** The `migrate` container fails, leaving the schema in an inconsistent state.
3. **Application Regressions:**
   - User authentication fails repeatedly with 500 Internal Error.
   - Core operational pages (Live Tracking, School ERP, Fleet Devices) experience unrecoverable rendering or API contract errors.
   - High database lock contention or CPU exhaustion appears on PostgreSQL.

---

## 2. Component-by-Component Rollback Procedures

### Procedure A: Database Migration Downgrade (`c3d4e5f6a7b8` -> `b2c3d4e5f6a7`)

The migration `20261106_1800_c3d4e5f6a7b8_outbox_pending_partial_index.py` is fully reversible and non-destructive. Downgrading removes only the partial index `ix_outbox__pending_created_at`; it **never drops tables, columns, or data**.

**Execution Steps:**
1. Connect via SSH to VPS `72.62.7.212`.
2. Inspect the running containers:
   ```bash
   docker ps --filter "name=raad-backend"
   ```
3. Run Alembic downgrade from the backend container:
   ```bash
   docker exec -i raad-backend alembic downgrade b2c3d4e5f6a7
   ```
   *Expected output:*
   ```
   Running downgrade c3d4e5f6a7b8 -> b2c3d4e5f6a7, events: add partial index on outbox(created_at) for unpublished events
   ```
4. Verify the revision was rolled back:
   ```bash
   docker exec -t raad-postgres psql -U raad -d raad -c "SELECT version_num FROM alembic_version;"
   ```
   *Confirmed value: `b2c3d4e5f6a7`*
5. Verify the index was safely removed:
   ```bash
   docker exec -t raad-postgres psql -U raad -d raad -c "SELECT indexname FROM pg_indexes WHERE tablename = 'outbox';"
   ```
   Confirm `ix_outbox__pending_created_at` is no longer present.

---

### Procedure B: Container Application Rollback via Coolify

To revert code changes (Backend, Frontend, Device Gateway):

1. **Identify Previous Stable Commit SHA:**
   Locate the commit SHA prior to merging `perf/production-remediation` (e.g., `HEAD~1` on `main`).
2. **Rollback in Coolify UI:**
   - Navigate to Coolify Dashboard -> Application `m0lhtrori7rbplpzwzilohfz`.
   - Under **General Settings** -> **Git Commit / Tag**, input the previous stable commit SHA.
   - Click **Deploy**.
   - Coolify will pull the corresponding GHCR image tags:
     `ghcr.io/raadtech2026-usame/raad-backend:<PREVIOUS_SHA>`
     `ghcr.io/raadtech2026-usame/raad-frontend:<PREVIOUS_SHA>`
3. **Verify Health:**
   ```bash
   docker ps --format "table {{.Names}}\t{{.Status}}"
   ```
   Ensure all services transition back to `healthy`.

---

### Procedure C: PostgreSQL Engine Parameter Rollback

If PostgreSQL performance tuning parameters (`shared_buffers=1GB`, `random_page_cost=1.1`, etc.) cause unexpected memory pressure:

1. **Revert Compose Configuration:**
   Remove the `command:` override block from `docker-compose.coolify.full.yml` (or restore default flags):
   ```yaml
   postgres:
     container_name: raad-postgres
     # Remove or comment the command section
   ```
2. **Restart Postgres Container:**
   ```bash
   docker restart raad-postgres
   ```
3. **Verify Restored Defaults:**
   ```bash
   docker exec -t raad-postgres psql -U raad -d raad -c "SHOW shared_buffers; SHOW random_page_cost; SHOW jit;"
   ```
   *Expected restored defaults:*
   - `shared_buffers`: `128MB`
   - `random_page_cost`: `4`
   - `jit`: `on`

---

### Procedure D: Emergency Database Restore (Worst-Case Disaster Recovery)

If production data was somehow corrupted during an unforeseen event, restore the pre-deployment snapshot created during Step 1 of the Deployment Checklist.

> [!CAUTION]
> This drops existing database objects and restores from the designated `.dump` file. Any data written since the snapshot was taken will be overwritten.

1. **Stop Application Writers (Prevent Data Corruption):**
   ```bash
   docker stop raad-backend raad-worker raad-device-gateway
   ```
2. **Identify Pre-Deployment Snapshot File:**
   ```bash
   ls -la /var/lib/docker/volumes/m0lhtrori7rbplpzwzilohfz_raad_backups_data/_data/
   ```
   Locate `raad_raad_<TIMESTAMP>.dump`.
3. **Execute Restore Script with Confirmation:**
   ```bash
   docker exec -it raad-backup /app/restore.sh \
     --target-url "postgresql://raad:${POSTGRES_PASSWORD}@postgres:5432/raad" \
     --confirm \
     "/backups/raad_raad_<TIMESTAMP>.dump"
   ```
4. **Verify Restored Database:**
   ```bash
   docker exec -t raad-postgres psql -U raad -d raad -c "SELECT COUNT(*) FROM users; SELECT version_num FROM alembic_version;"
   ```
5. **Restart Application Services:**
   ```bash
   docker start raad-backend raad-worker raad-device-gateway
   ```
6. **Perform Full System Smoke Test.**

---

## 3. Post-Rollback Sign-Off Checklist

- [ ] Database connectivity verified (`pg_isready`).
- [ ] Database schema is at `b2c3d4e5f6a7`.
- [ ] Frontend web app loads without JavaScript errors.
- [ ] Active telemetry streams in live tracking.
- [ ] Incident recorded in `docs/operations/` with timestamp, trigger, and root cause analysis.
