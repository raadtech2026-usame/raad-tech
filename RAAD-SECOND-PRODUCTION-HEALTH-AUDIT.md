# RAAD-TECH — Second Production Health Audit Report

**Document Title:** Second Read-Only Production Health Audit: Infrastructure, Services, Database, Security & Backups  
**File Name:** `RAAD-SECOND-PRODUCTION-HEALTH-AUDIT.md`  
**Date of Audit:** November 6, 2026  
**Audited Target:** Hostinger VPS `srv2082072` (IPv4: `72.62.7.212`, IPv6: `2a02:4780:f:da36::1`)  
**Container Stack:** Coolify PaaS 4.6.0, Application Resource `m0lhtrori7rbplpzwzilohfz` (Commit `4fd6c9a8123c1fb1baa6fe14ad3b494335dfbc34`)  
**Audit Policy:** Strict Read-Only Audit (Zero state changes, zero mutations, zero restarts, secrets protected)

---

## 1. Executive Summary & Audit Matrix

Following the forensic analysis conducted on November 5, 2026, a second comprehensive, non-destructive read-only health audit was conducted on the RAAD-TECH production environment. 

The production stack has successfully recovered from the November 5 deployment incident:
- Migration `b2c3d4e5f6a7` applied cleanly in deployment `20261105T140110`.
- The database schema is fully synchronized with HEAD (`b2c3d4e5f6a7`).
- The conflicting dual PostgreSQL engine hazard was resolved: the orphaned standalone `raad-postgres` container was removed, leaving exactly one PostgreSQL 16 container mounting `docker_raad_postgres_data`.
- All core application services (Backend, Frontend, Worker, Device Gateway, JT1078 Relay, PostgreSQL, Redis) are **Up and Healthy**.
- The main areas requiring prioritized remediation are:
  1. **Coolify HTTPS & Public Port 8000 Exposure:** Port 8000 is open publicly over cleartext HTTP, while `https://coolify.raadsystems.tech` returns 503.
  2. **Offsite Backups:** Daily local database dumps are functioning cleanly, but off-site synchronization (`BACKUP_RCLONE_REMOTE`) remains unconfigured.

### Master Findings Matrix

| # | Area / Component | Status | Finding Summary |
| :-: | :--- | :---: | :--- |
| **1.1** | PostgreSQL 16 Container Status & Health | **PASS** | Up 23+ hours, `healthy` status via internal healthcheck. |
| **1.2** | PostgreSQL 16 Database Connectivity | **PASS** | Active and responsive; accepts pool and interactive connections. |
| **1.3** | PostgreSQL 16 Database Size & Connections | **PASS** | Database size: ~40 MB (`41,917,463` bytes); 9 active connections (8 idle pool, 1 active) of 100 max. |
| **1.4** | PostgreSQL 16 Container Topology & Volumes | **PASS** | Exactly 1 container attached to `docker_raad_postgres_data`. No duplicate container conflict. |
| **2.1** | Redis 7 Container Health & Ping | **PASS** | Up 23+ hours, `healthy` status; answers `PING` with `PONG`. |
| **2.2** | Redis 7 Memory & Eviction Policy | **PASS** | Memory used: `26.69M` of `1.00G` limit (~2.6% utilization); policy: `noeviction`, AOF enabled. |
| **3.1** | RAAD Backend API Service | **PASS** | Up 23+ hours, `healthy`; public healthcheck `https://api.raadsystems.tech/health` returns `HTTP 200 {"status":"ok"}`. |
| **3.2** | RAAD Frontend Service | **PASS** | Up 23+ hours, `healthy`; `https://app.raadsystems.tech` returns `HTTP 200 OK` (Nginx 1.27.5). |
| **3.3** | RAAD Celery / Async Worker Service | **PASS** | Up 23+ hours, `healthy`. |
| **3.4** | RAAD Device Gateway Service | **PASS** | Up 23+ hours, `healthy`. |
| **3.5** | RAAD JT1078 Video Relay Service | **PASS** | Up 23+ hours, `healthy`; HTTPS endpoint routed via Traefik on `video.raadsystems.tech`. |
| **3.6** | Prometheus Monitoring Service | **PASS** | Up 23+ hours (`prom/prometheus:v2.53.0`), **no healthcheck** defined in Compose. |
| **3.7** | Automated Backup Service Container | **PASS** | Up 23+ hours, **no healthcheck** defined in Compose; loop actively sleeping on 24h interval. |
| **4.1** | JT808 TCP Listener Port 7808 | **PASS** | Active on `0.0.0.0:7808` and `[::]:7808` (Docker proxy -> `device-gateway`). |
| **4.2** | Port 6002 Listener | **PASS** | Active on `0.0.0.0:6002` and `[::]:6002` (Bound to Coolify internal real-time websocket/terminal). |
| **4.3** | JT1078/Video Relay Ports 7910 & 7911 | **PASS** | Active on `0.0.0.0:7910-7911` and `[::]:7910-7911` (Bound to `jt1078-relay`). |
| **5.1** | Coolify HTTPS Access (`coolify.raadsystems.tech`) | **FAIL** | Returns `HTTP 503 Service Unavailable`. Domain has DNS pointing to VPS, but Traefik has no router configured for Coolify FQDN. |
| **5.2** | Coolify Port 8000 Public Exposure | **FAIL** | Port 8000 is open in Hostinger Firewall (`357633`) and serves cleartext HTTP administrative login directly on `http://72.62.7.212:8000`. |
| **6.1** | Alembic Migration Revision State | **PASS** | Current revision is `b2c3d4e5f6a7` (HEAD). Zero unapplied migrations pending. |
| **6.2** | PostgreSQL Checkpoint & WAL Health | **PASS** | Regular checkpoints completing without errors; WAL flush mismatch errors observed previously are completely cleared. |
| **7.1** | Database Backup Schedule & Recency | **PASS** | Backup loop runs every 24h (`BACKUP_INTERVAL_HOURS=24`). Latest dump: `raad_raad_20261105_140202.dump` (3.16 MB, valid TOC with 832 entries). |
| **7.2** | Off-site Backup Mirroring | **WARNING** | `BACKUP_RCLONE_REMOTE` is empty (`""`). All database dumps remain stored strictly on the local host volume. |
| **7.3** | Hostinger Hypervisor Automated Backups | **PASS** | 2 snapshots present in Hostinger data center storage (Latest: Nov 4, 2026, 10.35 GB). |
| **8.1** | Hostinger Subscription & Expiration | **PASS** | Subscription `AzqdlnVYfTklq4k9g` (`KVM 2`) is `active`, auto-renewed, next billing date: Nov 21, 2026. |

