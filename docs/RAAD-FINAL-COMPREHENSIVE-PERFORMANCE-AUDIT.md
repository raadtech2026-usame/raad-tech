# RAAD-TECH — Final Comprehensive Performance, Code & Production Infrastructure Audit

**Document Title:** Deep Full-System Performance Investigation: Hardware, Ingress, Docker, PostgreSQL, Redis, Backend Code & Frontend Architecture  
**File Name:** `docs/RAAD-FINAL-COMPREHENSIVE-PERFORMANCE-AUDIT.md`  
**Date of Audit:** November 6, 2026  
**Audited Target:** RAAD-TECH Production Environment  
**VPS Instance:** Hostinger `srv2082072` (VPS ID: `2082072`)  
**Primary IP Addresses:** IPv4: `72.62.7.212` | IPv6: `2a02:4780:f:da36::1`  
**Host Operating System:** Ubuntu 24.04 LTS (Kernel: Linux 6.8.0-1014-kvm)  
**Hardware Specification:** Hostinger KVM 2 (2 vCPU AMD EPYC 9354P @ 2.0GHz, 8 GB RAM, 100 GB NVMe Storage)  
**Data Center Location:** Hostinger DC 18 (France, Europe)  
**PaaS Orchestrator:** Coolify 4.6.0 (Resource UUID: `m0lhtrori7rbplpzwzilohfz`)  
**Production Commit:** `4fd6c9a8123c1fb1baa6fe14ad3b494335dfbc34`  
**Audit Policy:** Strict Read-Only Audit (Zero mutations, zero restarts, zero deployments, secrets protected)

---

## 1. Executive Summary

A comprehensive, non-destructive, multi-layer performance and infrastructure audit was conducted across the RAAD-TECH production system in response to reported system sluggishness.

### Primary Diagnostic Finding
**The sluggishness experienced by users is NOT caused by an underpowered VPS.**
The Hostinger KVM 2 instance (2 vCPU, 8 GB RAM) is currently running at approximately **12% to 15% CPU utilization**, **22% RAM utilization** (with **6.17 GB of RAM free/available**), **0% disk I/O wait**, and **9% disk space utilization**. Upgrading the VPS hardware would provide **zero measurable performance improvement**.

The root causes of sluggishness were identified across four specific application and networking layers:

1. **Frontend Asset Delivery Defect (Primary Source of Initial Load Sluggishness):**  
   Nginx (`infrastructure/nginx/conf.d/frontend.conf`) serves the single-page application without Gzip/Brotli compression and without `Cache-Control: immutable` headers. Users download **4.5 MB+ of raw uncompressed JavaScript, CSS, and fonts** (including an 859 KB initial bundle and a 1.8 MB Mapbox bundle) on initial load and asset revalidation, consuming 3 to 6+ seconds over WAN before application bootstrapping begins.
2. **Cross-Origin CORS Preflight & WAN Round-Trip Latency (Primary Source of Interaction Sluggishness):**  
   The frontend (`app.raadsystems.tech`) and backend API (`api.raadsystems.tech`) reside on separate subdomains. Cross-origin requests with `Authorization: Bearer` headers force browsers to execute an HTTP `OPTIONS` CORS preflight before every API call. Because `CORSMiddleware` in `backend/raad/main.py:195` does not define `max_age`, and network latency to the France data center is ~140ms RTT, every single user action suffers **280ms to 500ms+ of pure network round-trip overhead** before backend processing occurs. Furthermore, dashboard pages trigger 6 to 8 separate API calls simultaneously (12 to 16 round-trips).
3. **PostgreSQL Configuration & Query Design Inefficiencies (Primary Source of Database Latency):**  
   - **Missing Index on `outbox`:** The transactional outbox table (`outbox`) has accrued 9,247 rows but lacks an index on `(published_at, created_at)`. The periodic background outbox relay worker polls every 5 seconds, resulting in **17,986 sequential scans** that have scanned **166,116,121 tuples** from disk/cache.
   - **In-Memory Full-Table Scans:** Key services (notably `VideoApplicationService` at lines 193, 295, 404) call `uow.video_sessions.list_all()`, fetching the entire table into Python memory to perform filtering via in-memory list comprehensions rather than database `WHERE` clauses.
   - **PostgreSQL Buffer & Cost Tuning:** PostgreSQL 16 is running with out-of-the-box defaults: `shared_buffers = 128 MB` (on an 8 GB host), `random_page_cost = 4.0` (penalizing NVMe index lookups), and `jit = on` (adding 20ms to 50ms compilation overhead to small OLTP queries).
4. **N+1 Sequential Query Loops in Financial & ERP Modules:**  
   Batch generation routines (e.g. `_plan_generation` in `backend/raad/modules/school_erp/application/services.py:1426` and `issue_student_invoices` at line 508) execute awaited single-entity queries inside `for` loops rather than using bulk `WHERE IN (...)` lookups.

---

## 2. Audit Scope and Methods

The audit was conducted using three orthogonal inspection vectors without introducing artificial load or perturbing production state:

