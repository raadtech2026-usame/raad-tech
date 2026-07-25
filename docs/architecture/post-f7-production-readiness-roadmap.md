# Post-F7 Production Readiness Roadmap

**Date:** 2026-07-25. **Source of truth:** `docs/architecture/device-onboarding-readiness-audit.md`
(2026-07-25), re-verified line-by-line against the current source tree for this document — every
claim below cites the same file:line evidence the audit used, plus a handful of additional call
chains the audit named but didn't trace to their exact break point (marked **New finding** below).
Nothing here is inferred from documentation alone; every "missing" claim was confirmed by reading
the actual code path.

**Scope boundary:** this roadmap starts where the audit's own checklist (§10) left off and covers
only what's needed to take a real MDVR terminal from "registers and reports GPS" (already true) to
the full pipeline in the GOAL diagram: power on → connect → authenticate → send GPS → persist
latest position → update live tracking → generate domain events → trigger notifications → be fully
observable, with no manual intervention. Phase F7 (live-tracking frontend) is done — the audit's
own blocking item #2 is closed as of `9051f11`; this roadmap does not re-litigate it.

---

## How to read each item

Every backlog item states: **(1)** why it's required, **(2)** current status (code-verified),
**(3)** the missing code, **(4)** files/modules touched, **(5)** dependencies, **(6)** risk level,
**(7)** complexity, **(8)** where it sits in the recommended order.

---

## Phase A — Critical (required before first pilot)

### A1. Fix the heartbeat/position `touch()` asymmetry

1. **Why:** A real device sending only `V114` position reports without `V109` heartbeats (a
   plausible firmware configuration — nothing in the vendor docs guarantees both are always sent)
   is never promoted to `ONLINE` and will eventually be swept `session_expired` by the 120s idle
   sweep — **while actively transmitting GPS**. This is a live-data-loss bug, not a cosmetic gap:
   `DeviceOffline` would fire, `devices.last_seen_at` (once A3 lands) would stop updating, and any
   future "bus went offline" alert (Phase B) would false-positive on a bus that is fine.
2. **Current status:** confirmed broken. `services/device-gateway/src/vendors/lsz/handlers/
   heartbeat_handler.py:38` calls `await context.device_sessions.touch(message.device_serial_number)`.
   `services/device-gateway/src/vendors/lsz/handlers/position_handler.py`'s `handle()` (lines
   101–147) only calls `context.device_sessions.resolve(...)` (read-only) — it never calls
   `touch()`. Grepped for any other `touch()` call site in the LSZ vendor package: none.
3. **Missing code:** one call — `await context.device_sessions.touch(message.device_serial_number)`
   — added to `MdvrPositionHandler.handle()`, after the session is resolved successfully (before
   the unauthenticated-drop early return would obviously be wrong; add it in the success branch,
   mirroring the heartbeat handler's unconditional-but-safe-on-unknown-key `touch()` semantics
   already documented in `device_session_manager.py`).
4. **Files:** `services/device-gateway/src/vendors/lsz/handlers/position_handler.py` (the fix);
   `services/device-gateway/tests/` — new/updated unit test asserting `touch()` is called on a
   position report and that a position-only device stays `ONLINE` across a sweep cycle.
5. **Dependencies:** none. Fully self-contained inside the device-gateway deployable.
6. **Risk:** **High** if left unfixed (silent false "offline" on an actively-reporting bus, and
   every downstream connectivity-derived feature in Phase A/B inherits the bug). **Low** to fix.
7. **Complexity:** Trivial (single method call + one regression test).
8. **Recommended order: 1st.** Zero dependencies, smallest possible diff, and it's a pure bug fix
   (not new architecture) — the natural first commit.

---

### A2. Write the `vehicle:{id}:last` Redis snapshot on every accepted position

1. **Why:** This is the audit's #1 blocking item for "GPS shows up live anywhere a human can see
   it." `GET /tracking/vehicles/{id}/latest` (the REST snapshot F7's `LiveTrackingPage` falls back
   to before a WS position arrives) 404s for every vehicle today, forever, regardless of how much
   real GPS data has landed in Postgres — because nothing writes the key it reads.
