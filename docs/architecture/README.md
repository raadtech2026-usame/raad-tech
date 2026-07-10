# Architecture Documentation

This directory is seeded for Architecture Decision Records (ADRs) and architecture diagrams going
forward.

## Current state (flagged, not resolved)

As of Phase 4.1, the approved Enterprise Architecture document
(`RAAD_Phase2_Enterprise_Architecture_v1_2.md`) and all Phase 3 design documents live under
`../business/` rather than here. `docs/architecture/` was empty prior to this scaffold. This is
recorded as an open inconsistency for the project owner to resolve (either move architecture-labeled
documents here, or treat `docs/business/` as the permanent home for both business and architecture
documentation and retire this directory's separate role). See the Phase 4.1 completion report for
detail.

## Structure

- `adr/` — one file per Architecture Decision Record, numbered sequentially
  (`0001-<slug>.md`, `0002-<slug>.md`, ...). ADR-worthy decisions already made and recorded in Phase 2
  §15 (ADR-1 through ADR-9) should be backfilled here as individual records if/when this directory is
  adopted as the ADR home.

## Recorded so far

- `adr/0001-business-entity-module-mapping.md` — confirms which bounded-context module owns each
  Ch. 6 business entity (Organization, Vehicle, Device, Driver, Student, Parent, Route, Stop, Trip,
  Subscription). Backfilled from Phase 2 §2 / Phase 3.1 §1 / Phase 3.2, not a new decision.

Phase 2 §15's ADR-1 through ADR-9 remain unbackfilled as individual files — still living only inside
the Phase 2 document.

## Status

Seeded with one backfilled ADR; otherwise a structural placeholder.