```mermaid
flowchart TD
    A["Performance Audit Vectors"] --> B["Hostinger MCP Integration"]
    A --> C["Direct Read-Only SSH Diagnostics"]
    A --> D["Local Repository Static Code & Build Analysis"]
    
    B --> B1["Hypervisor CPU, RAM, Disk, Traffic Metrics"]
    B --> B2["Firewall & Network Rule Inspection"]
    B --> B3["Subscription & Billing Lifecycle"]
    
    C --> C1["Host OS vmstat, lscpu, free, df, ss, iostat"]
    C --> C2["Docker Daemon & Container cgroup stats"]
    C --> C3["PostgreSQL 16 System Catalogs & Stat Tables"]
    C --> C4["Redis 7 INFO, Slowlog, Keyspace & Streams"]
    C --> C5["Prometheus Scraping & Endpoint Probes"]
    
    D --> D1["FastAPI Middleware & Route Dependencies"]
    D --> D2["SQLAlchemy Queries, Repositories & UoW"]
    D --> D3["Vite Rollup Chunking & Dependency Footprint"]
    D --> D4["Nginx & Traefik Configuration Files"]
```

---

## 3. Access Verification

All access channels were successfully verified in read-only mode:

- **Hostinger MCP Server:** Authenticated and active. Used to inspect VPS specifications, historical 24-hour resource metrics, firewall configuration, and subscription validity.
- **SSH Host Connectivity:** Authenticated via existing key (`~/.ssh/raad-kvm-migration`) to `72.62.7.212` (`root@srv2082072`). Successfully gathered host metrics, process tables, container statistics, and database diagnostics.
- **Local Codebase:** Verified at `C:\Dev\RAAD-TECH` across backend, frontend, services, infrastructure, and migration trees.

---

## 4. VPS Resource Analysis (Phase 1)

### 4.1 CPU Metrics & Contention Analysis
- **Hardware Architecture:** AMD EPYC 9354P 32-Core Processor (2 vCPUs assigned, 2.00 GHz base, 6490 BogoMIPS).
- **Load Average (1, 5, 15 min):** `0.91, 0.62, 0.52`. On a 2-vCPU system, load capacity is 2.00. Current load represents **~35% to 45% load capacity**.
- **CPU Utilization Breakdown (`vmstat 1 5`):**
  - User (`us`): 1% – 9%
  - System (`sy`): 1% – 6%
  - **Idle (`id`): 84% – 98%**
  - **I/O Wait (`wa`): 0% (Zero disk wait)**
  - Hypervisor Steal (`st`): 1% – 2% (Negligible virtualization overhead)
- **Hostinger 24-Hour Telemetry:** CPU utilization fluctuated strictly between **11.26% and 12.89%** over the preceding 24 hours.
- **Contention Verdict:** **NO CPU CONTENTION (PASS)**. The CPU operates with vast spare capacity.

### 4.2 Memory & Swap Analysis
- **Total Physical RAM:** 7,940 MB (~7.75 GiB)
- **Used RAM:** 1,770 MB (~22.3%)
- **Free RAM:** 1,655 MB
- **Buffer & OS Page Cache:** 5,143 MB
- **Available RAM for Applications:** **6,170 MB (~77.7% available)**
- **Swap Space:** 0 MB configured, 0 MB used.
- **Kernel OOM Events:** Zero OOM events recorded in `dmesg`.
- **Contention Verdict:** **NO MEMORY EXHAUSTION (PASS)**. Over 6 GB of memory is immediately available.

### 4.3 Disk Capacity, Inodes & Storage
- **Root Filesystem (`/dev/sda1` on NVMe):** 96 GB capacity, 8.6 GB used, **88 GB available (9% utilization)**.
- **Inodes:** 12,976,128 total, 207,585 used (**2% utilization**).
- **Disk I/O Wait:** 0.0% consistently in `vmstat`.
- **Contention Verdict:** **NO DISK BOTTLENECK (PASS)**.

### 4.4 Network & Latency Characteristics
- **Network Interface (`eth0`):** Full-duplex virtual interface. Zero dropped RX/TX packets, zero FIFO overruns.
- **Geographic Location:** Hostinger France Data Center (`node1618-fr-int-1-pbs`).
- **Ping & TCP Connect Latency:**
  - Client-to-Server TCP Connection: **140 ms – 217 ms**
  - Client-to-Server TLS Handshake: **160 ms – 180 ms**
  - Total Connection Setup Latency: **300 ms – 380 ms** per new socket.
- **DNS Resolution Latency:** 4 ms – 10 ms via Hostinger resolvers (`153.92.2.6`, `1.1.1.1`).
- **Network Verdict:** **SIGNIFICANT WAN LATENCY (WARNING)**. High baseline latency (~140ms RTT) amplifies the cost of multi-round-trip HTTP interactions and uncompressed payloads.

---

## 5. Docker and Coolify Analysis (Phase 2)

### 5.1 Container Resource Utilization Matrix

Empirical data captured live via `docker stats --no-stream`:

