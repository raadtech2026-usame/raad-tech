# ADR-0031: Fleet Overview Online-Vehicles Read Model

## Status
Accepted (direct user decision — All Vehicles fleet-map mode, frontend redesign follow-on, 2026-08-23).

## Context

The Live Tracking frontend redesign needs an "All Vehicles" map mode: a fleet-overview view
showing every currently-online vehicle as its own marker, updating live, with no camera/video
initialization at all (explicitly out of scope — 10 buses × 4 cameras = 40 possible streams is
never the desired behavior for this mode).

**No bulk data source for "which vehicles are online" exists anywhere in this backend today** —
confirmed by reading the actual code, not assumed:

- `GET /vehicles` (list) deliberately returns `tracking_status: null` on every row
  (`VehicleApplicationService.get_vehicle_by_id`'s own docstring: "avoids an N+1 device lookup
  per list page") — this was a correct call for the list route, but it means the list response
  itself carries no online signal.
- `GET /vehicles/{id}/device-assignment` → `GET /devices/{id}` resolves online status, but only
  per vehicle (two calls each) — there is no bulk/list variant.
- `GET /devices?filter[is_online]=true` (list) returns online devices, but `DeviceResponse`
  (`fleet_device/api/schemas.py`) carries no `vehicle_id` field at all — there is no reverse
  device→vehicle mapping in the wire contract.
- No REST endpoint anywhere returns "latest positions for all vehicles" in bulk. `tracking`'s own
  `LatestPositionPort`/`GET /tracking/vehicles/{id}/latest` is single-vehicle only.

Building the online-vehicle set from these alone would require a REST fan-out bounded only by the
existing ≤100-vehicle page cap: up to ~100 `GET /vehicles/{id}/device-assignment` calls plus ~100
`GET /devices/{id}` calls, purely to determine *who is online* — before a single realtime update
is even requested. This is exactly the N+1 shape `tracking_status: null` was deliberately
introduced to avoid elsewhere in this same codebase; repeating it here for a brand-new feature
would be inconsistent with that established precedent.

**A second, independently confirmed gap**: `LatestPositionPort` (`vehicle:{id}:last` in Redis) has
no writer for the live, primary JT808 adapter. `services/device-gateway/src/gateway.py`
constructs `Jt808Server` without a `latest_position_writer` — only the dormant `MdvrServer`/LSZ
adapter receives one. Live-verified: `KEYS vehicle:*` against the running Redis is empty despite
the physical bench unit streaming continuous GPS for over an hour. This is not new — it is the
same gap CLAUDE.md's own "Device onboarding readiness audit" section already names as open — but
it directly affects this ADR's own `position` field, which is `null` for every vehicle today as a
result. Fixing the JT808 writer wiring is a separate, larger device-plane change, explicitly out
of this ADR's scope.

**Realtime updates**: `/ws/tracking` (`backend/raad/modules/tracking/api/ws.py`) enforces exactly
one active vehicle subscription per connection (`handle_subscribe` unregisters the prior
`vehicle_id` before registering a new one on the same connection — a deliberate, documented
simplification, not a bug to route around). Since the limit is per *connection*, not per browser
tab, N independent WebSocket connections (one per online vehicle) reuses this exact, already-
tested primitive with zero backend protocol change — the same "N independent instances of a
single-item hook" shape already proven safe in this codebase for `MultiCameraVideoPanel`/
`CameraTile` (N independent `useVideoSessionController` instances, one per camera).

**Scalability of N raw WebSocket connections, evaluated before committing to this approach**
(read `ConnectionManager`, `handle_subscribe`, `_handle_position_event`, and the configured DB
pool directly, not estimated):

- `ConnectionManager` is an in-memory, single-process registry (its own docstring discloses
  this — correct for today's one-API-process deployment).
- Every subscribe (`resolve_vehicle_tracking_context`) and every position push
  (`resolve_tracking_decision`, per subscriber) can touch Postgres.
- The configured pool is small by default: `pool_size=5` (+ SQLAlchemy's own default
  `max_overflow=10` ⇒ ~15 concurrent DB connections total), **shared with every other concurrent
  API request**, not reserved for this feature.

| Vehicles | N WS connections | Verdict |
|---|---|---|
| 10 | 10 | Trivial — cheaper than the existing 4-camera video wall. |
| 100 | 100 | Works, but opening the fleet view fires ~100 near-simultaneous auth handshakes + Postgres-touching subscribe checks against a ~15-connection pool — a real, disclosed latency burst affecting all concurrent API traffic for that moment. |
| 500+ | 500+ | **Not clean.** Same burst, 5× worse, and 500 persistent connections from one browser tab is architecturally a smell regardless of raw asyncio feasibility. |

RAAD's realistic per-organization fleet size (school/transport operators) is tens to a couple
hundred buses, not thousands — no NFR target in
`docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §13.1 suggests otherwise. Given that,
and given the explicit instruction not to invent a new multi-vehicle subscribe protocol without
approval, this ADR caps rather than redesigns `/ws/tracking`.

## Decision

### 1. New endpoint: `GET /tracking/vehicles/online`
Owned by `tracking` (the module that already owns realtime vehicle visibility), mirroring the
ADR-0020/ADR-0023 precedent of a new composing application service living in the module that
most naturally owns the *capability*, constructor-injected with the other modules' own
application services — never a cross-module DB read (`.claude/rules/backend.md` #3), verified
clean against the architecture-gate module-boundary test suite (10/10 passing after this change).

### 2. Two small, additive `fleet_device` methods — no schema/migration
- `DeviceRepository.list_online_with_active_assignment()` (+ its
  `SqlAlchemyDeviceRepository` implementation): one JOIN query
  (`devices` ⋈ `device_assignments` on `unassigned_at IS NULL`, filtered `is_online = true`),
  scoped exactly like every other `list_*` method (`_apply_scope`, ADR-0021). Returns the thin
  `OnlineDeviceAssignment` projection (`device_id`, `terminal_id`, `vehicle_id`) — a pure
  read-model row, not a reconstructed `Device` aggregate, the same posture `count_total`/
  `count_online` already establish for KPI-only queries.
- `VehicleRepository.list_by_ids(vehicle_ids)`: a single scoped `WHERE id IN (...)` lookup — the
  bulk sibling of the existing single-`get()`, for a caller that already knows exactly which
  vehicles it needs.

Both stay entirely inside `fleet_device`'s own module — its own tables only, its own scope
enforcement, its own tested pattern, exposed as one new method each on
`DeviceApplicationService`/`VehicleApplicationService`.

### 3. One small, additive `tracking` port method — no schema/migration
`LatestPositionPort.get_latest_many(vehicle_ids)`: one Redis `MGET` for every requested key
(concrete impl: `RedisLatestPositionPort`), never a `get_latest` loop — the identical "one round
trip, not N" reasoning applied at the cache layer that `list_by_ids` applies at the SQL layer.
Optional at the service level (`container.try_resolve`), mirroring
`TrackingApplicationService.get_current_vehicle_position`'s own "fail loudly only at the one
method that needs it" posture — without a reachable Redis, every vehicle's `position` is simply
`null`, never a 500.

### 4. `FleetOverviewApplicationService` (new, `tracking.application.services`)
Composes `VehicleApplicationService`/`DeviceApplicationService` (per-call UoW, mirroring
`PlatformStatsApplicationService.get_platform_stats`'s identical shape) plus `LatestPositionPort`.
Capped at `FLEET_OVERVIEW_MAX_ONLINE_VEHICLES = 100` — the existing convention this same feature
already established (`listVehiclesForTracking`'s own frontend page size) — sorted deterministically
by `vehicle_id`, with the true pre-cap count returned separately (`total_online`) so a caller with
more online vehicles than the cap gets an honest "showing X of Y" signal instead of a silent
truncation.

### 5. A real authorization gap found and fixed while wiring this route, not silently shipped
`tracking.vehicles.read_latest` (reused for the coarse RBAC gate — deliberately no new permission/
migration) is *also* held by `parent`, for their existing single-vehicle, CR-1-gated use case
(`GET /tracking/vehicles/{id}/latest`, `/ws/tracking`). This new *bulk* route has no per-vehicle
ownership check at all (an admin fleet-list view, matching `GET /vehicles`/`GET /devices` (list)'s
own posture, not the single-vehicle CR-1 posture) — reusing the permission alone would let a
parent's own mobile JWT list every vehicle in their organization, not just their child's. Fixed
with an explicit, migration-free role-set check (`_FLEET_OVERVIEW_ELIGIBLE_ROLES` — Founder/
Regional Manager/Support Staff/Org Admin only), mirroring `core.policies.video_access`'s own
identical `_VIDEO_ELIGIBLE_ROLES` shape for the exact same "the permission is broader than this
one route needs" mismatch. Regression-tested (`test_tracking_fleet_overview.py`).

### 6. Frontend
`useFleetVehiclePositions` (new hook) fetches this endpoint once for the initial snapshot, then
opens up to `total_online` (capped) independent `/ws/tracking` connections — reusing
`useWebSocketChannel`, the same primitive `useVehiclePosition` already uses — for realtime
updates. No REST polling anywhere. `MultiCameraVideoPanel`/`CameraTile`/`useVideoSessionController`/
`useMpegtsPlayer` are never touched or initialized in All Vehicles mode.

## Consequences

- **What this closes**: All Vehicles mode has a real, efficient (bounded round-trips regardless
  of fleet size), architecturally consistent data source, with zero schema change and zero new
  RPC/polling mechanism.
- **What remains open, disclosed not hidden**:
  - `position` is `null` for every vehicle today — the confirmed JT808 `LatestPositionWriter`
    wiring gap (Context, above). Populates automatically once that gap is separately closed; no
    change needed in this read model when it is.
  - The 100-vehicle cap is a real ceiling, not a soft default — an organization with more online
    vehicles than that will not see all of them live-tracked simultaneously. Raising it needs a
    real `/ws/tracking` protocol change (multi-vehicle subscribe per connection), explicitly not
    attempted here.
  - No dedicated live-DB integration test was added this pass for the two new repository
    methods (the SQL was verified by static review against the exact patterns
    `count_online`/`list_page` already use and passed the full architecture-gate + unit suite,
    but a real-Postgres round-trip test remains a disclosed follow-up).
