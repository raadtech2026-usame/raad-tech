# ADR-0014: Resolving Two Config Gaps Found While Implementing Live Geofence Evaluation

## Status
Accepted (user decisions, made while scoping `docs/architecture/post-f7-production-readiness-
roadmap.md` Phase A item A5 — live geofence evaluation).

## Context
A5 wires the already-built-but-never-invoked geofence primitives (`GeofenceEvaluationService`,
the `GeofenceCrossing` entity and its four event types, two dormant notification triggers) into
the live position-ingestion path. Scoping the actual evaluation logic surfaced two real gaps
between Phase 2 §22.1 ("Geofence Event Architecture") and the originally approved Database
Design — not implementation details, but missing configuration data with no invented substitute
available:

1. **No "approaching stop" radius/threshold anywhere.** Phase 2 §22.1: "Radii and the approach
   threshold (distance or ETA) are configurable per organization/route." Database Design's
   `stops` table (§5.x) has exactly one radius column, `geofence_radius_m`, documented as
   backing both "approaching" and "arrived at stop" semantics — no second column for a wider
   approach threshold exists anywhere.
2. **No organization geofence center to test "arrived at organization" against.** Phase 2 §22.1
   names an "organization geofence... used for 'arrived at organization'", but Database Design
   §4.2's `organizations` table has no latitude/longitude/radius column at all, and `org_settings`
   (§4.7, which might have carried a default radius) was never built (documented only in prose,
   no column table — `organization/domain/entities.py`'s own module docstring already flags this
   as deferred).