---

## 2. Area 1: PostgreSQL 16 Deep Audit

### 2.1 Container & Topology
- **Container Name:** `postgres-m0lhtrori7rbplpzwzilohfz-20261105T140110`
- **Image:** `postgres:16-alpine` (PostgreSQL 16.15)
- **Status:** `Up 23 hours (healthy)`
- **Volume Mount:**
  - `Source`: `/var/lib/docker/volumes/docker_raad_postgres_data/_data`
  - `Destination`: `/var/lib/postgresql/data`
  - `Topology Assessment`: **PASS**. Only one container (`postgres-m0lhtrori7rbplpzwzilohfz-20261105T140110`) references `docker_raad_postgres_data`. The orphaned `raad-postgres` container has been decommissioned.

### 2.2 Connectivity, Connection Pool & Size
- **Database Name:** `raad`
- **Database Size:** `41,917,463` bytes (~40 MB)
- **Active Connections:** 9 connections total (8 idle pool connections from backend/worker, 1 active query)
- **Max Connections:** 100
- **Connection Utilization:** 9.0% (Well within safety margins)

### 2.3 WAL & Checkpoint Health
Inspection of PostgreSQL server logs over the last 24 hours:
```text
2026-11-06 12:37:26.440 UTC [26] LOG:  checkpoint complete: wrote 52 buffers (0.3%); 0 WAL file(s) added, 0 removed, 0 recycled; write=5.142 s, sync=0.005 s, total=5.156 s
2026-11-06 12:57:24.969 UTC [26] LOG:  checkpoint complete: wrote 33 buffers (0.2%); 0 WAL file(s) added, 0 removed, 0 recycled; write=3.214 s, sync=0.006 s, total=3.227 s
```
Zero WAL flush mismatch errors or lock contention issues detected.

---

## 3. Area 2: Redis 7 Deep Audit

### 3.1 Container Health & Responsiveness
- **Container Name:** `redis-m0lhtrori7rbplpzwzilohfz-20261105T140110`
- **Image:** `redis:7-alpine` (Redis 7.4.12)
- **Status:** `Up 23 hours (healthy)`
- **PING Response:** `PONG` (Latency < 1ms)
- **Healthcheck Command:** `redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping`

### 3.2 Memory & Configuration
- **Memory Used (`used_memory_human`):** `26.69 MB`
- **Configured Maximum Memory (`maxmemory_human`):** `1.00 GB`
- **Memory Consumption Ratio:** **2.6%**
- **Maxmemory Policy:** `noeviction`
- **Persistence:** AOF (`appendonly yes`, `appendfsync everysec`)

