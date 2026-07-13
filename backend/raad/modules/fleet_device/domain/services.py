"""Domain services for the `fleet_device` module (Backend LLD §5.1).

None are defined in this phase. The candidates considered, and why each is placed elsewhere:

- **Reassignment** ("close the current active assignment, open a new one", LLD §5.2 /
  Phase 2 §19.2): finding the current active assignment requires a repository query
  (`active_for_device`, LLD §7.2) — I/O, which makes the flow an *application*-layer
  use-case (`ReassignDevice`, LLD §4.2 command skeleton), not a domain service (domain
  services are stateless operations over already-loaded entities, LLD §5.1). The pure parts
  of the flow already live on the aggregates (`DeviceAssignment.close`/`.open`,
  `Device.mark_assigned`/`.mark_unassigned`), and the `DeviceReassigned` event factory
  (`events.py`) is ready for that use-case to record.
- **One-active-binding-per-device/vehicle**: a cross-row invariant needing repository
  guards + the Database Design §5.4 unique indexes — application + database, per the LLD
  §5.2 placement note on the analogous one-active-trip invariant.
- **Plate / terminal-id uniqueness**: repository-backed pre-checks over DB `UX` constraints —
  application-layer validators, mirroring `organization.application.validators`'s reasoning
  for region-name uniqueness.

Add a domain service here only if a future documented rule genuinely spans two loaded
aggregates without I/O — same standing rule as `organization.domain.services`.
"""
