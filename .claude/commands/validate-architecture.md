# Command: Validate Architecture

## Purpose
Invoke the "Architecture Validation" skill to check the repository for structural drift from
approved architecture.

## Usage
`/validate-architecture`

## Behavior
1. Loads `.claude/skills/architecture-validation.md`.
2. Walks `backend/raad/modules/`, `services/jt808/`, `services/jt1078/` and compares structure
   against `.claude/rules/architecture.md` and `.claude/rules/backend.md`.
3. Confirms `backend/tests/architecture/` is passing.
4. Reports any drift as findings, not silent fixes, unless explicitly asked to also apply fixes.

## Preconditions
- None; safe to run at any time as a read-only check.
