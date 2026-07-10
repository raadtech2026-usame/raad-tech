# Command: Review Module

## Purpose
Invoke the "Code Review" skill scoped to a single backend module.

## Usage
`/review-module <context-name>`

## Behavior
1. Loads `.claude/skills/code-review.md`.
2. Checks the target module's `api/ application/ domain/ infra/ events/` layering, dependency
   direction, tenancy enforcement, and naming against `.claude/rules/backend.md`,
   `.claude/rules/database.md`, and `.claude/rules/naming.md`.
3. Reports findings ranked by severity; does not silently auto-fix architectural violations without
   surfacing them first.

## Preconditions
- Target module exists under `backend/raad/modules/`.
