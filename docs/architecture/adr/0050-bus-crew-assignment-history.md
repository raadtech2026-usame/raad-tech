# ADR-0050: Bus Crew Assignment with History (amends Database Design §6.1)

## Status

**Accepted** (2026-09-30), Phase 1 of the transport-management roadmap, with ADR-0049.

## Context

The approved Project Brief says:
- a vehicle is "Assigned to drivers" and "Assigned to routes" (§6.3);
- a driver can "View assigned vehicle" and "View assigned route" (§4.7);
- "Drivers may only operate assigned vehicles" (§7.6).

Database Design §6.1 says "Vehicle↔driver is per-trip", and the code followed it. So RAAD could say who
drove a trip, but never who is *regularly* on a bus, and never who was on it last term.

This ADR resolves that documentation conflict for the standing crew. Trips are untouched.

## Decision

### 1. `vehicle_staff_assignments`: a history table, never overwritten

Each row records:
- `staff_id` and `vehicle_id`;
- the job title held during this assignment (`role_id`);
- an optional `route_id`;
- `starts_on`, and `ends_on` (null = current);
- `kind` (`permanent` / `temporary`), a `reason`, and `assigned_by`.

Rules:

- **A bus may have any number of staff at once**, including more than one person with a driving role,
  for example morning and afternoon drivers.
- **A staff member may be on several buses at once**, for example a supervisor.
- **One open assignment per person per bus.** A database partial unique index enforces it.
- **A temporary assignment must have an end date.** A permanent one may have none.
- **Replacing someone ends their row;** a new row starts for the replacement. Rows are never deleted.
  Ending records the actor and date through the audit trail.
- **The bus is required and the route optional.** There is no route-only assignment.
- **Organization boundary:** `vehicle_id` belongs to `fleet_device` and is referenced by id only,
  with no foreign key, following `.claude/rules/database.md` #3. The owning organization is checked
  through `fleet_device`'s own application service (a port adapter in `core/di/`). A bus from another
  organization is refused with 404.

### 2. Trips are unchanged

The trip remains the record of who actually drove: `trips.driver_id`, `change_driver`, and the driver
start/end ownership check.

The crew is the **plan**. "May only operate assigned vehicles" is **not** enforced in this phase:
enforcing it would block the substitute cover that Phase 2 designs.

### 3. Database Design §6.1 is amended

Its closing line now reads: vehicle↔driver is per-trip **for who actually drove**; the standing crew
and its history are `vehicle_staff_assignments` (ADR-0050).

## Consequences

- New routes are under `/staff-assignments` (`transport_ops` owns them). `/vehicles` stays
  `fleet_device`'s prefix (`.claude/rules/api.md` #2).
- Absence, substitutes, the daily crew view and uncovered trips build on this table in Phase 2.
