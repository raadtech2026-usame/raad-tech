# Device Onboarding Readiness Audit

**Date:** 2026-07-25. **Scope:** "A brand-new physical MDVR/GPS terminal arrives from the
supplier. After a technician registers it through the Register Device wizard, is the platform
already capable of handling its entire lifecycle?" Every claim below was checked directly against
source (file:line, verbatim quotes) — this is not a summary of documentation, it is an
independent re-verification of it. Where this audit's findings differ from `CLAUDE.md`'s own
claims, that is called out explicitly rather than silently reconciled.

**Headline finding:** device *registration* and raw *GPS ingestion into Postgres* are genuinely
complete and working end to end. Almost everything downstream of that — live "latest position"
delivery, map-based live tracking, video, and every event type except plain position reports
(no boarding/alighting/overspeed/SOS/ignition, and geofence/device-connectivity events that exist
in code are never actually triggered or consumed) — is either unbuilt or built-but-disconnected.
A real device powered on today would successfully register, authenticate (in the weak sense
described below), and have every GPS fix land in `vehicle_positions` — and that is the full extent
of what would work without further changes.

---

## 1. Device Registration

**Status: Complete and working.**

- `POST /devices` → `POST /devices/{id}/activate` → `POST /devices/{id}/assign` is a real,
  enforced state machine (`fleet_device/domain/entities.py`'s `DeviceLifecycleState`:
  `registered → activated → assigned`, illegal transitions raise `RuleViolationError`). Validated
  by the frontend's `RegisterDeviceWizard` (register → activate → assign, resumable on partial
  failure — see Task 1's fix, which was a bug in this same wizard, now resolved).
- Persistence is real Postgres rows (`devices`, `device_assignments`), with unique-value-object
  validators for `terminal_id`/`imei`/`iccid`/`serial_number`.
- **Gap, not a defect:** there is no pre-tenant "hardware pool" (`device_inventory`, mentioned
  only as `[PROPOSED — ADR required]` in `docs/architecture/RAAD_DevicePlane_Architecture_v0_1_draft.md`
  §3.5). `POST /devices` requires `organization_id` up front — a device cannot be registered into
  a stock pool and allocated to a school later; it's tenant-bound from creation. Fine for the
  "technician registers a device for a specific school" flow this audit assumes, not fine for a
  distributor/RMA/pre-provisioning workflow.

## 2. Device Gateway

**Status: Registration/heartbeat/position transport works. Authentication is effectively
nonexistent. No alarm/event protocol support of any kind.**

- **Protocol coverage** (`services/device-gateway/src/vendors/lsz/server.py:55-87`): exactly three
  LSZ message types are handled — `V101` (registration), `V109` (heartbeat), `V114` (position).
  Nothing else. No alarm message, no geofence message, no media-channel (video/file-transfer)
  message — confirmed absent, not just undocumented.
- **TCP listener**: real and reasonably hardened — 90s idle timeout, 8KB frame-size ceiling
  (`FrameTooLargeError` → connection closed), malformed-but-delimited frames are logged and
  dropped without killing the connection.
- **Device authentication: none.** Acceptance is decided purely by whether the device's serial
  number is already present (and `is_provisionable`) in the registry projection —
  `provisioning_port.py`'s own docstring: *"no cryptographic authentication mechanism of any kind
  is documented... registration validity is decided purely by whether the submitted device serial
  number is already present in the center's own database."* The serial number itself travels in
  plaintext over unencrypted TCP. This is a flagged, accepted gap (ADR-0009's Consequences section
  names network-layer compensating controls — mTLS/IP allow-listing/DMZ — as the required
  mitigation) but **none of those compensating controls are implemented either** — this audit
  found no TLS anywhere in `src/connection/` or `src/vendors/lsz/server.py`, and no IP allow-list
  enforcement in the connection manager.
