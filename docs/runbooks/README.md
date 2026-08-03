# Runbooks

Operational runbooks for exception workflows identified in
`docs/business/Project_Brief_v1.md` §8.9 (Device Offline, Vehicle Offline, GPS Signal Lost, Network
Failure, Driver Login Failure, Subscription Expired, Trip Not Started, Trip Interrupted) and for
incident response, deployment rollback, and on-call procedures.

## Status

Structural placeholder for the exception-workflow/incident-response runbooks listed above. Three
real runbooks exist outside that original list:

- [`founder-bootstrap.md`](founder-bootstrap.md) — first-time-deployment Founder account
  provisioning, added alongside `backend/raad/interfaces/cli/bootstrap_founder.py`.
- [`founder-password-recovery.md`](founder-password-recovery.md) — recovering a locked-out
  Founder account (ADR-0017 Amendment), added alongside
  `backend/raad/interfaces/cli/reset_founder_password.py`.
- [`backup-and-restore.md`](backup-and-restore.md) — database backup/restore operations and
  disaster recovery (`PROJECT_STATUS.md` Priority 1 Item 1), added alongside
  `scripts/db/backup.sh`/`scripts/db/restore.sh` and the `docker-compose.yml` `backup` service.
