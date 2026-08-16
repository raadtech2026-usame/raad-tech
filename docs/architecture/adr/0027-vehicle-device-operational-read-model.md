# ADR-0027: Vehicle-Device Operational Read Model

## Status

**Accepted** (direct user decision, 2026-08-16 — confirmed exactly as proposed, no changes to the
design). Originally filed as "Proposed — pending user confirmation"; the user reviewed and
confirmed all six decisions verbatim (recorded below) and moved this ADR to Accepted in the same
conversation, without altering scope. No implementation code, route, schema, migration, or
frontend change exists yet — Accepted status authorizes the next phase's implementation
checklist (bottom of this document), it is not itself that implementation. Written per
`.claude/rules/workflow.md` #8 ("never implement business logic without an approved design").
Follows the same "write the design down, confirm, then implement" sequencing this codebase already
used for ADR-0017 (originally "Proposed, not accepted," later Accepted) and ADR-0026.

Numbered/sequential per `.claude/rules/documentation.md` #4, filed in `docs/architecture/adr/` (not
as an informal review doc under `docs/architecture/`) because — unlike the broader, still-forking
`video-notifications-architecture-review-2026-08-07.md` (explicitly "not an ADR... intended to
inform two future ADRs") — the two changes below are narrow, already-resolved single decisions with
no remaining fork, matching ADR-0018's shape (small, additive, one narrow permission question) far
more closely than a wide-open review.

### Confirmed decisions (verbatim, 2026-08-16)

1. `GET /vehicles/{vehicle_id}/device-assignment` — reuses `DeviceAssignmentResponse` unchanged;
   permission gate is **`fleet_device.devices.read`** (confirmed, no longer a flagged
   recommendation — see Change 1 and the Authorization section, both updated below); the vehicle
   is resolved through the existing, already-scoped vehicle lookup **before** calling
   `active_for_vehicle()`, never the reverse; nonexistent, out-of-scope, and unassigned vehicles
   all produce the same 404 with no disclosing distinction between them.
2. `is_online: bool` added to `DeviceDTO`/`DeviceResponse`, sourced directly from the existing
   `Device.is_online` field — no migration, no second source of truth.
3. `DeviceAssignment` aggregate and its repository are reused as-is — no new relationship, no new
   assignment model.
4. No new authorization model — `fleet_device.devices.read` and existing tenant/region scope
   enforcement are reused verbatim.
5. D5, ADR-0026 (Parent video access), JT808, JT1078, and the existing
   `DeviceAssignmentRepository` implementation are **not** modified in this phase.
6. The pre-existing `_apply_scope` gap on `DeviceAssignmentRepository.active_for_device`/
   `.active_for_vehicle` (Context point 4) stays explicitly documented as a separate, un-bundled
   follow-up — this ADR does not expand scope to fix it now.

## Context

**Product direction (user-directed, 2026-08-16):** RAAD wants a device-centric operational view —
an administrator selects one Vehicle and sees both capabilities of the one physical MDVR bound to
it:

```text
Vehicle
  └── active Device / MDVR
       ├── JT/T 808  → Live GPS      (map, current position, online status)
       └── JT/T 1078 → Live Video    (camera channel selection, live stream)
```

Two prior investigation passes (this conversation) inspected the actual code — not assumptions —
and found:

1. **The Vehicle↔Device relationship already exists, fully modeled, bidirectionally.**
   `DeviceAssignment` (`backend/raad/modules/fleet_device/domain/entities.py:522-613`) is its own
   aggregate: `{id, organization_id, device_id, vehicle_id, assigned_by, assigned_at,
   unassigned_at}`, active while `unassigned_at IS NULL`. Both lookup directions are already
   implemented, tested repository methods
   (`fleet_device/domain/repositories.py:160-178`,
   `fleet_device/infra/repositories.py:329-345`):
   `DeviceAssignmentRepository.active_for_vehicle(vehicle_id)` and `.active_for_device(device_id)`.
   `VehicleApplicationService.get_vehicle_by_id` (`application/services.py:169-194`) already calls
   `active_for_vehicle` internally today — it just discards everything except
   `device.last_seen_at` before building `VehicleDTO`, a deliberate Org-Admin least-privilege
   choice from the Device Domain Overhaul, not a technical limitation.

2. **No API contract currently exposes this relationship as a GET.** `VehicleResponse`
   (`fleet_device/api/schemas.py:34-46`) carries no `device_id`. `DeviceResponse`
   (`api/schemas.py:76-93`) carries no `vehicle_id`. The one schema that already carries both,
   `DeviceAssignmentResponse` (`api/schemas.py:132-140`), is returned only by the three write
   routes — `POST /devices/{id}/assign|reassign|unassign` — never by a `GET`.

3. **`Device.is_online` is real and persisted but never surfaced per device.** ADR-0020 added the
   column (`infra/models.py:114`), correctly mirrored end-to-end
   (`domain/entities.py:451-470` `record_last_seen`, `infra/mappers.py:151,195`), and used today
   *only* for the platform-wide "Online Devices" KPI aggregate
   (`DeviceRepository.count_online()`). Neither `DeviceDTO` (`application/queries.py:112-127`) nor
   `DeviceResponse` includes it per row — there is no way to ask "is *this* device online" via the
   API today.

4. **A genuine, pre-existing tenant-scope gap, found while verifying this design is safe to
   propose.** `SqlAlchemyDeviceAssignmentRepository.active_for_device`/`.active_for_vehicle`
   (`infra/repositories.py:329-345`) build a raw `select(DeviceAssignmentModel).where(...)` and
   execute it directly — **neither calls `self._apply_scope(...)`**, unlike every other repository
   read method ADR-0021 mandates ("tenant scope is enforced centrally, at the repository layer...
   never rely on a call site remembering to filter"). Today this is safe only by *ordering*: both
   existing callers resolve their starting id through an already-scoped lookup first —
   `get_vehicle_by_id` calls `active_for_vehicle` only after `uow.vehicles.get(...)` (itself scoped,
   `SqlAlchemyVehicleRepository.get` → `get_by_id` → `_apply_scope`,
   `infra/repositories.py:110-112`) has already 404'd an out-of-scope vehicle; ADR-0026's
   `find_owned_student_id_for_device` similarly depends on the surrounding parent-ownership chain.
   Neither repository method is scope-safe *on its own*. This matters directly for Change 1 below.

**Why now:** both gaps block the same next step — a frontend that can select one vehicle and drive
both a GPS panel and a Video panel from its one resolved device. Closing them is a prerequisite,
not the unified page itself (see Non-goals).

## Decision

Two additive, read-only changes, both fully contained inside the existing `fleet_device` module —
no cross-module reach, `.claude/rules/backend.md` #3 does not apply to either.

### Change 1 — `GET /vehicles/{vehicle_id}/device-assignment`

A new route on the existing `vehicles_router`, returning the vehicle's current active device
assignment.

**Reuses, unchanged:**

- `DeviceAssignmentResponse` (`api/schemas.py:132-140`) — the response schema, verbatim. No new
  schema.
- `DeviceAssignmentDTO` / `assignment_to_dto` (`application/queries.py:130-200`) — the application
  DTO and its mapper. No new DTO.
- `DeviceAssignmentRepository.active_for_vehicle` (`domain/repositories.py:171-178`,
  `infra/repositories.py:337-345`) — the actual lookup. No change to this method.
- `_assignment_dto_to_response` (`api/routers.py:172-184`) — the existing response-mapping
  function, already used by the three write routes.

**New, minimal:**

- One application-service method (naming: `get_active_device_assignment_for_vehicle`, placed on
  `VehicleApplicationService` — it already owns `get_vehicle_by_id`'s identical vehicle-first
  resolution shape) composing two calls that already exist:
  1. Resolve the vehicle via the existing, already-scoped path
     (`self._get_vehicle_or_raise(uow, vehicle_id)` — the same private helper `get_vehicle_by_id`
     already uses). **This step is what makes the endpoint scope-safe** — an out-of-scope or
     nonexistent `vehicle_id` raises `NotFoundError` here, before `device_assignments` is ever
     queried, exactly mirroring `get_vehicle_by_id`'s existing, proven precedent. This is a
     deliberate design choice given Context point 4 above: the new code must not call
     `active_for_vehicle` directly off a raw path parameter.
  2. Call `uow.device_assignments.active_for_vehicle(vehicle.id)` (unmodified) for the active
     assignment.
- One new route, `GET /vehicles/{vehicle_id}/device-assignment`, thin (Backend LLD §16.2 shape):
  parse path param → call the one service method → map via the existing
  `_assignment_dto_to_response` → return.

**Behavior:**

- Active assignment found → `200`, `DeviceAssignmentResponse`.
- No active assignment for an in-scope vehicle (never assigned, or unassigned) → `404
  NotFoundError` — this codebase's standard "optional single record, not found" convention, the
  same shape `GET /tracking/vehicles/{id}/latest` already uses for "no known position."
- Vehicle doesn't exist, or exists but is out of the caller's tenant/region scope → `404
  NotFoundError` — indistinguishable from each other (this codebase's established
  cross-tenant-probing-avoidance posture, `resolve_cr1_decision`/`resolve_d5_decision`'s own
  precedent), and now also indistinguishable from "no active assignment" at the HTTP layer. This
  is intentional, not a loss of information a legitimate caller needs.
- **Permission gate:** `fleet_device.devices.read` — the same permission that already gates
  `GET /devices` / `GET /devices/{id}`. **Confirmed** (2026-08-16, see Status) — not
  `fleet_device.vehicles.read`, even though the route is vehicle-scoped by path; see the
  Authorization section for the reasoning.
- **No new domain logic.** Zero changes to `DeviceAssignment`, `Vehicle`, or `Device` entities;
  zero changes to `DeviceAssignmentRepository`, `assignment_to_dto`, or `DeviceAssignmentDTO`.

#### Why a dedicated endpoint, not `device_id` embedded on `VehicleResponse`

1. **Avoids an N+1 / avoids a useless field on every list row.** `GET /vehicles` (list) is called
   far more often than any single vehicle's operational detail. Embedding `device_id` would force
   either an extra `device_assignments` lookup per list row, or a `device_id: null` on every row
   for a field most list callers never use — the exact N+1 concern
   `VehicleApplicationService.get_vehicle_by_id`'s own docstring already names as the reason
   `tracking_status` is detail-only, not list-embedded. A dedicated endpoint is naturally
   pay-for-what-you-use.
2. **Zero blast radius on a shared, heavily-reused contract.** `VehicleResponse` backs every
   existing vehicle list/detail view across both dashboards. A new, narrow endpoint changes nothing
   about it.
3. **Matches this module's own existing precedent.** `DeviceAssignmentResponse` already exists as
   a *dedicated* concept, deliberately separate from both `VehicleResponse` and `DeviceResponse` —
   the write routes already return it standalone rather than folding the assignment into either
   aggregate's response. A `GET` mirrors that shape instead of inventing a second, inconsistent way
   to represent the same relationship.
4. **Preserves the assignment's own lifecycle facts.** "The vehicle's active device assignment" is
   a distinct fact with its own `assigned_at`/`assigned_by`/`unassigned_at` — collapsing it into a
   bare `VehicleResponse.device_id` scalar would silently drop that; the dedicated resource keeps
   it for free, at no extra design cost.
5. **Keeps the new capability request-shaped, not field-shaped.** A separate route is one
   explicit, auditable line in "what can `fleet_device.devices.read` reach" — consistent with this
   module's own "routes are contract-driven, not capability-driven" discipline already stated for
   camera registration and device-inventory listing (`fleet_device/api/routers.py`'s module
   docstring) — rather than a field silently riding along on a response every existing
   `fleet_device.vehicles.read` holder already receives on every request.

### Change 2 — `is_online` on `DeviceDTO` / `DeviceResponse`

Add one field, sourced from data that already exists and is already correctly maintained:

- `DeviceDTO.is_online: bool` (`application/queries.py:112-127`), populated in `device_to_dto`
  (`application/queries.py:165-185`) from the existing `Device.is_online` domain attribute — one
  added line in an existing mapper function, no new function.
- `DeviceResponse.is_online: bool` (`api/schemas.py:76-93`), populated in `_device_dto_to_response`
  (`api/routers.py:144-169`) — one added line, no new function.
- **No new route.** Rides on the two already-existing, already-permission-gated routes:
  `GET /devices` (list) and `GET /devices/{id}`.
- **No migration.** `devices.is_online` (`infra/models.py:114`) already exists, already populated
  by the existing `DeviceConnectivityProcessor` / `Device.record_last_seen` (ADR-0020) — this
  change reads a value that is already correct today, it does not create one.
- **Single source of truth preserved.** The field is read, never computed, derived, or duplicated
  — explicitly avoiding the exact anti-pattern `TrackingStatusDTO`'s own docstring warns against
  for a *different* field (a fabricated "is_connected" inferred from `last_seen_at` alone). This
  field has no such honesty problem: `is_online` is already the real, event-driven signal that
  docstring says a fabricated boolean would need to be.

## Authorization / Security — explicitly preserved

- **Platform Admin roles remain scope-limited.** `fleet_device.devices.read` resolves through the
  same `ScopeResolver`/`TenantRegionScope` every existing route already uses — Founder
  unrestricted, Regional Manager/Support Staff limited to assigned regions/orgs, unchanged by
  either change.
- **Org Admin remains organization-limited.** Change 1's vehicle-first resolution means an Org
  Admin can only ever reach their own organization's vehicles (already enforced at
  `uow.vehicles.get`), so the device-assignment lookup can never surface another organization's
  device — this is the direct payoff of the ordering decision made in Change 1's design.
- **`fleet_device.devices.read` is the confirmed gate for Change 1** (2026-08-16, see Status —
  no longer an open recommendation). It is already held by: `founder` (`_ALL_PERMISSIONS`),
  `regional_manager`/`support_staff` (`_RAAD_STAFF_READ_ONLY`), `org_admin` (ADR-0018's narrow
  grant). It is **not** held by `finance_staff` (consistent with "billing scope only",
  `.claude/rules/security.md` #3) or `driver`/`parent` (mobile-only, no `fleet_device` access at
  all — unaffected either way). Chosen over `.vehicles.read` because the *payload* is
  fundamentally device data (an assignment record keyed by `device_id`), matching ADR-0018's own
  precedent of gating "can see a device" specifically on `.devices.read`.
- **D5 is unchanged.** Neither change touches `enforce_d5`, `resolve_d5_decision`, or
  `VideoAccessPolicy`. A future frontend using the new endpoint to discover `device_id` still must
  pass through the exact same D5 chain, keyed off that `device_id`, before any video session is
  created — *discovering* a device and *being authorized to stream from it* remain fully separate
  steps, exactly as today.
- **Parent video access / ADR-0026 is unchanged.** No change to `Parent`,
  `has_video_live_access`/`has_video_playback_access`, or `find_owned_student_id_for_device`.
- **JT808/JT1078 authorization is unchanged.** Both changes are Business-API-only, `fleet_device`
  module only — no device-plane or relay code is touched.
- **No cross-organization assignment data is exposed**, by construction (vehicle resolved first,
  through the already-scoped path) — not by adding new scope-filtering logic anywhere.
- **Flagged, not fixed here:** `DeviceAssignmentRepository.active_for_device`/`.active_for_vehicle`
  bypass `_apply_scope` (Context point 4). This ADR's own new call site is safe by construction
  (ordering), but the repository methods themselves remain generically unsafe for any *future*
  caller that doesn't pre-scope the same way. Recommend a small, separate follow-up to bring both
  methods in line with ADR-0021's mandatory pattern — out of scope for this ADR, explicitly not
  silently bundled in.

## Product purpose

Restated for whoever implements the next phase: the MDVR is one physical source providing two
capabilities. `device_assignments` already *is* the Vehicle↔Device relationship — these two
changes make it queryable and add the one missing per-device status field, so that a future
frontend can resolve, from a single vehicle selection: its active device, that device's online
status, and (via the already-existing, unchanged `GET /devices/{id}` → `cameras`) its camera
channels — enough to drive both a Live GPS panel and a Live Video panel from one selection, without
either panel needing its own separate device-discovery path.

## Non-goals (explicitly not designed or implemented by this ADR)

- Unified frontend Vehicle Operations page.
- `VideoPage` rewrite.
- `LiveTrackingPage` rewrite.
- Any new Vehicle↔Device database relationship or new assignment model — none is needed;
  `device_assignments` is reused exactly as it exists today.
- JT808 changes.
- JT1078 relay changes.
- Parent video access changes (ADR-0026 untouched).
- A new RBAC model — `fleet_device.devices.read` is reused verbatim, not replaced.
- HLS.
- Audio playback.
- Physical MDVR testing.

## Frontend follow-up (future phase, not this task)

Once this design is approved and implemented on the backend:

1. Expose Vehicle → Device via the new `GET /vehicles/{id}/device-assignment` endpoint.
2. Expose `Device.is_online` via the widened `DeviceResponse`.
3. Refactor the existing GPS (`LiveTrackingPage`) and Video (`VideoPage`) logic into reusable
   pieces rather than duplicating either page.
4. Evolve the existing single-vehicle Live Tracking view into the unified Vehicle Operations
   experience.
5. On vehicle selection, resolve the active device via (1), and drive both the GPS panel and the
   Video panel from that one resolved device — including its `is_online` status (2) and its
   `cameras` list (already available, unchanged, via `GET /devices/{id}`).

No frontend work is implemented as part of this ADR.

## Consequences

- Purely additive: two mapper-level field additions, one new route, zero schema/migration changes
  to any existing shape, zero new permissions (reuses `fleet_device.devices.read`), zero change to
  any existing response.
- `fleet_device.devices.read` becomes reachable from one additional route — worth a one-line
  mention in the RBAC-matrix derivation record (ADR-0004) at implementation time, for continued
  auditability.
- The `_apply_scope` gap in `DeviceAssignmentRepository` (Context point 4) remains open, now
  documented in two places rather than one — a good candidate for its own small, separate
  follow-up before or alongside implementation of Change 1.

## Implementation checklist (backend complete 2026-08-16 — frontend still not started)

- [x] Permission gate for Change 1 confirmed: `fleet_device.devices.read` (2026-08-16).
- [x] Added the new application-service method
      (`VehicleApplicationService.get_active_device_assignment_for_vehicle`, vehicle resolved
      first via the existing scoped `_get_vehicle_or_raise`, then `active_for_vehicle`) — no new
      repository method, no new DTO, exactly as designed.
- [x] Added `GET /vehicles/{vehicle_id}/device-assignment`, reusing `DeviceAssignmentResponse`
      verbatim.
- [x] Added `is_online: bool` to `DeviceDTO` + one line in `device_to_dto`.
- [x] Added `is_online: bool` to `DeviceResponse` + one line in `_device_dto_to_response`.
- [x] Unit tests (`tests/unit/test_fleet_device_application.py`): `VehicleDeviceAssignmentQueryTests`
      (found / none-active / nonexistent-vehicle-404s / none-after-unassign) and
      `RecordDeviceSeenTests.test_get_device_by_id_reflects_is_online`. 1402/1402 unit tests pass.
- [x] Integration tests (`tests/integration/test_fleet_device_repository.py`,
      `TenantIsolationRepositoryTests`, live Postgres, not skipped in this environment):
      same-org success, cross-org 404 (the scope-safety property Context point 4 exists to
      protect), unassigned-vehicle → `None`. All passing against a real database.
- [x] Recorded the new route: `fleet_device/api/routers.py`'s own module docstring (this
      codebase's established convention for API additions — `api.md` #5 means there is no
      hand-authored OpenAPI spec to edit), and `tests/contract/test_api_contracts_routes.py`'s
      `ALLOWED_UNDOCUMENTED_EXTRAS` (its own "add a citation, don't leave it silent" rule).
- [ ] Frontend design step (see Frontend follow-up) — **not started**, out of scope for this
      phase.

**Verification notes, 2026-08-16:** full backend suite run — `tests/unit` (1402 tests),
`tests/architecture` (10 tests, all four boundary gates), and `tests/integration` (279 tests,
live Postgres/Redis) — all pass except two **pre-existing, unrelated** failures confirmed (via
`git stash`) present on `main` before this change and outside `fleet_device` entirely: (1)
`tests/contract/test_api_contracts_routes.py`'s `NoSilentUndocumentedRoutesTests` already had 18
undocumented routes from ADR-0018/0019/0020/0022/0023 unaccounted for — this ADR's own one new
route is now correctly accounted for (down from 19 to the pre-existing 18); the other 18 were not
touched, per Consequences' "don't silently expand scope" posture. (2)
`tests/integration/test_realtime_broker_fanout.py::
test_two_distinct_consumer_groups_each_receive_the_published_event` fails deterministically,
unrelated to any file this ADR touches (Redis Streams consumer-group timing). Both flagged, not
silently fixed or hidden.