- **Heartbeat/online-offline**: real and working — `V109` promotes a session to `ONLINE`
  (publishes `DeviceOnline`); a 120s silence sweep or a dropped connection publishes `DeviceOffline`
  with a `reason`. **Real gap found**: only the heartbeat handler calls `touch()`; the position
  handler does not. A device sending only `V114` position reports without `V109` heartbeats would
  never be promoted to `ONLINE` and would eventually be swept as `session_expired` even while
  actively reporting GPS.
- **Alarm bits are never decoded.** `alarm_flags` is parsed as an opaque 64-bit hex value, range-
  clamped to fit the backend's 32-bit `AlarmFlags` value object, and passed through unchanged —
  there is no per-bit mapping to SOS/overspeed/fatigue/geofence/etc. anywhere. The clamp itself was
  a real bug fix (commit `6c517ac`, ADR-0012) that stopped *all* position ingestion from silently
  failing forever — but it explicitly did not, and was never meant to, add alarm interpretation.
  `0` after clamping means "unmapped/unknown," not "verified no alarms."
- **`DeviceAlarmRaised` is defined but never constructed.** The event class exists (shared
  publishing machinery is ready) but no vendor adapter — LSZ or the dormant JT/T 808 code —
  ever instantiates one. Confirmed by exhaustive grep: the only non-test hit is inside the class's
  own docstring.

## 3. GPS

**Status: Ingestion → Postgres works. Ingestion → Redis "latest position" does not exist.**

