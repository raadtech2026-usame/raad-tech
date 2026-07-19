"""Domain services for the `transport_ops` module (Backend LLD §5.1).

None are defined in this phase. `Student`'s own constructor already enforces everything that's
a pure function of its own fields (non-empty/length-bounded `full_name`/`external_ref`). The
one candidate that might look like a domain service — "does this student already exist" /
uniqueness checking — needs a repository query (I/O) to check existing rows, which makes it an
*application*-layer concern (orchestration via the repository), not a domain service (domain
services are stateless operations over already-loaded entities, LLD §5.1), mirroring
`organization.domain.services`'s identical reasoning for region-name uniqueness. Add a domain
service here only if a future rule genuinely needs to span two loaded aggregates without I/O —
e.g. once `StudentAssignment` (a later phase, deliberately out of this phase's scope per
`entities.py`'s module docstring) exists alongside `Student`.

**Phase 11 (`Route`/`Stop`):** same reasoning again. `Route`'s own constructor/`add_stop`/
`move_stop` already enforce everything that's a pure function of already-loaded state
(sequence uniqueness, coordinate bounds, name length) directly on the aggregate — no separate
domain service needed. Per-tenant route-name uniqueness needs a repository query (I/O), so it
is an application-layer concern (`application/validators.py`'s `ensure_route_name_available`),
mirroring `fleet_device.application.validators.ensure_plate_no_available`'s identical
reasoning.

**Phase 12 (`Trip`):** same reasoning again. `Trip.schedule`'s cross-organization check
compares two already-loaded aggregates' `organization_id`s with no I/O of its own (mirroring
`StudentParent.link`'s identical placement) — a pure aggregate-constructor concern, not a
domain service. `Trip`'s one genuinely I/O-dependent rule, one-active-trip-per-vehicle, needs a
repository query, so it lives in the application layer instead
(`application/validators.py`'s `ensure_vehicle_has_no_active_trip`).

**Phase 13 (`StudentAssignment`):** same reasoning again. `StudentAssignment.assign`'s
cross-organization checks are pure, no-I/O comparisons of already-loaded aggregates, mirroring
`Trip.schedule`'s identical placement. The one I/O-dependent rule, one-active-assignment-per-
student, lives in the application layer (`application/validators.py`'s
`ensure_student_has_no_active_assignment`), and pickup/dropoff stop existence-checking is a
repository-query concern too (`ensure_pickup_and_dropoff_stops_exist`) — neither is a domain
service.
"""