---

## 4. Area 3: RAAD Application Services Audit

All core services were audited for runtime status, health check implementation, and deployment consistency.

| Service Name | Container Identifier | Runtime State | Healthcheck Status | Port Mappings / Network |
| :--- | :--- | :---: | :---: | :--- |
| **Backend** | `backend-m0lhtrori7rbplpzwzilohfz-20261105T140110` | `Up 23h` | **Healthy** | Internal `8000/tcp`, Traefik ingress `api.raadsystems.tech` |
| **Worker** | `worker-m0lhtrori7rbplpzwzilohfz-20261105T140110` | `Up 23h` | **Healthy** | Internal `8000/tcp`, Celery task processor |
| **Frontend** | `frontend-m0lhtrori7rbplpzwzilohfz-20261105T140110` | `Up 23h` | **Healthy** | Internal `80/tcp`, Traefik ingress `app.raadsystems.tech` |
| **Device Gateway** | `device-gateway-m0lhtrori7rbplpzwzilohfz-20261105T140110` | `Up 23h` | **Healthy** | `0.0.0.0:7808-7809->7808-7809/tcp` |
| **JT1078 Relay** | `jt1078-relay-m0lhtrori7rbplpzwzilohfz-20261105T140110` | `Up 23h` | **Healthy** | `0.0.0.0:7910-7911->7910-7911/tcp`, Traefik `video.raadsystems.tech` |
| **PostgreSQL 16** | `postgres-m0lhtrori7rbplpzwzilohfz-20261105T140110` | `Up 23h` | **Healthy** | Internal `5432/tcp` |
| **Redis 7** | `redis-m0lhtrori7rbplpzwzilohfz-20261105T140110` | `Up 23h` | **Healthy** | Internal `6379/tcp` |
| **Prometheus** | `prometheus-m0lhtrori7rbplpzwzilohfz-20261105T140110` | `Up 23h` | **No Healthcheck** | Internal `9090/tcp` |
| **Backup Service** | `backup-m0lhtrori7rbplpzwzilohfz-20261105T140110` | `Up 23h` | **No Healthcheck** | Internal loop (`/app/backup-loop.sh`) |
| **Migration** | `migrate-m0lhtrori7rbplpzwzilohfz-20261105T140110` | `Exited (0)` | **No Healthcheck** | Ephemeral startup container; executed cleanly |

### Public Health Endpoint Probing
- **API Health:** `GET https://api.raadsystems.tech/health` -> `HTTP 200 OK`, body: `{"status":"ok"}`.
- **Frontend App:** `GET https://app.raadsystems.tech/` -> `HTTP 200 OK` (Nginx 1.27.5).

---

## 5. Area 4: Device Connectivity & Listener Audit

Socket listeners on the host network stack were inspected via `ss -tlpn`:

```text
LISTEN 0      4096         0.0.0.0:7808       0.0.0.0:*    users:(("docker-proxy",pid=2771653,fd=8))
LISTEN 0      4096         0.0.0.0:7809       0.0.0.0:*    users:(("docker-proxy",pid=2771674,fd=8))
LISTEN 0      4096         0.0.0.0:6002       0.0.0.0:*    users:(("docker-proxy",pid=3195255,fd=8))
LISTEN 0      4096         0.0.0.0:7910       0.0.0.0:*    users:(("docker-proxy",pid=2771776,fd=8))
LISTEN 0      4096         0.0.0.0:7911       0.0.0.0:*    users:(("docker-proxy",pid=2771796,fd=8))
```

- **JT808 Ports (7808, 7809):** **ACTIVE (PASS)**. Bound to `device-gateway` container, listening on IPv4 and IPv6.
- **Port 6002:** **ACTIVE (PASS)**. Bound to `coolify` daemon for real-time WebSocket and terminal proxying.
- **JT1078 Video Ports (7910, 7911):** **ACTIVE (PASS)**. Bound to `jt1078-relay` container, listening on IPv4 and IPv6. Traefik reverse proxies `video.raadsystems.tech` to port 7911.

---

## 6. Area 5: Coolify & Ingress Security Audit

### 6.1 Domain Routing & Catchall Behavior
Traefik dynamic configuration contains a catchall router pointing to a no-op service:
```yaml
http:
  routers:
    catchall:
      rule: PathPrefix(`/`)
      service: noop
```
Any request hitting Traefik that does not match an explicit container router label receives `503 Service Unavailable`.

### 6.2 Findings
1. **`https://coolify.raadsystems.tech`:** **FAIL**.
   - DNS points `coolify.raadsystems.tech` to `72.62.7.212`.
   - The Coolify instance itself has no Traefik routing labels attached.
   - External requests to `https://coolify.raadsystems.tech` hit the catchall and return `HTTP 503 Service Unavailable`.
