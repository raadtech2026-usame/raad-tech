# ADR-0001: Business Entity → Bounded Context Module Mapping

## Status
Accepted (backfilled from the already-approved Phase 2 Domain Architecture and Phase 3.1/3.2
design docs — not a new decision).

## Context
`docs/business/Project_Brief_v1.md` Ch. 6 defines the core business entities: Organization, Vehicle,
Device, Driver, Student, Parent/Guardian, Route, Stop, Trip, Subscription. The backend is a modular
monolith organized into exactly **ten bounded contexts** (Phase 2 §2.1), not one module per entity.
This ADR makes explicit which context owns each entity, so the scaffold can be verified against it
and future changes are checked against a documented mapping rather than re-derived each time.

## Decision
Each business entity is owned by exactly one bounded context module under
`backend/raad/modules/`:

| Entity | Module | Rationale |
|---|---|---|
| Organization (incl. Schools, Transport Companies, Fleet Companies) | `organization` | Organization is the tenant root; "School" is a value of `org_type`, not a separate concern (D3 keeps org_type dormant beyond `SCHOOL`). |
| Vehicle | `fleet_device` | Vehicle is the operational asset; grouped with Device because they share one lifecycle concern — the 1:1 device↔vehicle assignment binding (Phase 2 §19). |
| Device (GPS/MDVR) | `fleet_device` | Device communication (JT808/JT1078) is handled by separate services; `fleet_device` owns only the assignment/lifecycle *record*, not the protocol. |
| Driver | `transport_ops` | Driver is defined purely by transport operations (trip start/end, assigned route/vehicle) — no separate "driver identity" concern beyond IAM login, which stays in `iam`. |
| Student | `transport_ops` | Core business domain of RAAD (Project Brief Ch. 6.6); owns `students`, `student_assignments`. |
| Parent/Guardian | `transport_ops` | Parent access is entirely scoped to their child's transport assignment; kept adjacent to Student rather than split into IAM, since the business relationship (not generic identity) drives access. |
| Route, Stop | `transport_ops` | Structural children of Trip/Student assignment. |
| Trip | `transport_ops` | Operational aggregate root for a day's journey (Phase 2 §2.3). |
| Subscription | `billing` | Commercial concern, deliberately downstream-advisory to Video/Notifications for entitlements only (D4/CR-1) — never merged into `organization` so billing logic can't leak into tenant management. |

`iam` remains a distinct context for authentication/session/RBAC infrastructure shared by every
role, not tied to any single business entity.

## Consequences
- No business entity from Ch. 6 is missing from the scaffold; all ten required contexts exist under
  `backend/raad/modules/`.
- A request to give Students, Parents, Drivers, Vehicles, or Subscriptions their own top-level
  module would be a bounded-context-boundary change and requires a new ADR superseding this one —
  not an ad hoc split during implementation.
- JT808 (device protocol) and JT1078 (video protocol) are explicitly **not** entities inside
  `fleet_device` or `video` — they are separate deployables (`services/jt808/`, `services/jt1078/`)
  that only ever communicate with the Business API via domain events / signaling, never by sharing a
  process or writing Business API tables directly (Phase 2 D6, §5).

## References
- `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §2 (Domain Architecture), §19 (Device
  Assignment Lifecycle)
- `docs/business/RAAD_Phase3.1_Backend_LLD_v1_2.md` §1
- `docs/business/RAAD_Phase3.2_Database_Design_v1.md` (table-to-context grouping)
- `docs/business/Project_Brief_v1.md` Ch. 6
