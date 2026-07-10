# CI/CD

Pipeline definitions for build → test → scan → deploy per deployable. Tooling (GitHub Actions,
GitLab CI, etc.) is not yet specified in approved documentation — do not assume a provider before
this is confirmed.

## Structure

`pipelines/` holds one placeholder pipeline definition per deployable:

- `backend-pipeline.yml`
- `frontend-pipeline.yml`
- `mobile-pipeline.yml`
- `jt808-pipeline.yml`
- `jt1078-pipeline.yml`
- `infrastructure-pipeline.yml`

Migrations must run as a gated pipeline step (per Phase 2 §11.3) — never as an ad hoc manual step in
production.

## Status

Structural scaffold only. All pipeline files are empty placeholders.