2. **Current status:** confirmed absent on both sides. `backend/raad/modules/tracking/infra/
   adapters.py`'s `RedisLatestPositionPort` (lines 63–101) implements `get_latest` only — no `set`
   method exists on the port interface (`application/ports.py`) or this adapter. On the
   device-gateway side, `MdvrPositionHandler.handle()` (`position_handler.py:101-147`) constructs a
   `DevicePositionReported` and calls `self._event_publisher.publish(event)` — no Redis `SET`
   anywhere in that method or anywhere else in `services/device-gateway/src/vendors/lsz/`. Grepped
   exhaustively (`vehicle:{id}:last`, `vehicle:.*:last`, `SET.*vehicle`) — zero hits outside
   docstrings describing the gap.
3. **Missing code:**
   - A `Redis` client in the device-gateway's LSZ composition root (`vendors/lsz/server.py`) — one
     already exists for `RedisEventPublisher` (per `docs/architecture/adr/0010-...md`'s shared
     Redis convention); reuse the same client/connection, don't open a second one.
   - A tiny write helper matching `RedisLatestPositionPort`'s own documented payload contract
     (`infra/adapters.py:22-32`): a JSON object keyed `organization_id, vehicle_id, device_id,
     trip_id?, lat, lng, speed_kph, heading_deg, alarm_flags, event_time, is_backfill` — the
     **abbreviated** `lat`/`lng` names, not `latitude`/`longitude` (the adapter's `get_latest`
     parses those exact keys; a mismatch here would make every read silently `KeyError` or return
     `None`-shaped garbage, so this needs a shared/duplicated-and-tested constant, not
     hand-typed dict literals in two places).
   - Called from `MdvrPositionHandler.handle()`, **before** `self._event_publisher.publish(event)`
     — matching JT808 Technical Design §21.2's sequence diagram ordering that `infra/adapters.py`'s
     own docstring already cites (`J->>R: SET vehicle:{id}:last` before `J->>B:
     device.position_reported`), and matching this vendor's own already-established "cache write
     is not this vendor's job to skip just because it's LSZ, not JT808" posture (ADR-0009: only
     the *protocol adapter* differs, not the surrounding architecture).
   - A parallel decision for `RecordBackfillPositionCommand`/backfilled points: per JT808 Technical
     Design (and `.claude/rules/jt808.md` #3), backfilled positions must **not** update the "live"
     snapshot — only non-backfill (`is_backfill=False`) writes should `SET` this key. The LSZ
     vendor doesn't currently produce backfill events at all (confirmed: no `0x0704`-equivalent
     handler exists — §2 of the audit already notes only `V101`/`V109`/`V114` are handled), so this
     is a one-line guard now and a real, load-bearing guard the moment buffered-data support is
     ever added.
