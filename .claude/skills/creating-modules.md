# Skill: Creating Modules

## Purpose
Add a new bounded-context module to the backend (or extend an existing one) following the fixed
module shape, without violating dependency-direction or module-seam rules.

## Workflow
1. Confirm the module belongs to one of the ten fixed bounded contexts (`.claude/rules/architecture.md`).
   Adding an eleventh context requires an ADR first — do not proceed without one.
2. Scaffold the fixed shape under `backend/raad/modules/<context>/`: `api/`, `application/`,
   `domain/`, `infra/`, `events/`, and an `__init__.py` facade.
3. Design the domain layer first (`entities.py`, `value_objects.py`, `events.py`, `services.py`,
   `policies.py`, `repositories.py` as interfaces) — no framework or infra imports here.
4. Implement `application/` use-cases against the domain-defined repository interfaces.
5. Implement `infra/` (SQLAlchemy models, repository implementations, adapters) against those same
   interfaces — this is where dependency inversion happens.
6. Wire `api/routers.py` + `api/schemas.py` for HTTP, matching the `/api/v1` contract conventions in
   `.claude/rules/api.md`. Add `api/ws.py` only if the module serves realtime data.
7. Wire `events/publishers.py` / `events/subscribers.py` for any cross-context communication — never
   reach into another module's internals directly.
8. Add tests: unit (domain/application), integration (infra), contract (api), and confirm the
   architecture test suite still passes (no forbidden imports).
9. Update the module's section in `backend/README.md` if its responsibilities changed.

## When to use
When approved documentation calls for new module functionality within an existing bounded context.