- `V114` → `MdvrPositionHandler` → `DevicePositionReported` → published to the shared
  `raad:events` Redis Stream → consumed by the backend's `DevicePositionReportedProcessor` →
  `TrackingApplicationService.record_vehicle_position` → a real `vehicle_positions` row. This
  entire chain is real, tested, and (per ADR-0012's own live-verification pass) has been proven
  against an actually-running Postgres, not just unit tests.
- **`vehicle:{id}:last` (the Redis key `GET /tracking/vehicles/{id}/latest` depends on) has no
  writer anywhere in this codebase — neither the device-gateway nor the backend.**
  `RedisLatestPositionPort` implements only `get_latest`; there is no `set`/write method on the
  port or its interface at all. The Business API's own tracking-subscriber docstring documents
  this as a still-open item, and this audit independently confirmed it via exhaustive grep across
  both deployables. Practical effect: `GET /tracking/vehicles/{id}/latest` will 404 (or 500 if
  Redis isn't configured at all) for every vehicle, forever, in this codebase's current state —
  regardless of how many real positions have landed in Postgres.
- The retention job (`prune_vehicle_positions`) and cursor-paginated trip-position history
  (`GET /tracking/trips/{id}/positions`) both work correctly against the Postgres side of this
  pipeline.

## 4. Live Tracking

**Status: The WebSocket delivery mechanism is real and would work. There is no frontend page to
use it, and no live "who's on this bus" concept exists at all.**

- `/ws/tracking` has its own dedicated Redis Streams consumer group (`ws-tracking`, independent
  from the worker process's own group) subscribing to the *same* `DevicePositionReported` events
  the Postgres-persistence path consumes. If a client subscribed and a real device were sending
  positions, that client would receive live pushes — this is the one "live tracking" path in the
  whole platform that is actually wired end to end on the backend side.
- **The frontend has zero live-tracking UI.** `/platform/tracking` and `/org/tracking` (the actual
  nav routes — not `/live-monitoring`, which doesn't exist as a route path at all; that's a
  feature-folder name only, containing a single empty `.gitkeep`) both render `PlaceholderPage`.
  A generic, well-built `useWebSocketChannel` hook exists (`shared/hooks/useWebSocket.ts`) but is
  called from nowhere — confirmed the only reference to it in the whole frontend is its own
  definition. `MapView`/`MapboxMapProvider` are implemented and unit-tested in isolation but are
  never rendered by any real page. This is exactly Phase F7's job, and F7 has not started — this
  matches `CLAUDE.md`'s own status, independently confirmed here.
- **Vehicle/route/student linkage is entirely static, not live.** `Trip.vehicle_id`/`route_id`
  are set once at `Trip.schedule()` and never change; there is no `Trip.change_vehicle()`. GPS
  fixes carry an optional `trip_id` but never mutate the `Trip` aggregate itself.
  `StudentAssignment.vehicle_id` is a standing, non-trip-specific, optional field — there is no
  concept of "which students are on this specific trip right now." **`trip_students` (Database
  Design §6.9's own "roster snapshot" table) does not exist as a migration anywhere** — confirmed
  by enumerating all 23 migration files. Even the documented version of that table would carry
  "no boarding fields (D1)" by design, so building it would still not answer "who is currently
  aboard," only "who was assigned to this trip."

## 5. Video

**Status: Effectively 0% functional beyond a database row saying someone asked.**

- `services/jt1078/src/` is five empty `.gitkeep` files. No language/runtime has been approved.
  Nothing to evaluate.
- `VideoSession` (the control-plane aggregate) and all three routes (`/video/live`,
  `/video/playback`, `/video/sessions/{id}/stop`) exist, correctly enforce D5 (Parent-never-reaches-
  video) before doing anything, and correctly persist a `VideoSession(REQUESTED)` row. Then:
  **`POST /video/live` and `POST /video/playback` unconditionally raise `NotImplementedError`**
  because `VideoProviderPort` is never bound in `core/di/bootstrap.py` — confirmed by grep, it is
  imported and `try_resolve`d but never `bind_singleton`d anywhere. `POST /.../stop` is the only
  one of the three that succeeds (it only closes the local control record).
- No device signaling, no media relay, no stream URL/token of any kind is produced anywhere in
  this platform today.

## 6. Events (boarding / alighting / overspeed / geofence / SOS / ignition / offline-online)

**Status: 5 of 7 have zero implementation anywhere. Geofence is fully coded but dead (never
triggered). Offline/online is published by the device-gateway but never consumed by the backend.**

| Event | Domain model exists? | Ever published in production? | Ever consumed/persisted? |
|---|---|---|---|
| Boarding | **No** — explicitly out of scope everywhere it's mentioned | — | — |
| Alighting | **No** — same | — | — |
| Overspeed | **No** — only exists as one example name in `AlarmFlags`'s docstring; `alarm_flags` is never inspected/branched on anywhere | — | — |
| SOS | **No** — same as overspeed, doc-mention only | — | — |
| Ignition | **No** — explicitly excluded from the position schema | — | — |
| Geofence (approaching/entered/arrived/exited) | **Yes** — 4 domain events, a `geofence_events` table, `GeofenceEvaluationService` (haversine) | **No** — exhaustive grep found zero production callers of `record_geofence_crossing`/`evaluate_geofence` anywhere (position ingestion, routers, scheduler); only unit tests call it | N/A — never generated, so never persisted |
| Device Online/Offline | **Yes**, and genuinely published by the device-gateway (heartbeat/session-sweep-driven, real) | **Yes**, onto the shared `raad:events` stream | **No** — this audit found zero backend consumer/processor for either event. `fleet_device`'s own router docstring confirms `devices.last_seen_at` "is always NULL" as a result — no JT808/device-plane consumer exists in `backend/raad` to write it |

This table is the single most important finding of this audit: two of the seven requested event
types have *any* code path that fires in production (geofence and device-connectivity), and both
of those are one-sided — geofence never fires at all, device-connectivity fires but is thrown
away, since nothing on the backend listens for it.

## 7. Notifications

**Status: The delivery pipeline (aggregate, FCM tokens, CR-1 policy, WebSocket push) is real and
correct. Only 2 of its 4 wired triggers are actually reachable; there are zero safety/hazard
triggers.**

- Exactly four `EventProcessor`s are registered with the Notification Worker:
  `TripStartedNotifier`, `TripEndedNotifier`, `VehicleApproachingStopNotifier`,
  `VehicleArrivedAtOrganizationNotifier`. All four correctly enforce `SubscriptionAccessPolicy`
  (CR-1) before creating a `Notification`.
- `TripStarted`/`TripEnded` are real and reachable (fired by `Trip.start()`/`Trip.end()`).
  `VehicleApproachingStop`/`VehicleArrivedAtOrganization` are wired correctly but **dormant** —
  per §6 above, nothing ever publishes their source events.
- No driver-targeted or school/org-staff-targeted notification trigger was found among the four
  processors — these all resolve parent recipients via `SubscriptionAccessPolicy`, which is
  specifically the parent-subscription-lapse policy. No distinct driver/school notification flow
  exists.
- No notification trigger exists for anything this audit's §6 table shows as unbuilt or
  unconsumed: no SOS alert, no overspeed alert, no device-offline alert to parents/school/RAAD
  staff. Given device connectivity events are already being thrown away (§6), even the
  comparatively simple "notify someone when a bus's tracker goes offline" capability cannot fire
  today, despite the underlying `DeviceOffline` event already existing and being published.

## 8. Persistence

**Status: Position data has a complete, verified persistence path. Nothing else device-plane-
related does.**

- `vehicle_positions`: real rows, proven against a live Postgres instance (ADR-0012).
- `geofence_events`: table exists, will remain permanently empty in this codebase's current state
  — nothing ever inserts into it.
- Device online/offline transitions: **no durable record anywhere.** Not in `devices.last_seen_at`
  (confirmed always NULL), not in `audit_entries` (that shared-kernel table is written
  transactionally by each module's own `UnitOfWork.commit()` — since no module's UnitOfWork ever
  processes these events, no audit row is ever produced for them either), not anywhere else. The
  events live briefly in the Redis Stream and are then effectively lost.
- Alarm data: never even constructed (`DeviceAlarmRaised` is unused), so nothing to persist.
- **Net finding**: today, the *only* durable trail a real device's activity leaves in this
  platform is its raw GPS fixes. Every other fact about that device — was it ever offline, did it
  raise any alarm, did a student board it — leaves no record at all, even though several of the
  tables/columns meant to hold that record (`devices.last_seen_at`, `geofence_events`,
  `audit_entries`) already exist and are schema-ready to receive it.

## 9. APIs

Every route that exists today, relevant to this audit (method / path / permission / what it
actually does). Compiled directly from each module's `routers.py`.

**`fleet_device`** — `POST /vehicles`, `GET /vehicles`, `GET/PATCH /vehicles/{id}`,
`POST /devices`, `GET /devices`, `GET/PATCH /devices/{id}`, `POST /devices/{id}/activate`,
`POST /devices/{id}/assign`, `POST /devices/{id}/reassign`, `POST /devices/{id}/unassign`. Missing:
`GET /devices/{id}/status` (connectivity — blocked on §6/§8's findings), any camera-registration
route, any soft-delete route.

**`tracking`** — `GET /tracking/vehicles/{id}/latest` (blocked on §3's Redis-writer gap, see
above), `GET /tracking/trips/{id}/positions` (cursor-paginated, works), `WS /ws/tracking` (works
mechanically, no producer of interest reaches it in practice, no frontend consumer exists).
Missing: any geofence-history read route (the application-layer query exists, no HTTP route).

**`video`** — `POST /video/live`, `POST /video/playback` (both always 500, §5), `POST
/video/sessions/{id}/stop` (works, closes a local record only).

**`notifications`** — `POST/DELETE /notifications/tokens`, `GET /notifications`,
`GET /notifications/{id}`, `POST /notifications/{id}/read`, `WS /ws/notifications`. Missing:
`notification_preferences` (no aggregate built at all).

**`transport_ops`** (trips/student-assignments/routes-stops only) — full CRUD-ish surface for
`routes`/`stops`/`trips`/`student-assignments` exists per API Contracts. Missing: per-stop
update/removal/reorder HTTP routes, `Trip.interrupt`/`resume` HTTP routes (both implemented at
the application layer only).

**`platform_audit`** — `GET /admin/audit` (read-only, correct).

**Runtime failure points found** (routes that exist but will always/conditionally fail):
`POST /video/live`, `POST /video/playback` (always, no provider bound);
`GET /tracking/vehicles/{id}/latest` (always 404/500 in this codebase's current state, no Redis
writer); every `tracking`/`video` route that calls `resolve_tracking_decision`/`enforce_d5`
(500 if `RAAD_DB__URL` unset, since `ScopeResolver` binds conditionally on it).

## 10. Missing pieces — precise checklist

What is genuinely required, in order of blocking severity, before a real production device can be
powered on and immediately start sending GPS, telemetry, events, live tracking, and video with no
further platform changes:

**Blocks "GPS shows up live anywhere a human can see it":**
1. A writer for `vehicle:{id}:last` in Redis. Per the JT808 Technical Design, this is meant to be
   the device-gateway's own job, written on every accepted position report, alongside (not instead
   of) publishing `DevicePositionReported`. Currently absent on both sides.
2. A real frontend page at `/platform/tracking` / `/org/tracking` (Phase F7) that renders
   `MapView` and calls the already-built-but-unused `useWebSocketChannel` hook against
   `/ws/tracking`. Both prerequisite pieces (Mapbox, the WebSocket hook, the backend fan-out) exist
   in isolation; nothing currently connects them.

**Blocks "the platform reacts to anything other than a bare position fix":**
3. A device-connectivity consumer on the backend side: something that subscribes to
   `DeviceOnline`/`DeviceOffline` off the broker and writes `devices.last_seen_at` (and, ideally, a
   notification trigger for "this bus's tracker just went offline"). The events are already
   published — only the consumer is missing.
4. A real caller of `TrackingApplicationService.record_geofence_crossing` from the live
   position-ingestion path (or a scheduled sweep over recent positions) — the domain logic,
   table, and two of four notification triggers already exist and are simply never invoked.
5. An LSZ (or JT808) alarm-message handler, plus a per-bit mapping from this vendor's raw
   `alarm_flags` integer to the JT/T-808 alarm taxonomy (Hardware Analysis §5) — needed before
   SOS/overspeed/ignition/etc. can mean anything. Currently the field is carried through as an
   opaque, clamped integer with no interpretation anywhere.
6. Domain modeling for boarding/alighting (a `trip_students`-shaped table plus real events) —
   currently doesn't exist even on paper as an implementable design (D1 explicitly excluded
   boarding fields from the one place a roster table is documented).

**Blocks device-plane trust:**
7. Some network-layer compensating control for LSZ device authentication (mTLS, IP allow-listing,
   or DMZ isolation, per ADR-0009's own Consequences section) — today, any TCP client that knows
   or guesses a valid device serial number can impersonate that device with zero further
   verification.
8. A fix for the heartbeat-vs-position `touch()` asymmetry in the device-gateway (§2) — a
   position-only device (no heartbeats) will eventually be swept offline while still actively
   transmitting.

**Blocks video entirely:**
9. A decided runtime for `services/jt1078/` (still not chosen) and a bound `VideoProviderPort`
   adapter — nothing here has started.

**Lower-severity / deferred by design, not blocking a basic "device sends GPS and someone sees a
dot on a map" outcome:** a pre-tenant device inventory/allocation flow (§1); driver/school-targeted
notifications; SOS/overspeed/ignition end-to-end (subsumed by item 5 above once the bit-mapping
exists, but the notification/UI layer for them still wouldn't exist yet either).

---

## Cross-check against `CLAUDE.md`

This audit's findings are consistent with `CLAUDE.md`'s own documented gaps everywhere they
overlap (Redis latest-position write path "still genuinely unbuilt," `VideoProviderPort`
unbound, F7 not started, `trip_students` not built). This audit adds detail `CLAUDE.md` did not
previously carry: the geofence pipeline being fully coded yet never invoked, the device-gateway
having zero alarm/event protocol support, `DeviceOnline`/`DeviceOffline` being published but never
consumed on the backend side, and the heartbeat/position `touch()` asymmetry. `CLAUDE.md` has been
updated with a pointer to this document (Frontend Implementation Status, ahead of the Phase F7
section) so it isn't rediscovered from scratch next time F7 planning begins.
