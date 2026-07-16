"""Application-layer command validators for `transport_ops` (Backend LLD §4.1's application
table: "Contextual pre-conditions of a use-case"). These would check pre-conditions that need
repository I/O — exactly why they're an application concern and not a domain one, mirroring
`organization`/`fleet_device`'s identical reasoning.

**None are defined this phase** — every validator category the task asked to review resolves to
"not needed" or "lives elsewhere", not to a gap:

- **Duplicate student validation** — explicitly scoped "(only if documented)". Database Design
  §6.2 lists no `UX`/uniqueness key on `students` beyond its primary key (`external_ref` has no
  uniqueness annotation) — confirmed again in this phase's own research, matching Phase 10.1's
  `StudentRepository` docstring exactly. No document defines a duplicate-student rule, so none is
  implemented here (the same "(if documented)" discipline already applied to JT808 Phase 9.6's
  duplicate-timestamp handling).
- **Organization ownership validation** — no application service in `organization`/`fleet_device`
  performs an explicit `organization_id` equality check against the actor's scope (confirmed by
  reading every write/read method in both modules' `services.py`); tenant scoping is resolved
  once at the edge and injected into every repository query automatically
  (`.claude/rules/backend.md` #4: "never rely on a call site remembering to filter by
  `organization_id`"). `StudentApplicationService` follows the identical pattern — trusting the
  injected, tenant-scoped `TransportOpsUnitOfWork`/`StudentRepository` entirely, adding no manual
  check of its own.
- **Student existence validation** — implemented as `StudentApplicationService.
  _get_student_or_raise`, a private static helper on the service class itself, exactly mirroring
  `OrganizationApplicationService._get_organization_or_raise`/`_get_region_or_raise` — not a
  function here. Existence-checking the very aggregate a use-case operates *on* lives on the
  service in every reference module; this file hosts pre-checks on *other*, referenced aggregates
  instead (e.g. `fleet_device.application.validators.ensure_vehicle_exists` for a `vehicle_id`
  referenced by a `DeviceAssignment` command) — `Student` has no such cross-aggregate reference
  this phase (no `route_id`/`parent_id`/`trip_id`, `domain/entities.py`'s module docstring).
- **State transition validation** — already fully owned by `Student`'s own domain methods
  (Phase 10.1): every status-change method is idempotent, and no illegal-transition rule is
  documented anywhere to enforce (`domain/value_objects.py`'s `StudentStatus` docstring). Adding
  an application-layer transition check here would duplicate domain rules — explicitly forbidden
  by this phase's own architecture requirements.

Add a validator here only once an approved document defines a genuine I/O-dependent
pre-condition this list doesn't already cover.
"""
