"""Application-layer command validators for `tracking` (Backend LLD §4.1's application table:
"Contextual pre-conditions of a use-case"). None are defined in this phase — the candidates
considered, and why each is placed elsewhere, mirroring `fleet_device.domain.services`'s
"document why empty" precedent:

- **Position-recording uniqueness/existence checks**: `vehicle_positions` has no uniqueness
  constraint to defend (unlike `vehicles.plate_no`/`devices.terminal_id`) and its
  `vehicle_id`/`device_id`/`trip_id` are cross-module references, not FK-enforced by design
  (Database Design §11.3: "cross-context references are by ID only... no hard FK across
  modules") — so there is nothing for this module's repositories to pre-check before
  `record_vehicle_position`/`record_backfill_position`.
- **The `approaching_stop`/`entered_stop` require-a-`stop_id` rule**: already enforced by
  `GeofenceCrossing.__init__` (Phase 8.1) — a domain invariant, not a repository-dependent
  pre-condition, so re-checking it here would duplicate a business rule already implemented in
  the domain (the instruction this phase is built under).
- **Geofence cooldown/duplicate-suppression** (Phase 2 §22.3: "a minimum dwell", "a cooldown...
  per (trip, stop, event-type)"): genuinely repository-dependent (it needs
  `GeofenceCrossingRepository.latest_for_trip`, Phase 8.1) and squarely an application-layer
  concern — but no approved document states the cooldown/dwell *duration*. Building a
  pre-check with an invented number would be inventing a business rule, not implementing one;
  `latest_for_trip` exists specifically so this validator can be added once an approved value
  (an NFR sign-off or an `org_settings` field) exists.

Add a validator here only once a genuinely repository-dependent, approved pre-condition needs
one — same standing rule `fleet_device.domain.services`/`organization.domain.services` state
for their own modules.
"""
