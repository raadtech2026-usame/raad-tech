# Skill: API Review

## Purpose
Validate that a new or changed API endpoint conforms to the published `/api/v1` contract
conventions before it ships.

## Workflow
1. Confirm the route belongs under the correct resource group per `.claude/rules/api.md`
   (e.g. `/students` → transport_ops, not scattered elsewhere).
2. Confirm versioning: additive changes stay in `/api/v1`; breaking changes require a `/api/v2` plan,
   not a silent breaking change in place.
3. Confirm the error envelope matches the standard shape:
   `{ error: { code, message, correlation_id, details? } }`.
4. Confirm auth: `Authorization: Bearer <access_jwt>` required, and the endpoint's authorization check
   matches the role/scope/ownership/time-window rules for the resource it touches.
5. Confirm request/response schemas are defined in `api/schemas.py`, not inlined ad hoc.
6. Confirm idempotency keys exist on any payment-affecting or otherwise non-idempotent-by-nature
   endpoint.
7. Confirm the endpoint will be picked up correctly by build-time OpenAPI generation (no manual spec
   authoring).

## When to use
Whenever a route is added, removed, or its request/response shape changes.