4. **Files:** `services/device-gateway/src/vendors/lsz/handlers/position_handler.py` (the write
   call), `services/device-gateway/src/vendors/lsz/server.py` (client wiring, if not already
   reachable from the handler's constructor), a new small module (e.g. `src/redis/latest_position_
   writer.py`) so the payload-shape contract lives in exactly one place and can be unit-tested
   against `tracking/infra/adapters.py`'s parser directly (a cross-deployable contract test, the
   same spirit as `services/device-gateway/scripts/verify_redis_e2e.py`).
5. **Dependencies:** none beyond A1 being harmless to land first; does not depend on A1 but shares
   a file, so sequencing after A1 avoids a merge conflict, not a logical dependency.
6. **Risk:** **High** if skipped — this is the single fact standing between "device sends GPS" and
   "anyone, anywhere, sees a dot on a map via the REST snapshot path" (the WS path also needs this
   independently verified — see A2 note below). **Low** risk to implement; it's an additive write
   next to an already-tested publish call, not a change to existing behavior.
7. **Complexity:** Low-Medium. No new architecture, but the payload-shape contract must be gotten
   byte-exact against a file this deployable cannot import (cross-deployable, Python-only "shared
   contract enforced by tests, not the compiler" — the same category of risk `redis_event_publisher.
   py`'s own docstring already calls out for the events envelope).
8. **Recommended order: 2nd.** Highest-value single item in this roadmap; no architectural
   decisions required, purely additive.

---

### A3. Consume `DeviceOnline`/`DeviceOffline` on the backend; persist `devices.last_seen_at`

1. **Why:** `DeviceOnline`/`DeviceOffline` are already real, published events (confirmed: `services/
   device-gateway/src/vendors/lsz/server.py:114-147` publishes both, with `RedisEventPublisher`
   giving them a fully-specified wire envelope — `event_type="DeviceOnline"/"DeviceOffline"`,
   `aggregate_type="Device"`, `aggregate_id=terminal_id`, payload carrying `device_id`). Nothing on
   the backend listens. `devices.last_seen_at` — a real, already-migrated column
   (`fleet_device/infra/models.py:108`) that `VehicleApplicationService.get_vehicle_by_id`'s
   `tracking_status` DTO already surfaces to the frontend (`fleet_device/application/
   services.py:171`, consumed by `VehiclesPage`'s "Tracking" drawer section per the Device Domain
   Overhaul) — stays `NULL` forever as a result, confirmed by `fleet_device/api/routers.py:31-33`'s
   own docstring. This is the one item that makes "vehicle state synchronization" (the user's own
   Phase A example) real: today `VehiclesPage`'s tracking section is wired end-to-end on the
   frontend and backend query side but has no data feeding it — this item is what lights it up.
2. **Current status:** confirmed unconsumed. `backend/raad/modules/fleet_device/events/
   subscribers.py` exists but is an **empty file** (confirmed via Read — zero bytes). Grepped
   `DeviceOnline|DeviceOffline` across all of `backend/`: the only hit is the docstring in
   `fleet_device/api/routers.py` describing the gap. No `EventProcessor` for either event type is
   registered anywhere in `core/di/bootstrap.py`.
3. **Missing code:**
   - `Device.record_last_seen(self, seen_at: datetime) -> None` on the `Device` aggregate
     (`fleet_device/domain/entities.py`) — a plain state mutation (`self.last_seen_at = seen_at`),
     **no domain event recorded**, per that same file's own module docstring (lines 23-27):
     "`devices.last_seen_at` is a durable mirror of that runtime state... not a domain behavior of
     `Device`" — connectivity state is explicitly modeled as *not* an aggregate-owned business
     fact, so this deliberately breaks from every other mutator on this class (which all record an
     event). Flag this explicitly in the method's own docstring so it isn't "fixed" into
     event-emitting consistency later by someone pattern-matching the surrounding methods.
   - `DeviceApplicationService.record_device_seen(command)` — loads the `Device` via
     `uow.devices.get(DeviceId(...))`, no-ops (logs, doesn't raise) if the device doesn't exist
     (an event for a terminal_id this backend never registered — e.g. a stray/decommissioned
     device still trying to connect — is a real, expected occurrence, not an error), else calls
     `record_last_seen`, commits. **Only `DeviceOnline` and `DeviceOffline` need this** — no
     lifecycle-state change, no `Vehicle` touch.
   - Two new `EventProcessor`s (`DeviceOnlineProcessor`/`DeviceOfflineProcessor`, or one processor
     handling both `event_type`s) in `fleet_device/events/subscribers.py`, resolving `device_id`
     from `event.payload["device_id"]` (present per the publisher's own envelope — falls back to
     resolving by `terminal_id` via a new `ensure`-style repository lookup only if `device_id` is
     ever absent, matching this event's own "optional, still meaningful even incomplete" design
     note in `device_online.py`'s docstring).
   - `register_fleet_device_processors(registry, container)`, wired into `core/di/bootstrap.py`
     the identical way `register_tracking_processors`/`register_notification_processors` already
     are (same `EventProcessorRegistry`, same `notification-worker` consumer group — no new broker
     consumer group needed, mirroring the precedent `tracking`'s own subscriber already set).
4. **Files:** `backend/raad/modules/fleet_device/domain/entities.py` (new method),
   `backend/raad/modules/fleet_device/application/services.py` + `application/commands.py` (new
   command/method), `backend/raad/modules/fleet_device/events/subscribers.py` (new, currently
   empty), `backend/raad/core/di/bootstrap.py` (registration call), `backend/tests/unit/
   test_fleet_device_*` (new), `backend/tests/integration/test_fleet_device_repository.py`
   (extend, or new file) for a live-DB round trip.
5. **Dependencies:** none on A1/A2 — independent event stream. Genuinely parallelizable with A2,
   sequenced after only because A1→A2→A3 keeps device-gateway and backend changes each in their
   own commit rather than interleaved.
6. **Risk:** **Medium.** Nothing breaks if this is skipped (today's silent-NULL is already the
   "safe" failure mode), but every Phase A/B item downstream of "know when a bus's tracker is
   offline" (future offline alerting) depends on this existing first — and it is real, currently
   thrown-away signal that a device-gateway is already producing correctly.
7. **Complexity:** Medium. New aggregate method (small), new application-service method (small),
   new event-processor wiring (small but touches 3 files + DI), full unit + integration test
   coverage per `.claude/rules/testing.md` #3's "safety-critical invariants require explicit
   regression tests" spirit (connectivity state isn't itself D4/CR-1/D5, but it directly feeds a
   pattern those do care about — device trust).
8. **Recommended order: 3rd.**

---

### A4. Resolve the active trip and populate `VehiclePosition.trip_id` at ingestion

1. **Why:** **New finding, not explicit in the audit's own checklist** (the audit's §4 mentions
   `trip_id` is "optional" on GPS fixes but doesn't trace this to its concrete consequence): every
   real LSZ position today publishes with `trip_id=None` — confirmed, `position_handler.py:127`
   hardcodes `trip_id=None` with the docstring "no active-trip Redis read-model exists in this
   deployable." `DevicePositionReportedProcessor` (`tracking/events/subscribers.py:102`) passes
   `payload.get("trip_id")` straight through unchanged. **Practical effect: `GET /tracking/trips/
   {id}/positions` — documented in the audit as "works" — returns an empty page for every trip a
   real device ever drives, forever**, because no `vehicle_positions` row for a real device is ever
   written with a non-null `trip_id`. It "works" only in the sense that the query mechanics are
   correct against manually-seeded test data. This is also a hard prerequisite for A5 (geofence
   evaluation is explicitly trip-scoped per Phase 2 §22.2: "tested against the *upcoming* stops for
   **that trip**").
2. **Current status:** confirmed broken/unbuilt. `transport_ops`'s own `TripRepository` **already
   has exactly the lookup needed**: `active_trip_for_vehicle(vehicle_id) -> Trip | None`
   (`transport_ops/domain/repositories.py:317-322`, "the currently `IN_PROGRESS` trip for a
   vehicle... backs the one-active-trip-per-vehicle guard"). It is currently called only from
   `Trip.schedule`/`Trip.start`'s own one-active-trip invariant check — never from the position
   ingestion path.
3. **Missing code:**
   - A resolution step in `DevicePositionReportedProcessor.process()` (`tracking/events/
     subscribers.py`), calling `TripApplicationService`'s own read path (need to confirm/add a
     thin `get_active_trip_for_vehicle` query method if `TripApplicationService` doesn't already
     expose one at the application layer — the repository method exists, but this processor must
     go through `transport_ops`'s own application service, never its repository directly, per
     `.claude/rules/backend.md` #3's no-cross-module-DB-read rule), then passing the resolved
     `trip_id` into `RecordVehiclePositionCommand`/`RecordBackfillPositionCommand` instead of
     `payload.get("trip_id")` verbatim.
   - A decision on precedence: if the device-plane event itself ever *does* carry a `trip_id` in
     the future (JT808 vendor path, or a later LSZ enhancement), should that value win over the
     freshly-resolved one, or should the backend's own resolution always be authoritative? Flag
     this rather than silently picking — recommend backend-authoritative (the device plane has no
     visibility into `transport_ops`'s trip state at all), but this is a real design call worth one
     line in an ADR or this document's own follow-up, not a silent implementation detail.
   - Cache/perf consideration: this adds one cross-module read per position event (potentially
     high-frequency). `active_trip_for_vehicle` should be checked for an existing index backing it
     (`trips` on `(vehicle_id, status)` or equivalent) before this ships — if absent, add it in the
     same migration.
4. **Files:** `backend/raad/modules/tracking/events/subscribers.py` (the resolution call),
   `backend/raad/modules/transport_ops/application/services.py`/`queries.py` (new query method, if
   missing), `backend/raad/core/di/bootstrap.py` (processor now needs `TripApplicationService`
   resolvable — already bound, just needs threading into the processor's constructor/container
   resolution), a new/updated Alembic migration only if the supporting index is missing (check
   first — do not add speculatively).
5. **Dependencies:** none on A1-A3. Independent of the device-gateway-side work entirely (this is
   backend-only). Is a **hard dependency for A5**.
6. **Risk:** **Medium-High.** Without this, trip position history is silently empty for every real
   device, and geofence evaluation (A5) has no way to know which stops to test against. The failure
   mode is silent (no error, just an empty result set) — exactly the kind of gap this roadmap's
   audit-first approach exists to catch before a pilot, not after a customer asks "why is my trip
   history empty."
7. **Complexity:** Medium. Cross-module application-service call from an event processor (a new
   pattern for this processor, though `policy_guards.py` already establishes the "orchestrate
   multiple modules' application services" precedent elsewhere in the codebase), plus the
   index/perf check.
8. **Recommended order: 4th.**

---

### A5. Wire live geofence evaluation into the position-ingestion path

1. **Why:** This is the audit's single most-cited "fully built, never invoked" finding. Domain
   logic (`GeofenceEvaluationService`, haversine distance + hysteresis primitives), a table
   (`geofence_events`... actually `geofence_crossings`, see below), and 2 of 4 notification
   triggers (`VehicleApproachingStopNotifier`, `VehicleArrivedAtOrganizationNotifier`) already
   exist and are correctly wired — they just never fire, because nothing ever calls
   `TrackingApplicationService.record_geofence_crossing`.
2. **Current status:** confirmed exactly as the audit describes, plus one additional precondition
   the audit didn't fully spell out. `tracking/domain/services.py`'s `GeofenceEvaluationService` is
   pure/stateless (distance, containment, transition-detection only — by design, per its own
   docstring, lines 1-19). `tracking/application/services.py:161-205`'s `record_geofence_crossing`
   **requires a non-null `trip_id`** (`TripId(command.trip_id)`, line 167 — would raise if `None`)
   — so this item is **hard-blocked on A4**. Per Phase 2 §22.2 (`docs/business/
   RAAD_Phase2_Enterprise_Architecture_v1_2.md` lines 969-994), the intended architecture is: live
   position → Geofence Evaluator (Tracking context) ↔ **active-trip geofence state in Redis** ↔
   **route/stop geofence config** → crossing events. Two full pieces of state this needs do not
   exist in code at all today: (a) a per-(trip, stop) "was inside" flag store (Redis, per the
   architecture doc — `GeofenceEvaluationService.detect_transition`'s own docstring: "the caller"
   supplies `was_inside`, meaning something must persist it across calls; nothing does), and (b)
   the debounce/cooldown ("minimum dwell", §22.3) also explicitly deferred to "an application-layer
   concern built on top of `detect_transition`" that was never built.
3. **Missing code:**
   - A per-trip, per-stop hysteresis-state store (Redis, matching the architecture doc's own
     placement) — new key scheme, e.g. `trip:{id}:geofence:{stop_id}` → `{is_inside, last_fired_at}`,
     analogous in spirit to A2's `vehicle:{id}:last` but a new capability, not a reuse of it.
   - An orchestration step (new method on `TrackingApplicationService`, e.g.
     `evaluate_and_record_geofence_crossings`) called from `DevicePositionReportedProcessor` after
     `record_vehicle_position` succeeds, for non-backfill positions only (§22.2: "backfilled points
     are excluded to prevent false historical triggers" — an explicit, already-documented rule this
     implementation must honor).
   - Resolution of "upcoming stops for that trip" — a cross-module read into `transport_ops`'s
     `Route`/`Stop` data via `RouteApplicationService` (never a direct repository reach, same rule
     as A4), keyed off the trip's `route_id`, filtered to stops not yet passed (needs a definition
     of "upcoming" — likely `sequence_no` beyond the last-fired stop, tracked in the same Redis
     state).
   - Geofence radius configuration resolution: `stops.geofence_radius_m` (confirmed to exist —
     `geofence_radius_m` appears in `transport_ops/domain/entities.py`, `infra/models.py`,
     `application/services.py`) or an organization-level default (Phase 2 §22.1) — confirm the org
     default actually exists as a configurable value (`organization`'s `SystemSetting`? — verify,
     don't assume) before wiring the fallback.
   - Cooldown/dwell logic per §22.3, using the same Redis state's `last_fired_at`.
   - Wiring `VehicleEnteredStopGeofence`/`VehicleExitedGeofence` (currently unbuilt) alongside the
     two that already exist (`VehicleApproachingStop`/`VehicleArrivedAtOrganization`) — check
     whether `GeofenceCrossing` domain entity (`tracking/domain/entities.py`) already models all
     four transition types (it appears to, per `application/services.py:170-200`'s four branches:
     `approaching_stop`/`entered_stop`/`arrived_at_organization`/`exited`) — if so this is wiring
     only, not new domain modeling.
4. **Files:** `backend/raad/modules/tracking/application/services.py` (new orchestration method),
   `backend/raad/modules/tracking/infra/adapters.py` or a new adapter (Redis hysteresis-state
   port + implementation), `backend/raad/modules/tracking/events/subscribers.py` (call site),
   `backend/raad/modules/transport_ops/application/services.py` (new "stops for route, ordered"
   query if not already exposed cleanly), `backend/raad/core/di/bootstrap.py` (new port binding),
   extensive new unit + integration tests (hysteresis correctness is exactly the kind of logic that
   silently misbehaves without them — hence `.claude/rules/testing.md` #6).
5. **Dependencies:** **Hard dependency on A4** (needs `trip_id`). Soft dependency on A2/A3 only in
   that they should land first to keep each commit's blast radius small — not a logical
   dependency.
6. **Risk:** **Medium.** Nothing breaks if skipped — `VehicleApproachingStop`/
   `VehicleArrivedAtOrganization` notifications simply stay dormant, exactly as they are today. The
   risk is entirely opportunity cost: this is explicitly a documented, approved, safety-adjacent
   feature (parent notifications) sitting fully-built-but-dead.
7. **Complexity:** **High** — the largest single item in Phase A. New state design (Redis schema
   for hysteresis), new cross-module orchestration, debounce/cooldown correctness, and it must not
   regress `record_vehicle_position`'s own already-tested, already-live-verified path (A2/A4's
   changes sit "next to" existing code; this one wraps around it).
8. **Recommended order: 5th**, and the item most likely to warrant being split into its own
   sub-phase (state design first, evaluation logic second, notification-trigger verification third)
   rather than one commit — flagged here rather than pre-committing to a single-PR shape before
   starting.

---

### A6. Device-plane authentication compensating control

1. **Why:** Today, per the audit (§2, independently re-confirmed by grep against
   `services/device-gateway/src/connection/` and `vendors/lsz/server.py`: no TLS, no IP allow-list
   anywhere), **any TCP client that knows or guesses a valid device serial number can impersonate
   that device with zero further verification** — including publishing fabricated GPS positions
   that would flow, unquestioned, all the way to a parent's live map. `.claude/rules/security.md`
   #9 requires "device auth keys, IP/APN allow-listing where supported, DMZ isolation" as
   compensating controls given JT808/JT1078-family protocols' weak native security; ADR-0009's own
   Consequences section names the same set. None are implemented.
2. **Current status:** confirmed absent, matching the audit exactly (re-verified, not re-derived).
3. **Missing code:** **deliberately not specified yet** — this is the one Phase A item where
   picking an approach is a real architecture/infra decision, not an implementation detail, per
   `.claude/rules/workflow.md` #8 ("never implement business logic without an approved design").
   The candidate mechanisms have materially different trade-offs worth surfacing before choosing:
   - **IP/APN allow-listing** — cheapest to build, but MDVR units typically connect over carrier
     cellular data (dynamic, NAT'd, carrier-pooled IPs), which may make a simple IP allow-list
     operationally unworkable unless the SIM plan is a private APN with stable addressing — a fact
     to confirm with the hardware vendor/carrier contract, not assume.
   - **`auth_key_hash`** — already has a column on `Device` (`fleet_device/domain/entities.py:255`,
     "stored, never verified here — device authentication happens in the JT808 service against the
     device-registry projection") but the LSZ vendor protocol has no documented field to carry a
     pre-shared key/token at all (Hardware Analysis's own finding) — would require either
     smuggling a key into an existing free-text field the vendor protocol does support, or is
     simply not possible without a firmware-level change on hardware already procured.
   - **mTLS** — strongest, but the LSZ protocol is a raw TCP/ASCII-binary stream with no TLS
     framing documented anywhere in `mdvrdocs/`; would likely require a TLS-terminating proxy in
     front of the raw listener, adding real infrastructure, not a code change alone.
   - **DMZ/network isolation** — an infra/deployment decision (firewall rules, VPC placement), not
     application code at all.
4. **Files:** none yet — this needs a scoping conversation (and likely a short ADR, per
   `.claude/rules/documentation.md` #4) before any file changes.
5. **Dependencies:** none technical; depends on an operator/business decision (what does the actual
   SIM/carrier contract for pilot hardware look like?) this document cannot answer from source code
   alone.
6. **Risk:** **High** in the abstract (zero device authentication is a real trust gap for a system
   that ends up on a parent's live map), but the *practical* pilot risk is bounded by physical
   control: a first pilot likely runs on hardware RAAD itself provisions and a small, known set of
   serial numbers — meaningfully lower real-world exploitability than the same gap at scale. Stated
   honestly rather than inflated: this is important to close before broad rollout, arguable whether
   it blocks a small, supervised first pilot.
7. **Complexity:** Unknown until a mechanism is chosen — ranges from Low (a static IP allow-list
   config, if cellular IPs turn out stable enough) to High (a TLS-terminating proxy layer).
8. **Recommended order: 6th, and gated on a decision, not code.** Flagged for the user rather than
   silently picked — see the question this document's cover message will ask.

---

### A7. WebSocket reliability — **verified already implemented, not a build item**

1. **Why (the user's own Phase A example category):** live tracking must survive network blips,
   server restarts, and reconnects without the frontend silently going stale.
2. **Current status: already built and correct**, re-verified directly against source (not assumed
   from CLAUDE.md's own claims): `frontend/src/shared/hooks/useWebSocket.ts` — auto-reconnects on
   any non-auth/policy close code after a 2s delay (`RECONNECT_DELAY_MS`, lines 83-91), deliberately
   does **not** auto-reconnect on `4401`/`4403` (stale-token loops would spin forever, correctly
   avoided), surfaces `status`/`lastCloseCode` so a feature page can show a visible "stale" state
   per `.claude/rules/flutter.md` #6's cross-platform "never fail silently" principle. On the
   backend, `/ws/tracking` re-authorizes on every position send (not just at subscribe time, per
   CLAUDE.md's WebSocket phase section) and the device-gateway's own `DeviceSessionManager` already
   handles "duplicate-terminal supersession" (`session/device_session_manager.py:3,115` — a device
   reconnecting on a new TCP connection correctly supersedes its own stale prior session rather
   than leaving two live sessions for one terminal).
3. **Missing code: none found.**
4. **Files:** none.
5. **Dependencies:** n/a.
6. **Risk:** n/a — already mitigated.
7. **Complexity:** n/a.
8. **Recommended order: not scheduled — no work item.** Included here only so this roadmap doesn't
   silently skip a category the user explicitly asked about; re-verify with a live multi-restart
   test once A1-A3 are deployed together, as a smoke check, not a build task.

---

### A8. Automatic reconnect handling — folded into A7

Same finding as A7 — the user's "WebSocket reliability" and "automatic reconnect handling" examples
turned out, on inspection, to be the same already-built mechanism (`useWebSocketChannel`'s
reconnect timer + backend re-subscribe-on-reconnect design) rather than two distinct gaps. Not
listed as a separate roadmap item to avoid double-counting; see A7's evidence.

---

## Phase A — recommended order summary

| # | Item | Complexity | Risk if skipped | Depends on |
|---|---|---|---|---|
| 1 | Heartbeat/position `touch()` fix | Trivial | High | — |
| 2 | `vehicle:{id}:last` Redis writer | Low-Medium | High | — |
| 3 | Device connectivity consumer (`last_seen_at`) | Medium | Medium | — |
| 4 | Active-trip resolution → `trip_id` | Medium | Medium-High | — |
| 5 | Live geofence evaluation | High | Medium (opportunity cost) | **A4** |
| 6 | Device-plane auth compensating control | Unknown (decision-gated) | High (abstract) / bounded (pilot) | A decision, not code |

Items 1-4 have no dependencies on each other and were only sequenced for clean, reviewable commits
— 2 and 3 could ship in parallel if preferred. 5 cannot start before 4. 6 cannot start before a
scoping decision (see A6 §3).

---

## Phase B — Operational (not started this phase; summarized per the audit's §6/§7)

All five items below share one root cause: **no domain model exists for any of them** (confirmed,
audit §6 table) — this is not "code exists but is disconnected" the way Phase A's items mostly are.

- **Boarding/Alighting** — **Currently blocked by an explicit approved-design decision, not just
  missing code.** Database Design's own `trip_students` "roster snapshot" table (§6.9) was
  deliberately specified with "no boarding fields (D1)". Building this requires reversing or
  amending D1 first — a documentation/ADR change, per `.claude/rules/workflow.md` #8 — not
  something to implement around. Flagged, not started.
- **Overspeed/SOS** — blocked on the alarm-bit ACL mapping (Hardware Analysis §5) from this
  vendor's raw `alarm_flags` integer to the JT/T-808 alarm taxonomy; `_clamp_alarm_flags` in
  `position_handler.py` currently passes `0` ("unmapped," not "no alarms") for anything out of
  range — real per-bit decoding work, needs the vendor's alarm-bit documentation traced precisely
  before any code is written (no inventing a mapping).
- **Ignition** — explicitly excluded from the current position schema; needs a Database
  Design/API Contracts amendment before implementation (schema gap, not a code gap).
- **Driver-targeted / route-event notifications** — no approved Business Requirements/LLD entry
  exists for either; the four wired `EventProcessor`s all resolve *parent* recipients via
  `SubscriptionAccessPolicy` only. Needs design work before implementation, per workflow.md #8.

Not detailed to Phase A's depth here since none of it is scheduled this phase — will be re-audited
with the same file:line rigor immediately before Phase B begins, the same discipline this document
itself follows.

---

## Phase C — Video (not started this phase; summarized per the audit's §5)

`services/jt1078/` is five empty `.gitkeep` files — no runtime decision has been made.
`VideoProviderPort` exists as an abstraction but has zero bound adapters. This is 0% functional
beyond a database row recording that someone asked, and stays fully out of scope until Phase A/B
are closed and a JT1078-equivalent runtime + vendor signaling approach (this vendor's own `C508`
commands, per `.claude/rules/jt1078.md`'s own reality-check note) is decided.

---

## What this document deliberately does not do

Per `.claude/rules/workflow.md` #8 and `.claude/rules/documentation.md` #1, this roadmap does not
invent new architecture to fill any gap it found — every "missing code" section above builds on an
already-approved document (Phase 2 §22 for geofence, JT808 Technical Design §21.2 for the Redis
snapshot contract, Database Design for `last_seen_at`/`geofence_radius_m`) or is explicitly flagged
as blocked on a decision this document cannot make unilaterally (A6's auth mechanism, Phase B's D1
reversal).