2. **Cleartext Port 8000 Exposure:** **FAIL / SECURITY RISK**.
   - The Coolify web UI is exposed directly via Docker port binding `0.0.0.0:8000->8080/tcp`.
   - Hostinger Firewall Group `RAAD Production` (`357633`) permits inbound TCP port `8000` from `any` IP.
   - The Coolify admin login interface is currently reachable over cleartext HTTP at `http://72.62.7.212:8000`.

---

## 7. Area 6: Database Safety & Schema Status

### 7.1 Alembic Version State
Inspection of the production PostgreSQL database:
```sql
SELECT version_num FROM alembic_version;
```
- **Recorded Database Version:** `b2c3d4e5f6a7`
- **Alembic HEAD in Backend Image:** `b2c3d4e5f6a7 (head)`
- **Pending Migrations:** **0 (Zero)**.
- **Status:** **PASS**. The database schema is fully aligned with the codebase HEAD revision (`20261105_1200_b2c3d4e5f6a7_data_transfer_import_batches.py`).

### 7.2 Data Integrity & Volume Exclusivity
- Volume `docker_raad_postgres_data` is mounted exclusively by `postgres-m0lhtrori7rbplpzwzilohfz-20261105T140110`.
- Sequential table reads and PostgreSQL catalog inspections show zero relation naming collisions or orphan processes.

---

## 8. Area 7: Backup Schedule & Verification

### 8.1 Automated Backup Service
- **Execution Script:** `/app/backup-loop.sh`
- **Schedule:** Runs on container startup and repeats every 24 hours (`BACKUP_INTERVAL_HOURS=24`).
- **Retention Period:** 14 days (`BACKUP_RETENTION_DAYS=14`).
- **Latest Backup Dump:**
  - File: `raad_raad_20261105_140202.dump`
  - Created: `2026-11-05 14:02:02 UTC`
  - File Size: `3,159,846` bytes (~3.16 MB)
  - Next Automated Execution: `2026-11-06 14:02:02 UTC` (~within the hour).
- **TOC Verification:** A non-destructive `pg_restore -l` check completed successfully, reading 832 schema and data TOC entries with valid gzip compression.

### 8.2 Off-Site Backup Gap
- Environment variable `BACKUP_RCLONE_REMOTE` is currently unconfigured (`""`).
- **Status:** **WARNING**. Backups reside solely on local disk storage in `/var/lib/docker/volumes/m0lhtrori7rbplpzwzilohfz_raad-backups-data/_data/`. A disk or VPS catastrophic failure would risk backup availability.
- *Mitigation in place:* Hostinger hypervisor-level snapshot exists in the France data center (last taken Nov 4, 2026).

---

## 9. Prioritized Remediation Plan

*(All proposed actions are advisory only; no modifications have been executed).*

### Priority 1: High Security Risk — Secure Coolify Administrative Ingress
1. **Configure Coolify FQDN:** In Coolify Settings (`General`), assign the custom FQDN `https://coolify.raadsystems.tech`. This will instruct Traefik to issue a Let's Encrypt TLS certificate and proxy HTTPS traffic securely to Coolify.
2. **Close Port 8000 on Hostinger Firewall:** Once HTTPS routing via Traefik is confirmed, remove port `8000` from Hostinger Firewall Group `357633` (or restrict it to trusted administrative CIDR blocks only) to eliminate cleartext HTTP exposure of the PaaS panel.

### Priority 2: Reliability & Disaster Recovery — Enable Off-Site Backup Mirroring
1. **Configure Rclone Remote:** Provision an S3-compatible bucket (e.g., Cloudflare R2, AWS S3, or Backblaze B2) and set `BACKUP_RCLONE_REMOTE` in the Coolify environment configuration for application `m0lhtrori7rbplpzwzilohfz`.
2. **Verify Backup Offloading:** Confirm that `scripts/db/backup.sh` uploads daily dumps to the remote bucket after local creation.

### Priority 3: Observability — Add Docker Healthchecks for Ancillary Services
1. **Prometheus:** Add an HTTP healthcheck in `docker-compose.yml` (`wget -q -O - http://localhost:9090/-/healthy || exit 1`).
2. **Backup Service:** Add a container healthcheck verifying process liveness or dump file recency.

### Priority 4: Web Ingress — Apex Domain Redirect
1. **Configure Apex Redirect:** Configure Traefik / Coolify to redirect requests from `raadsystems.tech` to `https://app.raadsystems.tech` rather than returning `503 Service Unavailable`.
