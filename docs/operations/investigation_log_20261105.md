# RAAD-TECH Production Remediation — Investigation & Execution Log

- **Date:** 2026-11-05
- **Incident Commander:** Senior Site Reliability Engineer / PostgreSQL DBA / Backend Architect
- **Environment:** Production Hostinger VPS (`srv2082072`), Coolify v4.6.0
- **App UUID:** `m0lhtrori7rbplpzwzilohfz`
- **Application Path:** `/data/coolify/applications/m0lhtrori7rbplpzwzilohfz`

---

## Phase A: Connectivity and Environment Discovery (Completed)

1. **Local System:**
   - OS: Windows
   - Repository: `C:\Dev\RAAD-TECH`
   - Git branch: `main` (clean working tree, HEAD @ `bbe21b8e223f8c2911da894b875643608b6ed7b8`)
   - Remote: `https://github.com/raadtech2026-usame/raad-tech.git`
   - Python: 3.11.18, Git: 2.55.0.windows.5, Docker: 29.8.2
   - SSH config: `Host raad-vps`, `HostName 72.62.7.212`, `User root`, key-based auth verified.

2. **Production Host:**
   - Hostname: `srv2082072`
   - Docker: 29.9.2, Git: 2.43.0, Python: 3.12.3
   - Coolify: 4.6.0
   - Running container set for `m0lhtrori7rbplpzwzilohfz`:
     - `migrate-m0lhtrori7rbplpzwzilohfz-20261105T102701`: Exited (1) — migration failure
     - `backend-m0lhtrori7rbplpzwzilohfz-20261105T102701`: Created (blocked on migrate)
     - `worker-m0lhtrori7rbplpzwzilohfz-20261105T102701`: Created (blocked on migrate)
     - `prometheus-m0lhtrori7rbplpzwzilohfz-20261105T102701`: Created (blocked on migrate)
     - `postgres-m0lhtrori7rbplpzwzilohfz-20261105T102701`: Up (healthy)
     - `redis-m0lhtrori7rbplpzwzilohfz-20261105T102701`: Up (healthy)
     - `frontend-m0lhtrori7rbplpzwzilohfz-20261105T102701`: Up (healthy)
     - `device-gateway-m0lhtrori7rbplpzwzilohfz-20261105T102701`: Up (healthy)
     - `jt1078-relay-m0lhtrori7rbplpzwzilohfz-20261105T102701`: Up (healthy)
     - `backup-m0lhtrori7rbplpzwzilohfz-20261105T102701`: Up
     - Standalone `raad-postgres`: Up 2 days (unmanaged)

## Phase B: Dual PostgreSQL Remediation (Completed)

1. **State Discovered:**
   - Container `raad-postgres` (ID `f092fc64df00`, started 2026-11-02 19:40:01 UTC) and `postgres-m0lhtrori7rbplpzwzilohfz-20261105T102701` both mounted `/var/lib/docker/volumes/docker_raad_postgres_data/_data`.
   - Both held alias `postgres` on network `m0lhtrori7rbplpzwzilohfz`. Docker DNS alternated round-robin between `172.16.3.3` and `172.16.3.6`.
   - `raad-postgres` produced continuous checkpointer WAL flush errors.

2. **Safety Measures Executed:**
   - Full live consistent backup taken: `/backups/raad_raad_20261105_112309.dump` (SHA256: `f7ded22280e6ace891bd3fbda959e76ece4a8abf3f26642f651ef774e1d96b01`).
   - Backup verified via test restore into isolated temporary container `raad-backup-verify-temp`.
   - Full raw directory copied to `/var/lib/docker/volumes/docker_raad_postgres_data_BEFORE_REPAIR`.

3. **Remediation Executed:**
   - Stopped and removed unmanaged container `raad-postgres`.
   - Archived directory, cleanly started `postgres-m0lhtrori7rbplpzwzilohfz-20261105T102701`.
   - Restored data from verified backup `raad_raad_20261105_112309.dump`.
   - Verified data counts: users=14, students=18, parents=8, drivers=1, vehicles=3, trips=2, organizations=1.
   - Verified single postmaster listening and healthy, zero checkpoint errors, stable DNS resolving exclusively to `172.16.3.3`.
