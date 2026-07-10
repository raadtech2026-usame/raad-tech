# Command: Review API

## Purpose
Invoke the "API Review" skill against a specific endpoint or router change.

## Usage
`/review-api <route-or-router-path>`

## Behavior
1. Loads `.claude/skills/api-review.md`.
2. Validates the target against `.claude/rules/api.md`: versioning, resource-group placement, error
   envelope, auth requirement, schema location, idempotency where applicable.
3. Reports pass/fail per check with specific file:line references.

## Preconditions
- Target route(s) exist in a module's `api/routers.py` or in
  `backend/raad/interfaces/http/api_v1.py`.