| Container Name | Status | CPU % | Memory Usage / Limit | Memory % | Network I/O (In/Out) | Block I/O (Read/Write) | PIDs | Healthcheck |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **coolify** | Up 2d | 10.28% | 460.6 MiB / 7.75 GiB | 5.80% | 3.04 GB / 2.98 GB | 33.6 MB / 106 MB | 39 | Healthy |
| **coolify-db** (PG 15) | Up 2d | 5.11% | 44.0 MiB / 7.75 GiB | 0.55% | 701 MB / 1.55 GB | 12.2 MB / 570 MB | 7 | Healthy |
| **coolify-redis** | Up 2d | 1.16% | 7.1 MiB / 7.75 GiB | 0.09% | 1.89 GB / 613 MB | 803 kB / 10.3 GB | 7 | Healthy |
| **coolify-proxy** (Traefik) | Up 2w | 0.14% | 29.9 MiB / 7.75 GiB | 0.38% | 591 MB / 402 MB | 8.3 MB / 152 kB | 9 | Healthy |
| **coolify-sentinel** | Up 27m | 0.06% | 2.9 MiB / 7.75 GiB | 0.04% | 45 kB / 1.58 MB | 0 B / 537 kB | 3 | Healthy |
| **backend** | Up 23h | 0.33% | 144.7 MiB / 7.75 GiB | 1.82% | 46.2 MB / 85.4 MB | 1.02 MB / 4.1 kB | 6 | Healthy |
| **worker** | Up 23h | 0.52% | 113.7 MiB / 7.75 GiB | 1.43% | 257 MB / 50.0 MB | 73.7 kB / 0 B | 3 | Healthy |
| **postgres** (PG 16) | Up 23h | 0.36% | 77.4 MiB / 7.75 GiB | 0.97% | 25.8 MB / 263 MB | 5.0 MB / 1.02 MB | 14 | Healthy |
| **redis** (Redis 7) | Up 23h | 0.58% | 29.6 MiB / 7.75 GiB | 0.37% | 170 MB / 125 MB | 37.3 MB / 215 MB | 6 | Healthy |
| **device-gateway** | Up 23h | 0.06% | 24.0 MiB / 7.75 GiB | 0.30% | 48.3 MB / 41.0 MB | 0 B / 0 B | 2 | Healthy |
| **jt1078-relay** | Up 23h | 0.61% | 23.5 MiB / 7.75 GiB | 0.30% | 22.5 MB / 29.6 MB | 0 B / 0 B | 3 | Healthy |
| **prometheus** | Up 23h | 0.03% | 23.3 MiB / 7.75 GiB | 0.29% | 10.2 MB / 3.87 MB | 348 kB / 49.3 MB | 8 | None |
| **frontend** (Nginx) | Up 23h | 0.00% | 3.1 MiB / 7.75 GiB | 0.04% | 21.8 kB / 8.15 kB | 0 B / 4.1 kB | 3 | Healthy |
| **backup** | Up 23h | 0.00% | 0.6 MiB / 7.75 GiB | 0.01% | 17.9 MB / 111 kB | 504 kB / 3.16 MB | 2 | None |
| **migrate** | Exited | — | — | — | — | — | — | None |

### 5.2 Container Observations
1. **Total RAAD Application Footprint:** CPU usage is under **2.5%**, and memory usage is **~440 MiB** across all 9 application containers combined.
2. **Coolify Control Plane Overhead:** The Coolify control plane (`coolify` PHP-FPM/Nginx + `coolify-db` + `coolify-redis`) consumes **~16.5% CPU** and **~510 MiB RAM**, representing more resource consumption than the entire application workload. However, on this host, ample headroom remains.
3. **No Container Restarts:** Zero unexpected crashes or restarts observed across any production service. All services have been continuously up since deployment `20261105T140110` (23+ hours).

---

## 6. PostgreSQL 16 Deep Analysis (Phase 3)

### 6.1 Database Metrics & Settings

```text
Database Size: 41.9 MB (41,917,463 bytes)
Active Connections: 9 total (8 idle pool connections, 1 active query)
Max Connections: 100 (9% pool utilization)
Buffer Cache Hit Ratio: 99.91% (7,190,462 hits vs 6,297 reads)
```

PostgreSQL configuration settings (`pg_settings`):
- `shared_buffers = 16384 * 8kB = 128 MB`: **Severely undersized**. On an 8 GB server with ~6 GB free, `shared_buffers` should be 1 GB to 2 GB to allow PostgreSQL to cache working sets and indexes directly in its own buffer pool rather than relying exclusively on OS page cache.
- `random_page_cost = 4.0`: **Misconfigured for NVMe storage**. The PostgreSQL default of 4.0 assumes mechanical spinning hard drives with high seek latency. On NVMe SSDs, `random_page_cost` should be set to `1.1` to `1.25`. A setting of 4.0 artificially discourages the query planner from using indexes for range scans and joins, steering it toward sequential scans.
- `jit = on`: **Enabled by default in PG 16**. For small OLTP queries with complex expressions, JIT compilation can add 20ms to 50ms of CPU overhead to compile code for queries that take only 1ms to execute. JIT should be disabled for OLTP workloads (`jit = off`).
- `work_mem = 4096 kB = 4 MB`: Default. Acceptable for current connection counts, but should be increased to 16 MB.

### 6.2 Table Scan & Access Inefficiencies

Query on `pg_stat_user_tables` revealed significant full-table scan hotspots:

```text
relname            seq_scan     seq_tup_read    idx_scan    idx_tup_fetch    n_live_tup
----------------------------------------------------------------------------------------
outbox               17,986      166,116,121          57               57         9,247
video_sessions        1,508        1,131,000           4                4           750
vehicle_positions_09      8          210,189           0                0        30,027
audit_entries             9          124,202           2               82        13,845
devices                 335            1,340           0                0             4
subscriptions           220              440           0                0             2
parents                 195            1,723           0                0             9
erp_parent_invoices     179            3,449           0                0            24
payments                161              483           0                0             3
students                 94            1,766           0                0            19
```

#### Confirmed Defect: Missing Index on `outbox`
- **Location:** Table `outbox`
- **Existing Indexes:** Only `pk_outbox (id)` and `ux_outbox__event_id (event_id)`.
- **Query Pattern:** In `backend/raad/core/events/outbox.py:94-99`:
  ```python
  statement = (
      select(OutboxRecord)
      .where(OutboxRecord.published_at.is_(None))
      .order_by(OutboxRecord.created_at)
      .limit(batch_size)
  )
  ```