Both of the two currently-dormant notification triggers this roadmap item exists to wake up
(`VehicleApproachingStopNotifier`, `VehicleArrivedAtOrganizationNotifier`) depend on one of these
two gaps — skipping both would leave A5 as pure infrastructure with no visible behavior change,
against a legitimate architecture-decision boundary (`.claude/rules/workflow.md` #8: "if
documentation is missing or conflicts exist, stop and request clarification instead of making
assumptions"). Both were put to the user directly rather than invented.

## Decision

### 1. Approach radius: a flagged multiplier of the stop's own arrival radius
`APPROACHING_STOP` fires when a vehicle is within `stop.geofence_radius_m * 3` of the stop (the
multiplier lives as `_APPROACH_RADIUS_MULTIPLIER` in `tracking/events/subscribers.py`, not a new
config column) — the user's own instruction was to let this implementation choose and document
the exact rule rather than adding a new schema column for it. A stop with no configured
`geofence_radius_m` at all gets no approach/arrival evaluation whatsoever (never a hardcoded
fallback radius) — flagged, not invented around, mirroring `TrackingApplicationService.
evaluate_geofence`'s own existing "caller supplies the radius" contract.

### 2. Organization geofence: add real schema columns
`organizations` gains `latitude`/`longitude`/`geofence_radius_m` (all nullable `DECIMAL(9,6,
asdecimal=False)`/`Integer`, mirroring `stops`' identical column shapes exactly) — migration
`a53375e74c3a`. `Organization.set_geofence(...)` (all three fields set together or not at all,
enforced at the domain layer) is the only way to populate them; `register()` deliberately does
not accept them (no approved document gives this a creation-time field, and requiring exact
coordinates at signup would regress an already-approved registration flow).
`OrganizationApplicationService.update_organization_geofence` is reachable at the application
layer only — **no new HTTP route this phase**, the same "use-case exists, no approved endpoint
yet" posture `Route.remove_stop`/`Trip.interrupt`/`ScopeAssignmentApplicationService`'s own
grant/revoke methods already establish. An organization that hasn't configured its location yet
simply has no organization-geofence evaluation performed for it, ever — never a zero-island
fallback.

### 3. Cooldown / minimum dwell: a flagged fixed window, not literal multi-sample debounce
Phase 2 §22.3 asks for "minimum dwell" and a "cooldown... duplicate suppression window per
(trip, stop, event-type)" but specifies neither mechanism nor a duration. Implemented as: a
per-(trip, stop-or-org, event-type) timestamp (`last_fired_at`, Redis-backed hysteresis state)
suppresses re-firing the same event type within `_EVENT_COOLDOWN_SECONDS = 120` of its last fire
— combined with the existing was-inside/is-inside flag transition (which already prevents
re-firing while continuously inside a radius), this satisfies §22.3's stated intent without
implementing literal N-consecutive-reading debounce, which no document specifies the parameters
of either. Flagged in `tracking/events/subscribers.py`'s own module docstring as a deliberate
simplification, not the only possible interpretation.

## Consequences
- `organizations` gains three new nullable columns and one new domain event
  (`OrganizationGeofenceUpdated`) — no existing row is affected (all `NULL` until explicitly
  set), no existing endpoint's response shape changes except gaining three new (nullable)
  `OrganizationDTO` fields.
- No UI exists yet to set an organization's geofence location — it is reachable only via direct
  application-layer/test code until a future phase adds an approved endpoint and Org
  Admin/Founder-facing form. Tracked as a real, deliberate gap, not silently assumed solved.
- The `3x` approach multiplier and `120s` cooldown are both easily reconfigurable constants, not
  load-bearing architecture — revisiting either later (e.g., if Phase 2 §22.1's "configurable
  per organization/route" is ever formally implemented via a real config column) requires no
  change to the evaluation algorithm's shape, only where the numbers come from.

## Verification
- `tests/unit/test_organization_domain.py::OrganizationGeofenceTests` — `set_geofence`
  invariants (set-together-or-not-at-all, range validation, event emission).
- `tests/unit/test_organization_application.py::UpdateOrganizationGeofenceApplicationTests`.
- `tests/integration/test_organization_repository.py::
  test_geofence_round_trips_through_the_real_decimal_columns` — proves the real Postgres
  `DECIMAL`/`Integer` columns give back plain `float`/`int`, not `decimal.Decimal`, against a
  live database in this environment.
- `alembic upgrade head` / `downgrade -1` / `upgrade head` round-tripped clean; `alembic check`
  reports "No new upgrade operations detected."
- `tests/unit/test_tracking_subscribers.py` covers the geofence evaluation orchestration itself
  (see that module's own docstring for the full case list).

## References
- `docs/architecture/post-f7-production-readiness-roadmap.md` Phase A item A5
- `docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §22 (Geofence Event Architecture)
- `docs/business/RAAD_Phase3.2_Database_Design_v1.md` §4.2 (`organizations`), §4.7 (`org_settings`)
- Migration `backend/migrations/versions/20260726_1700_a53375e74c3a_organization_add_geofence_columns.py`

## Amendment (2026-07-26): Organization-level configurable approaching distance

**Status:** Accepted (direct user decision), superseding this ADR's original Decision §1 only.
Decision §2 (organization geofence columns) and §3 (cooldown window) are unchanged.

### Context
Decision §1 above flagged the `3x` approach-radius multiplier as "easily reconfigurable... not
load-bearing architecture" and explicitly anticipated exactly this follow-up: "revisiting either
later (e.g., if Phase 2 §22.1's 'configurable per organization/route' is ever formally implemented
via a real config column) requires no change to the evaluation algorithm's shape, only where the
numbers come from." The user has now made that call directly: Phase 2 §22.1's "configurable per
organization/route" language is implemented at the **organization** level this phase (not
per-route/per-stop yet — see below), with a default of 300m.

### Decision
`organizations` gains a fourth geofence-related column, `approaching_distance_m` — migration
`b6f2a19d3e7c`. Unlike `latitude`/`longitude`/`geofence_radius_m` (Decision §2, still nullable —
an organization opts in to its own "arrived at organization" evaluation), `approaching_distance_m`
is **`NOT NULL`, defaulting to 300m** (`Organization._DEFAULT_APPROACHING_DISTANCE_M`, set at
`register()` time and backfilled onto existing rows via the migration's server default): every
organization has *some* approaching distance, since it governs "approaching stop" evaluation for
every stop on every one of that organization's routes, not an opt-in location fact the way the
organization's own arrival geofence is.

`tracking/events/subscribers.py`'s `_evaluate_stop_geofence` now reads
`organization.approaching_distance_m` directly as the absolute "approaching" radius, in place of
`stop.geofence_radius_m * _APPROACH_RADIUS_MULTIPLIER` — the approach radius is therefore fully
decoupled from any specific stop's own arrival radius. Configuring it is
`Organization.set_approaching_distance_m` (its own setter/event,
`OrganizationApproachingDistanceUpdated` — deliberately not folded into `set_geofence`, since it
governs a route-scoped concern orthogonal to the organization's location-scoped arrival geofence),
reachable via `OrganizationApplicationService.update_organization_approaching_distance` —
application layer only, **no approved HTTP route this phase**, the same posture `set_geofence`
already established.

**Designed for a future per-stop override, not built this phase**: the organization-level value
is a *default* a stop's own evaluation falls back to. A later phase could add a nullable
`stops.approaching_distance_m` that takes precedence over the organization default when set —
`_evaluate_stop_geofence`'s own resolution point (`approach_radius_m = organization.
approaching_distance_m`) is the one place such a change would land; nothing else in the evaluation
algorithm's shape would need to change, exactly as this ADR's original Consequences section
anticipated.

### Consequences
- `organizations` gains one new `NOT NULL` column (server-default-backfilled to 300 on existing
  rows) and one new domain event (`OrganizationApproachingDistanceUpdated`).
- The approach radius for a given stop is no longer proportional to that stop's own arrival
  radius — a stop with a small arrival radius (e.g. 20m, a tight driveway) and a stop with a large
  one (e.g. 150m, an open lot) now trigger `APPROACHING_STOP` at the *same* distance (the
  organization's configured default) rather than at 3x/60x their own respective radii. No document
  specifies whether approach distance should scale with a stop's own radius; decoupling them was
  the user's own explicit instruction, not an invented interpretation.
- No UI/HTTP route exists yet to set this value — reachable only via direct application-layer/
  test code, the same tracked, deliberate gap `set_geofence` already carries.

### Verification
- `tests/unit/test_organization_domain.py` — `set_approaching_distance_m` invariants (positive-
  value validation, default value, event emission).
- `tests/unit/test_organization_application.py` — `update_organization_approaching_distance`
  service orchestration.
- `tests/unit/test_tracking_subscribers.py::GeofenceEvaluationTests` — proves the approach radius
  now comes from the organization's own configured value, independent of the stop's arrival
  radius.
- `alembic upgrade head` / `downgrade -1` / `upgrade head` round-tripped clean.

### References (amendment)
- Migration `backend/migrations/versions/20260726_1800_b6f2a19d3e7c_organization_add_approaching_distance.py`
