# Hooks

No hooks are configured yet. This directory is a placeholder for future automated behaviors
(pre-commit checks, post-tool-use validation, etc.) that should run deterministically rather than
being left to convention.

Candidates worth configuring once the backend exists:
- Run `backend/tests/architecture/` automatically before allowing a commit that touches
  `backend/raad/modules/` or `backend/raad/core/`.
- Block commits that add a table without standard audit columns.

## Status
Placeholder only — no hook scripts exist yet.
