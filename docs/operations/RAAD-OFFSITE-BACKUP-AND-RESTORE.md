# RAAD-TECH — Offsite Backup Configuration and Disaster Recovery Guide

**System:** RAAD-TECH Production Platform  
**Target Architecture:** PostgreSQL 16 on Hostinger VPS `srv2082072`  
**Tooling:** PostgreSQL `pg_dump`/`pg_restore` + `rclone` (v1.66+ in `postgres:16-alpine`)  
**Container:** `raad-backup` (`docker/backup.Dockerfile`)  

---

## 1. Architecture & Background

The RAAD-TECH backup architecture provides two layers of data protection:
1. **Local Persistent Volume:** Dumps are written to `/backups` (`raad_backups_data` Docker volume) on a 24-hour cycle (`BACKUP_INTERVAL_HOURS=24`) with 14-day local retention (`BACKUP_RETENTION_DAYS=14`).
2. **Offsite Remote Synchronization:** The `backup.sh` script invokes `rclone copy` to push fresh dumps to a remote object storage bucket, followed by `rclone delete --min-age 30d` for remote lifecycle pruning.

> [!WARNING]
> While local backups protect against accidental row deletion or bad migrations, **local backups on the same disk do NOT protect against total VPS loss, hardware failure, or datacenter outages.** Offsite replication is essential for production durability.

---

## 2. Setting Up an Offsite Storage Remote

`rclone` supports over 40 cloud storage providers. Cloudflare R2 or AWS S3 is recommended due to low cost and zero egress fees (R2).

### Option A: Cloudflare R2 (Recommended — Zero Egress Fees)

1. **Create an R2 Bucket:**
   - Log in to Cloudflare Dashboard -> R2 Object Storage.
   - Click **Create bucket**. Name it `raad-production-backups`.
   - Set Location to `auto` or closest region (Europe / Middle East).
2. **Create R2 API Credentials:**
   - In R2 -> Manage R2 API Tokens -> **Create API Token**.
   - Permissions: **Object Read & Write**.
   - Note the **Access Key ID**, **Secret Access Key**, and **Endpoint URL** (e.g., `https://<account_id>.r2.cloudflarestorage.com`).
3. **Configure `rclone.conf` on the VPS:**
   SSH to `72.62.7.212` and create the directory:
   ```bash
   mkdir -p /root/raad-backups-config
   ```
   Create `/root/raad-backups-config/rclone.conf`:
   ```ini
   [r2-backups]
   type = s3
   provider = Cloudflare
   access_key_id = <YOUR_R2_ACCESS_KEY_ID>
   secret_access_key = <YOUR_R2_SECRET_ACCESS_KEY>
   endpoint = https://<ACCOUNT_ID>.r2.cloudflarestorage.com
   acl = private
   ```
   Set permissions:
   ```bash
   chmod 600 /root/raad-backups-config/rclone.conf
   ```

---

### Option B: AWS S3

1. **Create an S3 Bucket:**
   - In AWS Console -> S3 -> Create Bucket `raad-production-backups-eu`.
   - Block all public access. Enable default AES-256 encryption.
2. **Create an IAM User:**
   - Attach policy granting `s3:PutObject`, `s3:GetObject`, `s3:ListBucket`, `s3:DeleteObject` on `arn:aws:s3:::raad-production-backups-eu/*`.
   - Generate Access Key ID and Secret Access Key.
3. **Configure `rclone.conf`:**
   ```ini
   [s3-backups]
   type = s3
   provider = AWS
   env_auth = false
   access_key_id = <YOUR_AWS_ACCESS_KEY_ID>
   secret_access_key = <YOUR_AWS_SECRET_ACCESS_KEY>
   region = eu-central-1
   acl = private
   ```

---

## 3. Wiring Offsite Backups into Coolify

To connect the running `raad-backup` container to the offsite remote:

1. **Mount the `rclone.conf` into `raad-backup`:**
   In Coolify's Stack Compose definition for `raad-backup`, ensure the configuration file is mounted:
   ```yaml
   volumes:
     - source: raad_backups_data
       target: /backups
       type: volume
     - source: /root/raad-backups-config/rclone.conf
       target: /root/.config/rclone/rclone.conf
       type: bind
       read_only: true
   ```
