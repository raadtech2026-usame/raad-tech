# ADR-0018: Device Inventory & Allocation

## Status
Accepted (direct user decision — RAAD business model realignment, 2026-07-28). Formalizes the
already-drafted, previously-unaccepted design in `docs/architecture/
RAAD_DevicePlane_Architecture_v0_1_draft.md` §3.5 ("[PROPOSED — ADR required] Platform inventory
(`device_inventory`)", Gap G3) — this ADR adopts that draft's own recommended Option 3 verbatim,
rather than inventing an alternative.

## Context
The new RAAD business model's device workflow is: Supplier → RAAD registers the MDVR/GPS device →
RAAD assigns the device to an Organization → the Organization immediately sees the assigned
device → the Organization creates a Vehicle → the Organization links Vehicle + Driver + Device.

Two conflicts with the current, already-implemented Device Domain Overhaul design:

1. **No pre-tenant device state exists.** `Device.__init__`/`Device.register()`
   (`raad/modules/fleet_device/domain/entities.py`) require `organization_id: OrganizationId` —
   non-nullable, from the first line of code — and `RegisterDeviceRequest.organization_id`
   (`api/schemas.py`) is likewise required. A device cannot be represented as "RAAD has it, not
   yet given to any school" today. This is a known, already-documented gap (draft doc §3.5, Gap
   G3): "`devices.organization_id` is `NOT NULL` — correct for tenant isolation, but it makes
   factory/warehouse stock unrepresentable."
2. **Org Admin has zero visibility into devices, by deliberate design.** The Device Domain
   Overhaul (see `CLAUDE.md`'s Fleet Device section) intentionally stripped `org_admin` of every
   `fleet_device.devices.*` permission, including `.read` — RAAD-owns-hardware, org visibility
   flows only through `Vehicle.tracking_status.last_seen_at` (no device identity at all). The new
   model's "Organization immediately sees the assigned device" cannot be satisfied without *some*
   device-read access for `org_admin` — this is a genuine, narrow reversal of that posture, not
   an oversight to route around silently.

## Decision

### 1. `device_inventory` — a platform-scoped pre-tenant pool (draft §3.5 Option 3, adopted)
New table `device_inventory` (Database Design-style, `.claude/rules/naming.md` conventions):
`id` (ULID), `serial_number`, `imei`, `iccid`, `model`, `vendor`, `state ENUM(manufactured,
in_stock,allocated,scrapped)`, `+ standard audit columns` (`.claude/rules/database.md` #4). **No
`organization_id`** — like `regions`/`plans`, this is platform-level stock, not tenant-owned.
Owned by `fleet_device` (the module that already owns `devices`/`device_assignments`).

A new `DeviceInventoryItem` aggregate (`fleet_device/domain/entities.py`) with `receive()`
(creates a `manufactured`/`in_stock` row — the exact initial state is an implementation choice,
not user-facing this phase) and `allocate(organization_id, ...)`. **`allocate()` does not itself
create a `devices` row** — it only transitions `device_inventory.state → allocated` and records
which org it was allocated to (a plain `organization_id` value on the event, not a persisted
column on `device_inventory` itself, consistent with the draft's "like regions, no
organization_id" framing). The actual `devices` row is created by the *existing*
`Device.register()` factory, called immediately after allocation, referencing the inventory item
by a new `devices.inventory_id` (nullable FK-by-id-only, `.claude/rules/database.md` #3) — this
is the draft's own "Allocation to a tenant creates the `devices` row and links back by
`inventory_id`" resolution, applied exactly.

**Zero change to the existing `devices` table's `organization_id NOT NULL` constraint, zero
change to `Device`'s existing lifecycle state machine (`registered→activated→assigned`,
`suspended`, `retired`).** Today's device→vehicle assignment code (`DeviceAssignment`) is
completely untouched — this ADR only adds a new *earlier* stage in front of the existing
`Device.register()` call, it does not modify what that call does.

### 2. New routes
- `POST /device-inventory` (RAAD-only — same permission holders as today's `fleet_device.
  devices.create`: `founder`, `support_staff`) — receives new stock.
- `POST /device-inventory/{id}/allocate` (RAAD-only, body: `organization_id`) — allocates one
  inventory item to an organization, creating the `devices` row in the same application-service
  call. Mirrors the existing `POST /devices/{id}/assign` (device→vehicle) pattern one level up
  (inventory→org, rather than device→vehicle).

### 3. `org_admin` gains `fleet_device.devices.read` — narrow, tenant-scoped, read-only
A new RBAC grant, resolved through the existing `ScopeResolver` (ADR-0005) exactly like every
other tenant-scoped grant — `org_admin` can list/view devices where `organization_id` matches
their own org (never another org's, never inventory items). **No other `fleet_device.devices.*`
permission changes** — `org_admin` still cannot create, update, activate, assign, reassign, or
unassign a device; RAAD (`founder`/`support_staff`) retains exclusive device lifecycle control.
This is the minimum grant that satisfies "Organization immediately sees the assigned device"
without reopening device management — Org Admin can now *see* a device (to pick it when linking
Vehicle + Driver + Device) but not touch its lifecycle.

## Consequences
- `fleet_device` gains one new table, one new aggregate, two new routes, one new nullable FK
  column (`devices.inventory_id`) — additive only, no existing column/behavior changes.
- Org visibility into devices widens from "nothing" to "read-only, own-org devices only" — a
  real, flagged, narrow RBAC reversal of the Device Domain Overhaul's original posture, scoped
  exactly to what the new business model requires and no further.
- The device-gateway (`services/device-gateway/`) and its `DeviceProtocolAdapter`/registry
  projection (ADR-0009/0010) are **unaffected** — they already resolve `{device_id,
  organization_id, vehicle_id}` from the existing `devices`/`device_assignments` tables; nothing
  about how a physical device authenticates or streams telemetry changes.

## Verification
- Unit: `DeviceInventoryItem` state machine (`manufactured/in_stock/allocated/scrapped`,
  idempotent same-state no-ops matching every other undocumented-transition-graph aggregate's
  precedent in this codebase).
- Integration: allocate → a real `devices` row appears with the correct `organization_id` and
  `inventory_id`; tenant-scoped visibility proven both directions — an Org Admin sees only their
  own org's allocated devices, never another org's, never un-allocated inventory.
- `tests/architecture/` gate suite re-run — confirms no cross-module DB read was introduced.
- `alembic upgrade head` / `downgrade -1` / `upgrade head` round-tripped clean.

## References
- `docs/architecture/RAAD_DevicePlane_Architecture_v0_1_draft.md` §3.5 (Gap G3, the adopted
  design)
- `docs/architecture/device-onboarding-readiness-audit.md`
- `.claude/rules/database.md` #2, #3, #4
- `.claude/rules/security.md` #2 (tenant isolation defense-in-depth)
- `raad/modules/fleet_device/domain/entities.py`, `raad/modules/fleet_device/api/routers.py`
- `docs/architecture/adr/0005-scope-resolver.md` (`ScopeResolver`, reused unchanged for the new
  `org_admin` grant)
