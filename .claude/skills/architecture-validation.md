# Skill: Architecture Validation

## Purpose
Verify that the repository's actual structure still matches the approved architecture — catch drift
before it compounds.

## Workflow
1. Confirm the ten bounded contexts under `backend/raad/modules/` are unchanged in name and shape
   (`api/ application/ domain/ infra/ events/`) unless a new ADR justifies a change.
2. Confirm `backend/tests/architecture/` still passes (dependency-direction and import-boundary
   checks) — treat a failure here as a build-blocking regression, not a warning.
3. Confirm JT808 and JT1078 remain separate deployables under `services/`, with no code path from
   `backend/` that opens a device socket.
4. Confirm no new top-level deployable was added without an ADR in `docs/architecture/adr/`.
5. Confirm the ten-context list and the D1–D6/CR-1 locked decisions in
   `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` are still reflected accurately in
   `.claude/rules/`.
6. Report any drift found as a finding, don't silently "fix" architecture without owner sign-off if
   the fix is non-trivial.

## When to use
Periodically, and always before a major release or before extracting a module into its own service.