2. **Add Environment Variables in Coolify:**
   In Coolify Dashboard -> Stack `m0lhtrori7rbplpzwzilohfz` -> Environment Variables:
   - `BACKUP_RCLONE_REMOTE`: `r2-backups:raad-production-backups`
   - `BACKUP_RCLONE_RETENTION_DAYS`: `30`
   - `RCLONE_CONFIG`: `/root/.config/rclone/rclone.conf`
3. **Redeploy Stack in Coolify.**

---

## 4. Verifying Offsite Synchronization

Trigger an immediate manual backup to test the full pipeline:

```bash
docker exec -it raad-backup /app/backup.sh
```

**Expected Log Output:**
```
[backup] starting: target=postgres/raad -> /backups/raad_raad_20261106_183000.dump
[backup] database not ready yet — waiting up to 120s for it
[backup] wrote /backups/raad_raad_20261106_183000.dump (4829104 bytes)
[backup] pushing to off-site remote: r2-backups:raad-production-backups
[backup] off-site copy complete
[backup] pruning off-site backups older than 30d from r2-backups:raad-production-backups
[backup] off-site retention pruning complete
[backup] done
```

Inspect remote bucket files:
```bash
docker exec -it raad-backup rclone lsl r2-backups:raad-production-backups
```
You should see `raad_raad_<timestamp>.dump` listed with its exact byte count.

Inspect `.latest_status`:
```bash
docker exec -it raad-backup cat /backups/.latest_status
# Output: OK:2026-11-06T18:30:15Z:/backups/raad_raad_20261106_183000.dump:4829104
```

---

## 5. Disaster Recovery Restore Procedure (New VPS)

If the production VPS `srv2082072` is destroyed or permanently unavailable:

### Step 1: Provision Replacement VPS
1. Deploy Ubuntu 24.04 on a fresh host with at least 4 vCPU, 8 GB RAM, and Docker Engine 25+.
2. Install Coolify or clone the RAAD-TECH repository.

### Step 2: Retrieve the Latest Backup from Offsite Storage
On the new host, install `rclone` and pull the latest dump:
```bash
# Configure rclone with the credentials from Step 2
rclone config

# List available dumps
rclone lsl r2-backups:raad-production-backups

# Copy the latest dump to the host
rclone copy r2-backups:raad-production-backups/raad_raad_<LATEST>.dump /tmp/
```

### Step 3: Bring Up PostgreSQL
Start only PostgreSQL and the backup container:
```bash
docker compose -f docker/docker-compose.yml up -d postgres backup
```

### Step 4: Execute Database Restore
```bash
docker cp /tmp/raad_raad_<LATEST>.dump raad-backup:/backups/latest.dump

docker exec -it raad-backup /app/restore.sh \
  --target-url "postgresql://raad:${POSTGRES_PASSWORD}@postgres:5432/raad" \
  --confirm \
  /backups/latest.dump
```

### Step 5: Catch Up Migrations
If the application code has newer migrations than the dump:
```bash
docker compose -f docker/docker-compose.yml run --rm migrate
```

### Step 6: Start All Services
```bash
docker compose -f docker/docker-compose.yml up -d
```
Verify all containers enter `healthy` status and test API endpoints.

---

## 6. Monthly Restore Drill Procedure

To ensure backups remain restorable:

1. Create a drill database on the PostgreSQL instance:
   ```bash
   docker exec -it raad-postgres createdb -U raad raad_drill
   ```
2. Restore the latest offsite backup into `raad_drill`:
   ```bash
   docker exec -it raad-backup /app/restore.sh \
     --target-url "postgresql://raad:${POSTGRES_PASSWORD}@postgres:5432/raad_drill" \
     --confirm \
     /backups/raad_raad_<LATEST>.dump
   ```
3. Verify integrity:
   ```bash
   docker exec -it raad-postgres psql -U raad -d raad_drill -c "SELECT COUNT(*) FROM users; SELECT COUNT(*) FROM erp_student_invoices; SELECT COUNT(*) FROM vehicle_positions;"
   ```
4. Drop the drill database:
   ```bash
   docker exec -it raad-postgres dropdb -U raad raad_drill
   ```
5. Record drill outcome in operational logs.