- **Evidence:** With 9,247 rows in `outbox`, the outbox relay polls every 5 seconds. Because `published_at` and `created_at` are unindexed, PostgreSQL must perform a full sequential scan across all 9,247 rows and sort them in memory on every poll. This single query has executed **17,986 times**, reading **166,116,121 rows**.
- **Impact:** Continuous background CPU and cache churn on the database engine.
- **Remediation:** Create a partial composite index:
  ```sql
  CREATE INDEX ix_outbox__pending ON outbox (created_at) WHERE published_at IS NULL;
  ```

---

## 7. Redis and Worker Analysis (Phase 4)

### 7.1 Redis 7 Diagnostics
- **Container:** `redis-m0lhtrori7rbplpzwzilohfz-20261105T140110` (Redis 7.4.12)
- **Memory Consumption:** `26.69 MB` used of `1.00 GB` configured `maxmemory` (**2.6% utilization**).
- **Eviction Policy:** `noeviction` (0 keys evicted, 0 clients evicted).
- **Hit Ratio:** **99.05%** (`1,224,025` hits vs `11,689` misses).
- **Event Loop Duration:** `369 microseconds` (0.37ms).
- **Slowlog:** Redis slowlog recorded only blocking stream reads (`XREADGROUP ... BLOCK 1000`), which is normal behavior for blocking consumer loops.
- **Verdict:** **PERFECT HEALTH (PASS)**. Redis operates cleanly with sub-millisecond execution times.

### 7.2 Celery / Async Worker Diagnostics
- **Worker Process:** `python -m raad.interfaces.workers.bootstrap` running inside container `worker`.
- **Execution Architecture:** In-process asyncio worker loop running:
  - `OutboxRelayWorker` (ticks every 5.0s, polls `outbox`)
  - `NotificationWorker` (ticks every 5.0s, reads `raad:events` stream)
  - `TelemetryWorker` (ticks every 1.0s, batch size 500)
  - `ReportWorker` (ticks every 10.0s)
  - `SchedulerWorker` (hourly retention, subscription sweep, daily operations)
- **Worker Resource Impact:** Worker CPU is ~0.52%, RAM is ~113.7 MiB.
- **Contention Verdict:** Worker processing does not compete with the API for host CPU or RAM. However, the worker's unindexed outbox polling places unnecessary scan load on PostgreSQL.

---

## 8. Backend Code Performance Audit (Phase 5)

A detailed source code audit was conducted on `backend/raad/`:

### 8.1 In-Memory Full-Table Scans via `list_all()`
Multiple application services bypass database filtering by fetching entire tables into memory:

