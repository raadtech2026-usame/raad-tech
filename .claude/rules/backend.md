# Rule: Backend

Derived from `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md`.

1. **Module shape is fixed.** Every module under `backend/raad/modules/<context>/` has exactly:
   `api/ application/ domain/ infra/ events/` plus an `__init__.py` facade that is the module's
   *only* public surface. No other module may import past that facade.
2. **Dependency direction:** `api -> application -> domain`. `infra` implements interfaces the
   domain defines (dependency inversion). Domain never imports infra or FastAPI.
3. **No cross-module DB reads.** A module's repositories query only that module's own tables.
   Cross-context data comes from the owning module's application service or from events/read-models.
4. **Tenancy is cross-cutting.** Tenant context is resolved once at the edge (`core/tenancy`) and
   injected into every repository query automatically — never rely on a call site remembering to
   filter by `organization_id`.
5. **Events published transactionally.** Use the outbox pattern (`interfaces/workers/
   outbox_relay.py`) so domain events are never lost or published before their causing transaction
   commits.
6. **Safety-over-billing is one policy object.** Safety capabilities (live GPS during active trips,
   safety notifications) are granted by a single, tested capability policy in `core/policies/` —
   never by scattered `if subscription_active` checks.
7. **Video authorization happens in the API**, before any signaling to the JT1078 server. The Parent
   role must have zero reachable code path to a media session or stream token.