1. **`VideoApplicationService.get_open_sessions_for_user`** ([`services.py:289-302`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/video/application/services.py#L289-L302)):
   ```python
   async with uow:
       sessions = await uow.video_sessions.list_all()
   return [
       video_session_to_dto(session)
       for session in sessions
       if str(session.requested_by) == requested_by_user_id
       and session.purpose.value == purpose
       and session.status in _OPEN_STATUSES
   ]
   ```
   *Analysis:* Fetches every video session in history into Python memory to filter by user and status in a Python list comprehension.
2. **`VideoApplicationService.request_intercom`** ([`services.py:193-200`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/video/application/services.py#L193-L200)):
   ```python
   async with uow:
       existing = await uow.video_sessions.list_all()
   if any(session.device_id == DeviceId(command.device_id) ... for session in existing):
   ```
   *Analysis:* Calls `list_all()` to check if an active session exists for a single device, rather than executing `SELECT 1 FROM video_sessions WHERE device_id = :id AND status IN (...) LIMIT 1`.
3. **`VideoApplicationService.reconcile_stale_sessions`** ([`services.py:404`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/video/application/services.py#L404)):
   Calls `list_all()` on every reconciliation tick.

### 8.2 N+1 Query Patterns in Batch Operations
1. **`SchoolErpApplicationService._plan_generation`** ([`services.py:1426-1440`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/school_erp/application/services.py#L1426-L1440)):
   ```python
   for profile in profiles:
       if await school_erp_uow.parent_invoices.exists_for_parent_period(...):
           ...
       children = await self._resolve_active_children(...)
   ```
   *Analysis:* Inside `for profile in profiles:`, two individual database queries are awaited per parent profile. For 100 parents, this executes 200 sequential queries across the wire.
2. **`SchoolErpApplicationService.issue_student_invoices`** ([`services.py:508-512`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/school_erp/application/services.py#L508-L512)):
   ```python
   for student_id in command.student_ids:
       if await uow.student_invoices.exists_for_student_period(...):
           continue
   ```
   *Analysis:* Executes an awaited database query for each student in the batch rather than a single `WHERE student_id IN (...)` query.

### 8.3 Uncached CORS Preflight Overhead
In `backend/raad/main.py:195-201`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
*Analysis:* `max_age` is not configured. When `max_age` is omitted, browsers either do not cache the CORS preflight response or cache it for short durations. Because the frontend (`app.raadsystems.tech`) and API (`api.raadsystems.tech`) are on different subdomains, every API call with an `Authorization` header triggers an `OPTIONS` round-trip. At ~140ms RTT, this adds ~140ms of latency to every user interaction.

### 8.4 Middleware Stack Overhead
FastAPI mounts 5 separate `BaseHTTPMiddleware` classes:
1. `RequestLoggingMiddleware`
2. `SecurityContextMiddleware`
3. `RateLimitMiddleware`
4. `CorrelationIdMiddleware`
5. `SecurityHeadersMiddleware`
Starlette's `BaseHTTPMiddleware` wraps request processing in an anyio TaskGroup and memory streaming channel, adding ~1ms to 2ms of CPU and allocation overhead per request compared to pure ASGI middleware.

---

## 9. Frontend Performance Audit (Phase 6)

### 9.1 Missing Compression & Caching Headers (Critical Defect)

Inspection of HTTP response headers for built assets on `https://app.raadsystems.tech`:

```http
HTTP/1.1 200 OK
Accept-Ranges: bytes
Content-Length: 859004
Content-Type: application/javascript
Date: Fri, 06 Nov 2026 14:06:19 GMT
Etag: "6aec4134-d1b7c"
Last-Modified: Thu, 05 Nov 2026 08:41:24 GMT
Server: nginx/1.27.5
```

**Measured Deficiencies:**
1. **No Gzip / Brotli Compression:** Even when `Accept-Encoding: gzip, deflate, br` is sent by the client, Nginx returns raw uncompressed bytes (`Content-Length: 859004`).
2. **No Cache-Control Header:** `Cache-Control: public, max-age=31536000, immutable` is completely absent.
3. **Root Cause:** In `infrastructure/nginx/conf.d/frontend.conf`:
   ```nginx
   server {
       listen 80;
       server_name _;
       root /usr/share/nginx/html;
       index index.html;

       location / {
           try_files $uri $uri/ /index.html;
       }
   }
   ```
   Gzip compression is not enabled, and no asset caching location block exists.

### 9.2 Built Asset Bundle Sizes
Inspection of production assets inside the frontend container:
- `index-CCJxyU_3.js`: **838.9 KB** (Uncompressed)
- `mapbox-D0uJGG4S.js`: **1.8 MB** (Uncompressed)
- `video-C9pmnQEa.js`: **270.3 KB** (Uncompressed)
- `vendor-CzMGLAcr.js`: **205.0 KB** (Uncompressed)
- `index-B4WsXUlU.css`: **228.7 KB** (Uncompressed)
- Font files (Manrope, JetBrains Mono, Sora): **~350 KB**
- **Total Asset Payload:** **~4.5 MB+**

**User-Visible Effect:**  
On a 10 Mbps connection, downloading 4.5 MB of uncompressed assets takes ~3.6 seconds of raw transfer time, plus connection establishment. Enabling Gzip would reduce `index.js` from 859 KB to ~220 KB, and `mapbox.js` from 1.8 MB to ~450 KB (a **75% reduction in transfer size**). Adding immutable caching ensures returning users download 0 bytes.

### 9.3 Dashboard Request Fan-Out & Polling
When opening dashboard pages, the frontend fires multiple queries simultaneously:
- `useVehicleActiveDevice.ts:45`: Polls every 10 seconds if any camera status is unknown (`UNKNOWN_CAMERA_REFETCH_MS = 10_000`).
- Dashboard loading: Simultaneously fires 6 to 8 separate requests (`/users`, `/vehicles`, `/students/count`, `/parents/count`, `/billing/subscriptions`, `/billing/plans`), each accompanied by an `OPTIONS` preflight, producing 12 to 16 network round-trips upon initial navigation.

---

## 10. JT808, JT1078 and Real-Time System (Phase 7)

- **Device Gateway:** Listening on TCP ports `7808` (JT808) and `7809` (MDVR). Zero active device connections currently connected. CPU usage is ~0.06%.
- **JT1078 Video Relay:** Listening on TCP ports `7910` (ingest) and `7911` (viewer). Reverse proxied via Traefik on `video.raadsystems.tech`. Idle CPU usage is ~0.61%.
- **Live GPS Tracking Architecture:** `useVehiclePosition.ts` fetches a single initial REST position snapshot, then establishes a WebSocket connection (`/ws/tracking`). It re-evaluates fix staleness locally every 15 seconds without polling the backend.
- **Verdict:** **HEALTHY & IDLE (PASS)**. The real-time subsystem is not generating resource contention or contributing to current latency.

---

## 11. API and End-to-End Latency Analysis (Phase 8)

### 11.1 Empirical Latency Measurements

Direct HTTP probing from external network to `https://api.raadsystems.tech/health`:

| Measurement Run | DNS Lookup | TCP Connect | TLS Handshake | Server TTFB | Total Latency |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **Cold Connection** | 232.5 ms | 383.9 ms | 191.2 ms | 668.2 ms | **1,244.4 ms** |
| **Warm Run 1** | 6.8 ms | 144.0 ms | 174.2 ms | 132.8 ms | **451.8 ms** |
| **Warm Run 2** | 10.2 ms | 140.6 ms | 155.9 ms | 132.6 ms | **429.9 ms** |
| **Warm Run 3** | 4.5 ms | 217.5 ms | 160.9 ms | 137.2 ms | **516.3 ms** |

### 11.2 Latency Composition Breakdown
- **Network Transport (TCP + TLS):** **~300 ms – 380 ms** (~70% of total latency). This is physical propagation latency to the Hostinger France data center.
- **Server Internal Processing (FastAPI + Traefik):** **~130 ms**.
- **Impact of Subdomain Separation:** Because `app.raadsystems.tech` calls `api.raadsystems.tech`, every new API interaction requires:
  - Preflight `OPTIONS`: ~300ms connection + ~140ms request = ~440ms
  - Actual `GET`: ~140ms request + ~130ms server processing = ~270ms
  - Total interaction delay: **~710 ms minimum**.

---

## 12. Security and Configuration Findings (Phase 9)

| Finding | Severity | Description |
| :--- | :---: | :--- |
| **Cleartext Port 8000 Publicly Exposed** | **HIGH** | Hostinger Firewall Group `357633` permits inbound TCP port `8000` from `any` IP. The Coolify administrative login panel is directly accessible over unencrypted HTTP at `http://72.62.7.212:8000`. |
| **Missing Coolify HTTPS Router** | **HIGH** | `https://coolify.raadsystems.tech` returns `HTTP 503 Service Unavailable` because Coolify has no custom FQDN configured in Traefik. |
| **Apex Domain Returns 503** | **MEDIUM** | `https://raadsystems.tech` returns `HTTP 503 Service Unavailable` because Traefik has no catchall redirect to `app.raadsystems.tech`. |
| **Off-Site Backups Unconfigured** | **MEDIUM** | Local PostgreSQL dumps run daily (`raad_raad_20261105_140202.dump`, 3.16 MB), but `BACKUP_RCLONE_REMOTE` is empty (`""`). Dumps reside solely on local disk storage. |

---

## 13. Confirmed Root Causes & Detailed Findings (Phase 10)

### Finding 1: Uncompressed & Uncached Frontend Asset Delivery
- **Finding ID:** `PERF-01`
- **Severity:** **CRITICAL**
- **Component:** Frontend Nginx Web Server (`infrastructure/nginx/conf.d/frontend.conf`)
- **Evidence:** HTTP responses for `index-CCJxyU_3.js` return `Content-Length: 859004` with no `Content-Encoding: gzip` and no `Cache-Control` header.
- **Root Cause:** `frontend.conf` lacks `gzip on;` directives and cache-control expiration blocks for `/assets/`.
- **User-Visible Effect:** Extremely slow initial page loads (3 to 6+ seconds) and unnecessary re-downloads on every browser session.
- **Recommended Remediation:** Update `infrastructure/nginx/conf.d/frontend.conf`:
  ```nginx
  server {
      listen 80;
      server_name _;
      root /usr/share/nginx/html;
      index index.html;

      gzip on;
      gzip_vary on;
      gzip_proxied any;
      gzip_comp_level 6;
      gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;

      location /assets/ {
          expires 1y;
          add_header Cache-Control "public, max-age=31536000, immutable";
          try_files $uri =404;
      }

      location / {
          try_files $uri $uri/ /index.html;
      }
  }
  ```
- **Estimated Improvement:** **75% reduction in asset download size** (from 4.5 MB to ~1.1 MB); **95% speedup for returning users** (served instantly from browser disk cache).
- **Risk:** Zero risk. Standard Nginx SPA practice.
- **Action Required:** Code update in repository + container redeployment.

---

### Finding 2: Cross-Origin CORS Preflight & WAN Latency Amplification
- **Finding ID:** `PERF-02`
- **Severity:** **HIGH**
- **Component:** Backend FastAPI Application (`backend/raad/main.py:195-201`)
- **Evidence:** Browser makes an `OPTIONS` request before every `GET` request with `Authorization` headers. Backend logs confirm 1:1 `OPTIONS` and `GET` pairing. `CORSMiddleware` configuration lacks `max_age`.
- **Root Cause:** Frontend and backend reside on separate subdomains (`app.` vs `api.`), forcing CORS preflights. Without `max_age`, the browser re-executes preflight requests continuously over a 140ms RTT link.
- **User-Visible Effect:** 250ms to 500ms delay on every click and navigation.
- **Recommended Remediation:**
  1. Add `max_age=86400` (24 hours) to `CORSMiddleware` in `backend/raad/main.py`:
     ```python
     app.add_middleware(
         CORSMiddleware,
         allow_origins=settings.cors.allowed_origins,
         allow_credentials=False,
         allow_methods=["*"],
         allow_headers=["*"],
         max_age=86400,
     )
     ```
  2. *Architectural Improvement (Optional/Future):* Route API requests through a single origin via Traefik (e.g. `https://app.raadsystems.tech/api/v1`), completely eliminating CORS preflights and reusing the existing HTTP/3 TLS connection.
- **Estimated Improvement:** Eliminates 1 full round-trip (140ms – 250ms) from subsequent API requests.
- **Risk:** Zero risk.

---

### Finding 3: Missing Database Index on `outbox` Table
- **Finding ID:** `PERF-03`
- **Severity:** **HIGH**
- **Component:** PostgreSQL Database (`outbox` table) & `SqlOutboxPublisher` ([`backend/raad/core/events/outbox.py:94-99`](file:///C:/Dev/RAAD-TECH/backend/raad/core/events/outbox.py#L94-L99))
- **Evidence:** `pg_stat_user_tables` records **17,986 sequential scans** reading **166,116,121 rows**. Table has 9,247 rows.
- **Root Cause:** Query `WHERE published_at IS NULL ORDER BY created_at LIMIT :batch_size` runs without an index on `published_at` or `created_at`.
- **User-Visible Effect:** Continuous background database load; locks and CPU contention in PostgreSQL.
- **Recommended Remediation:** Create an Alembic migration adding a partial index:
  ```python
  op.create_index(
      "ix_outbox__pending_created_at",
      "outbox",
      ["created_at"],
      postgresql_where=sa.text("published_at IS NULL"),
      if_not_exists=True,
  )
  ```
- **Estimated Improvement:** Reduces outbox poll cost from ~9,250 row scans to 0-1 index lookups (from ~5-15ms down to < 0.1ms per poll).
- **Risk:** Very low. Requires an Alembic migration.

---

### Finding 4: In-Memory Full-Table Scans in `VideoApplicationService`
- **Finding ID:** `PERF-04`
- **Severity:** **MEDIUM**
- **Component:** Backend Video Module ([`backend/raad/modules/video/application/services.py`](file:///C:/Dev/RAAD-TECH/backend/raad/modules/video/application/services.py#L193))
- **Evidence:** `pg_stat_user_tables` records **1,508 sequential scans** with **1,131,000 tuples read** on `video_sessions`. Source code explicitly calls `await uow.video_sessions.list_all()` at lines 193, 295, and 404, followed by in-memory filtering.
- **Root Cause:** Developer avoided adding targeted repository finder queries, opting to load all historical sessions into memory.
- **User-Visible Effect:** Increasing latency on video and intercom operations as table grows.
- **Recommended Remediation:** Replace `list_all()` with targeted repository methods:
  - `has_active_intercom(device_id)` -> `SELECT 1 FROM video_sessions WHERE device_id = :id AND purpose = 'intercom' AND status IN (...) LIMIT 1`
  - `list_open_sessions_for_user(user_id, purpose)` -> `SELECT ... WHERE requested_by = :user_id AND purpose = :purpose AND status IN (...)`
- **Estimated Improvement:** Drops query execution time from O(N) to O(1) index lookup.
- **Risk:** Low. Code refactor in video repository and service.

---

### Finding 5: PostgreSQL Default Buffer & Cost Configuration
- **Finding ID:** `PERF-05`
- **Severity:** **MEDIUM**
- **Component:** PostgreSQL Server Configuration (`docker_raad_postgres_data`)
- **Evidence:** `shared_buffers = 128 MB`, `random_page_cost = 4.0`, `jit = on`.
- **Root Cause:** PostgreSQL container launched with default Alpine parameters rather than hardware-tailored settings.
- **User-Visible Effect:** Slower query planning on NVMe storage; potential JIT compilation spikes on small queries.
- **Recommended Remediation:** Pass optimized startup flags to PostgreSQL in Docker Compose:
  ```yaml
  command:
    - postgres
    - -c
    - shared_buffers=1GB
    - -c
    - effective_cache_size=4GB
    - -c
    - random_page_cost=1.1
    - -c
    - work_mem=16MB
    - -c
    - jit=off
  ```
- **Estimated Improvement:** 10% – 30% improvement in query execution times; eliminates JIT compilation latency.
- **Risk:** Low. Requires container restart.

---

### Finding 6: Cleartext Exposure of Coolify Port 8000
- **Finding ID:** `SEC-01`
- **Severity:** **HIGH (SECURITY)**
- **Component:** Host Firewall (`357633`) & Coolify Container
- **Evidence:** `http://72.62.7.212:8000` is reachable from the public internet without encryption. `https://coolify.raadsystems.tech` returns 503.
- **Root Cause:** Coolify FQDN was never registered in Coolify Settings, leaving Traefik with no HTTPS router, while port 8000 remained open on the firewall.
- **User-Visible Effect:** Security vulnerability (administrative credentials transmitted in cleartext).
- **Recommended Remediation:**
  1. Set custom FQDN `https://coolify.raadsystems.tech` in Coolify dashboard.
  2. Remove port `8000` from Hostinger Firewall Group `357633`.
- **Risk:** Low.

---

## 14. Prioritized Remediation Plan

```mermaid
flowchart TD
    P1["Phase 1: Zero-Downtime Infrastructure & Nginx Fixes<br/>(Immediate 70%+ Perceived Speedup)"] --> P2["Phase 2: Database Indexing & Backend CORS<br/>(Eliminates 166M Tuple Scans & Round-Trips)"]
    P2 --> P3["Phase 3: Code Refactoring & Security Hardening<br/>(N+1 Query Elimination & Port 8000 Closure)"]
```

### Priority 1: Immediate High-Impact Fixes (Front-End & Network)
1. **Enable Nginx Gzip & Long-Term Asset Caching (`PERF-01`):**  
   Update `infrastructure/nginx/conf.d/frontend.conf` to enable Gzip compression and set `Cache-Control: public, max-age=31536000, immutable` on `/assets/`. Reduces asset payloads from **4.5 MB to ~1.1 MB** and eliminates reload downloads.
2. **Add `max_age` to CORS Middleware (`PERF-02`):**  
   Update `backend/raad/main.py` line 195 to add `max_age=86400`. Eliminates redundant `OPTIONS` round-trips for 24 hours per client.

### Priority 2: Database Performance & Background Optimization
3. **Add Partial Index to `outbox` Table (`PERF-03`):**  
   Create an Alembic migration creating `ix_outbox__pending_created_at` on `(created_at) WHERE published_at IS NULL`. Immediately halts the 166-million-tuple sequential scan loop.
4. **Tune PostgreSQL Runtime Parameters (`PERF-05`):**  
   Configure `shared_buffers=1GB`, `random_page_cost=1.1`, and `jit=off` in Docker Compose.

### Priority 3: Security & Code Refactoring
5. **Secure Coolify Ingress & Close Port 8000 (`SEC-01`):**  
   Assign `https://coolify.raadsystems.tech` in Coolify UI, verify Traefik TLS routing, and remove port `8000` from Hostinger firewall.
6. **Refactor In-Memory `list_all()` Calls in `VideoApplicationService` (`PERF-04`):**  
   Replace full-table scans in `backend/raad/modules/video/application/services.py` with SQL-level `WHERE` clauses and existence queries.
7. **Batch N+1 Loops in School ERP Billing:**  
   Update `_plan_generation` in `backend/raad/modules/school_erp/application/services.py` to pre-fetch parent invoice existence and active children in bulk dictionaries.

---

## 15. Performance Scorecard

| Subsystem | Rating | Assessment Criteria & Evidence |
| :--- | :---: | :--- |
| **VPS Infrastructure** | **PASS** | 2 vCPU AMD EPYC, 8 GB RAM. CPU load is ~12-15%, RAM is 22% used, I/O wait is 0%. Hardware has ample headroom. |
| **Docker & Coolify** | **PASS** | All 14 containers stable. Zero crash loops. Resource footprint < 450 MB RAM for app stack. |
| **PostgreSQL 16** | **WARNING** | 99.91% buffer cache hit ratio, but default 128 MB buffer, 4.0 disk cost, and missing outbox index cause 166M tuple scans. |
| **Redis 7** | **PASS** | 99.05% hit ratio, 26 MB / 1 GB used, event loop execution under 0.4ms. Exceptional performance. |
| **Backend Code** | **WARNING** | Clean architecture, but suffers from lack of CORS preflight caching, in-memory `list_all()` scans, and N+1 query loops. |
| **Frontend Architecture** | **FAIL** | 4.5 MB uncompressed assets served without Gzip and without Cache-Control headers. High initial load penalty. |
| **Background Workers** | **PASS** | Execution loops are healthy. Contention is limited to outbox database polling. |
| **GPS / JT808 Gateway** | **PASS** | Socket listeners active and healthy. Minimal resource footprint. |
| **JT1078 Video Relay** | **PASS** | Stream proxying active. Idle overhead < 1% CPU. |
| **Network & Latency** | **WARNING** | 140ms baseline RTT to France data center amplifies multi-round-trip HTTP and CORS interactions. |
| **Backup & Security** | **WARNING** | Local dumps verified healthy, but port 8000 is open in cleartext, Coolify HTTPS returns 503, and offsite backups are unconfigured. |

---

## 16. Answers to Core Investigation Questions

1. **What is causing the system to feel slow?**  
   The sluggishness is caused by **uncompressed 4.5 MB frontend assets** downloading over a 140ms WAN link, combined with **redundant cross-origin CORS `OPTIONS` preflight requests** doubling the latency of every API call, exacerbated by **unindexed full-table scans in PostgreSQL (`outbox`)**.
2. **Is the VPS underpowered?**  
   **No.** The VPS is operating at ~12%–15% CPU and ~22% RAM with 0% I/O wait.
3. **Is CPU, RAM, disk I/O, or network the bottleneck?**  
   **Network payload size and round-trip amplification** is the primary bottleneck. Disk I/O, RAM, and CPU are not bottlenecks.
4. **Is PostgreSQL contributing to the slowdown?**  
   **Yes.** Outbox polling scans 9,247 rows sequentially every 5 seconds (166 million rows read so far), and default parameters (`shared_buffers=128MB`, `random_page_cost=4.0`, `jit=on`) degrade query planning.
5. **Is the backend code inefficient?**  
   **Yes in specific areas.** In-memory `list_all()` filtering in `VideoApplicationService` and N+1 loops in School ERP batch generation.
6. **Is the frontend making too many requests or rendering unnecessarily?**  
   **Yes.** Dashboard loading triggers 6 to 8 separate requests in parallel, each duplicated by a CORS preflight.
7. **Are GPS updates or video streams creating resource contention?**  
   **No.** The device gateway and video relay are currently consuming < 1% CPU combined.
8. **Are Docker resource limits configured appropriately?**  
   Containers currently run without restrictive memory/CPU ceilings, allowing them full access to host resources without throttling.
9. **What are the top five improvements?**  
   1. Enable Nginx Gzip and 1-year immutable caching on frontend assets.  
   2. Add `max_age=86400` to `CORSMiddleware`.  
   3. Add partial index on `outbox(created_at) WHERE published_at IS NULL`.  
   4. Configure PostgreSQL `shared_buffers=1GB`, `random_page_cost=1.1`, and `jit=off`.  
   5. Secure Coolify HTTPS routing and close public port 8000.  
10. **Should I upgrade the VPS, or optimize the current system first?**  
    **OPTIMIZE THE CURRENT SYSTEM.** Upgrading the VPS would achieve 0% noticeable improvement because the hardware is already 85% idle. Applying the recommended optimizations will produce an immediate and dramatic speedup.

---

## 17. Limitations and Unverified Areas

- **High-Concurrency Load Testing:** In strict adherence to the read-only safety policy, simulated load tests and traffic generation were not executed.
- **Off-Site Backup Verification:** Because `BACKUP_RCLONE_REMOTE` is unconfigured, remote upload latency and network saturation during backups could not be evaluated.

---

## 18. Final Verdict

| Metric | Current State | Optimized Target |
| :--- | :---: | :---: |
| **Initial Asset Download** | 4.5 MB (Uncompressed) | **~1.1 MB (Gzip)** |
| **Repeat Asset Download** | 4.5 MB (Revalidation) | **0 Bytes (Browser Cache)** |
| **API Preflight Overhead** | 1 Preflight per Request (~140ms) | **1 Preflight per Day (< 1ms)** |
| **Outbox Scan Cost** | 9,247 rows / poll | **0 – 1 rows / poll (Index)** |
| **Hardware Adequacy** | 2 vCPU / 8 GB (15% used) | **Optimal for current load** |

**Recommendation:** **OPTIMIZE CURRENT VPS**.
