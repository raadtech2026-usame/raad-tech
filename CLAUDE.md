# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Division of labor with `docs/PROJECT_STATUS.md`** (that file's own §14 states this explicitly):
this file is the authority on *why* — architecture, invariants, business rules, permanent
engineering lessons, and pointers to ADRs. `PROJECT_STATUS.md` is the authority on *current state
and what's next* (per-feature ✅/🟡/❌/⏸ status in its §3, the numbered Known Issues in its §10,
sprint-by-sprint history in its §8/§9). Read both before implementing; if they disagree, trust the
running code and fix whichever doc is stale.

## What RAAD Is

RAAD is a cloud-based **School Bus Tracking and Student Transportation Management Platform**.

It exists to solve one problem: giving schools, transport operators, drivers, and parents real-time
visibility and control over school bus operations. Every feature decision should be evaluated against
that single purpose.

## Product Scope

### In scope (this is what RAAD does)

- Real-time GPS tracking of school buses
- Live video streaming from onboard bus cameras (JT1078)
- GPS/vehicle terminal communication (JT808)
- Parent notifications (e.g., bus location, arrival/departure, pickup/drop-off events)
- Fleet management (buses/vehicles as assets)
- Driver management
- Route management
- Student transportation (linking students to routes/buses, boarding/alighting tracking)

### Explicitly out of scope

RAAD is **not** a school ERP. Do not add, extend toward, or casually suggest features from these domains,
even if a request seems adjacent:

- Classroom/school attendance tracking
- General school ERP functionality
- Payroll
- Exams / gradebook / academic records
- Learning Management System (LMS) features

If a request would pull RAAD toward any of the above, say so explicitly and ask for confirmation
rather than implementing it. Scope creep into general school-management territory is the main risk
to design against in this codebase.

## Business Model (Realigned 2026-07-28)

RAAD is a **three-level multi-tenant platform**, in this strict order of authority:

1. **RAAD Platform (Super Admin)** — RAAD's own company dashboard. RAAD manages Organizations,
   Subscriptions/Billing, Devices (hardware onboarding end-to-end), Drivers-as-fleet-assets
   visibility, Live GPS/Video, Fleet Monitoring, Support, and Platform Analytics. **RAAD does not
   manage students or parents directly, and does not run classroom/attendance/ERP functionality**
   — that stays this project's permanent out-of-scope boundary (Product Scope, above).
2. **Organization** — owns all operational data: Vehicles, Drivers, Routes/Stops, Students,
   Parents, Staff Users, Device Assignments. Only reachable after RAAD onboards the Organization
   (below) — an Organization never provisions itself.
3. **Parent / Driver** — mobile-only (`.claude/rules/flutter.md` #1), scoped to exactly one
   Organization, created only by that Organization.

This realignment added five ADR-driven changes on top of the architecture documented below, each
formalized as an ADR before implementation (`.claude/rules/workflow.md` #7/#8). **All five have
now landed** — full verification detail (test counts, live-verification steps, exact bugs found
during implementation) lives in `PROJECT_STATUS.md`, not duplicated here:

- **Organization Onboarding** (`docs/architecture/adr/0017-organization-onboarding-orchestration.md`,
  reusing ADR-0003's provisioning-port pattern, now **Accepted** — previously "Proposed, not
  accepted"): RAAD creates the Organization, selects its Plan, and creates the first Org Admin —
  handing off a username/phone + one-time temporary password — in one orchestrated flow. The same
  provisioning-port pattern also backs Driver registration.
- **Organization-only billing** (`docs/architecture/adr/0016-organization-only-billing-model.md`,
  amending ADR-0006): direct parent billing is removed **outright, not deprecated in place** —
  `SubscriberType.PARENT`, `Organization.billing_model=parent_pays`,
  `RenewParentSubscriptionCommand` are all deleted. RAAD bills Organizations only. Usage-metrics
  tracking (active users, MAU, active devices, active vehicles) ships with **no pricing formula**
  — none is documented anywhere, so only tracking/display exists.
- **Device inventory** (`docs/architecture/adr/0018-device-inventory-and-allocation.md`,
  formalizing the previously-draft-only `docs/architecture/RAAD_DevicePlane_Architecture_v0_1_draft.md`
  §3.5): Supplier → RAAD registers into `device_inventory` (platform-scoped, **no**
  `organization_id`, like `regions`/`plans`) → RAAD allocates to an Organization (creates the
  `devices` row via the existing `Device.register()`, unchanged shape) → the Organization can now
  **read** (never manage) devices allocated to it — a narrow, explicit, flagged reversal of the
  Device Domain Overhaul's original zero-device-visibility posture for `org_admin`, granting only
  `fleet_device.devices.read`, no other `.devices.*` permission.
- **Account-sharing protection** (`docs/architecture/adr/0019-account-sharing-session-cap.md`): a
  concurrent-session cap on `refresh_tokens`, not device attestation — a deliberate lightweight
  tier (no fingerprinting; blocked on the Flutter app existing beyond scaffold). **Implementation:**
  `core.policies.session_limit.SessionLimitPolicy` enforced inside `AuthApplicationService.login`/
  `.refresh` — oldest non-revoked/non-expired `RefreshToken`s are revoked once a per-role cap is
  exceeded; a refresh's own rotated token is deliberately excluded from that count (a 1:1
  replacement, not a net-new session — counting it would make every ordinary refresh spuriously
  evict an unrelated session). The cap lives in **one** `SystemSetting` row (`key="session_cap"`,
  value `{role: max_sessions}` dict) rather than one row per role, because `SystemSettingKey`'s
  26-character max can't fit a per-role key like `session_cap.regional_manager`. Read via a new
  `SessionCapPort` abstraction that `iam` depends on only abstractly, with its concrete adapter
  placed in `core/di/` (the composition root, not `iam` itself) — **this is the reference pattern**
  for any future case of one module reading another module's `SystemSetting` value
  (`.claude/rules/backend.md` #3); confirmed clean against the architecture-gate module-boundary
  test. Self-service `GET`/`DELETE /auth/sessions` returns a **masked** `ip_address`. A "login from
  an unrecognized device" signal is visibility-only (`.claude/rules/security.md` #8, no automated
  block) and is deliberately skipped on a genuinely first-ever login (a flagged interpretive
  choice — the ADR's own "not seen in the last N sessions" leaves N undefined).
- **Platform Analytics dashboard** (`docs/architecture/adr/0020-platform-analytics-read-model.md`):
  a new `platform_audit.PlatformStatsApplicationService` (distinct from
  `PlatformAuditApplicationService`), constructor-injected with `organization`/`iam`/
  `fleet_device`/`billing`'s own application services plus the existing `HealthCheckService` —
  legal per the architecture-gate Rule 1 (application-layer imports only, never `domain`/`infra`).
  Closes the previously-fabricated Online/Offline Devices KPI via a new `devices.is_online`
  boolean, populated by the *existing* `DeviceConnectivityProcessor` extended in place (no new
  event consumer needed). New `admin.platform_stats.read` permission (Founder/Regional
  Manager/Support Staff/Finance Staff) rather than reusing `admin.audit.read`, since
  `finance_staff` doesn't hold that grant. "Live Vehicle Locations" and "Active Drivers" KPIs are
  a flagged scope cut, not silently dropped (no safe cheap Redis aggregate for the former; neither
  module is in the ADR's own decision scope for the latter).

## Core Technical Domains

RAAD's real-time capabilities target two vehicle telematics protocols — these terms recur across
GPS ingestion, video, and device-communication code:

- **JT808** (JT/T 808) — protocol between the bus's onboard terminal and the platform: GPS
  positioning, terminal registration/auth, status, alarms/events, and commands sent to the device.
- **JT1078** (JT/T 1078) — protocol for transmitting live audio/video from onboard cameras to the
  platform over the public network.

Treat both as first-class architectural concerns: most "real-time tracking" and "live video" work
in this codebase is ultimately about correctly implementing, parsing, or relaying JT808/JT1078
traffic. **The procured hardware is now confirmed genuinely JT/T 808-2019 + JT/T 1078-2016
compliant (ADR-0025, 2026-08-10)** — see below for how that reverses the earlier, since-superseded
non-compliance finding, and exactly what still needs implementation work as a result.

**Native protocol compliance confirmed (ADR-0025), superseding the original vendor-protocol
finding (ADR-0009).** ADR-0009 originally found, from `docs/vendor/HARDWARE_ANALYSIS.md` (tracing
only to the vendor's own `mdvrdocs/` documentation available at the time), that the procured MDVR
hardware (Shenzhen Tianyou Security Technology Co., Ltd, brand "LSZ", model `LSZ-C5804DG-Q-F`)
spoke a proprietary ASCII/binary protocol, not JT/T 808/1078 — confirmed at the time against the
codebase's own JT/T 808-2013 parser, which couldn't parse a single frame that hardware sent. Two
new supplier documents received 2026-08-10 (`mdvrdocs/MDVR-808-1078-spec.pdf`, a 70-page
message-by-message JT/T 808-2019 + JT/T 1078-2016 specification, and `mdvrdocs/
LSZ-C5804DG-Q-F_Compliance_Confirmation_RAAD-TECH.pdf`) establish, and the user has confirmed
verification of, genuine compliance for this exact model. **`docs/architecture/adr/
0025-jt808-2019-jt1078-2016-native-protocol-compliance.md` records the reversal and its concrete
consequences** — ADR-0009 itself is not edited (this codebase keeps ADRs as historical records;
ADR-0025 is where a reader following ADR-0009 forward should land for the current finding), and
ADR-0009's *other* decisions (deployable separation, event-only device/business-plane
communication, the Anti-Corruption Layer principle, keeping the dormant JT/T 808 code rather than
deleting it) are unchanged and are exactly what make this reversal cheap to absorb.

**Device gateway rename (ADR-0010) and current adapter roles.** The device-plane deployable was
renamed `services/jt808/` → `services/device-gateway/` and reorganized into `src/vendors/
{jt808,lsz,teltonika,queclink,ruptela}/` behind a common `DeviceProtocolAdapter` interface — a
single multi-vendor entry point for every GPS/MDVR integration, not a JT808-specific service;
`teltonika`/`queclink`/`ruptela` remain structural placeholders only (no hardware procured, no
vendor docs, no code invented ahead of either). ADR-0010 also wires a real Redis-backed event bus
(`RedisEventPublisher`, shared by every vendor adapter) and a broker-driven device registry
projection. **`src/vendors/jt808/` is now the live, primary GPS adapter for this vendor
relationship (ADR-0025 §4)** — it needs the field-width rework named below before a real device
can complete a handshake against it. **`src/vendors/lsz/` (the proprietary-protocol adapter) is
kept, dormant** — the same "kept, untouched, for a possible future case" posture `vendors/jt808/`
itself held before this reversal, not deleted, in case a specific unit or firmware batch ever
turns out to need it after all. The architectural principles (separate plane, event-only
communication with the business plane, same `DevicePositionReported`/`DeviceOnline`/
`DeviceOffline`/`DeviceAlarmRaised` event contract) apply identically regardless of which adapter
is live. `.claude/rules/jt808.md`/`.claude/rules/jt1078.md` no longer carry a "Reality check"
disclaimer (ADR-0025 §6) — they describe the actual, current target again, not a hypothetical
future vendor's.

**JT808 device-plane provisioning/identity gap closed (2026-08-09), now targeting the confirmed
2019 wire shape.** A source-code audit found the JT808 registration/authentication/location
handler stack (`services/device-gateway/src/vendors/jt808/`) was real and tested but permanently
wired to a fail-closed `NullDeviceProvisioningPort`. A new `ProjectionBackedJt808ProvisioningPort`
(mirroring the LSZ adapter's own equivalent pattern) resolves a device's `terminal_id` against the
shared, vendor-agnostic `DeviceRegistryProjection` (already indexed by both `terminal_id` and
`serial_number`, fed by `fleet_device`'s own `DeviceRegistered`/`DeviceActivated`/
`DeviceAssignedToVehicle` events over the broker) — a real, pre-provisioned device (registered →
activated → assigned to a vehicle, the same dashboard flow `RegisterDeviceWizard.tsx` already
provides) is correctly identified and resolved to its `device_id`/`vehicle_id`/`organization_id`
at `0x0100`; unknown/inactive/unassigned/suspended/retired devices all correctly reject
(`TERMINAL_NOT_FOUND`, connection closed — never auto-created, never pending). A new
`HeartbeatHandler` (`0x0002`) and a `touch()` call added to `LocationHandler` (`0x0200`) trigger
`DeviceSessionManager`'s pre-existing `AUTHENTICATED → ONLINE` promotion and `DeviceOnline`/
`DeviceOffline` publishing — both were already fully built, just never triggered before this.
**Field-width rework and `0x0102` auth-code lifecycle implemented (2026-08-11).** The
header/`0x0100`/`0x0102` field-width rework to the confirmed JT/T 808-2019 shape (`BCD[10]`
terminal phone, a protocol-version byte, wider manufacturer-ID/terminal-model/terminal-ID fields,
IMEI + software-version parsing in `0x0102`) is complete — `header.py`/`registration_body.py`/
`authentication_body.py` now parse the real 2019 shape. `0x0200`'s own basic-info layout was
confirmed byte-for-byte identical between the 2013 citation already implemented and the confirmed
2019 supplier spec (a citation-only fix, no parsing-logic change). The prior three-way `0x0102`
auth-code conflict (JT808 Technical Design's device-held-static-secret reading, the primary JT/T
808 spec's platform-issued-code reading, Backend LLD's Redis-rotating-token reading) is resolved
in favor of the platform-issued/echoed-back model per ADR-0025 §3 and now **implemented**:
`ProjectionBackedJt808ProvisioningPort.authorize_registration` mints a random code on `0x0100`
success, hashes it at rest in `Device.auth_key_hash` (an existing column, previously always
`None`) via a new `auth_code_hashing.py` (PBKDF2-HMAC-SHA256), `verify_auth_code` checks it by
hash comparison on `0x0102`; a new `DeviceAuthCodeIssued` event keeps `fleet_device`'s own
`Device.auth_key_hash` column mirrored via a new `DeviceAuthCodeProcessor` subscriber.

**JT/T 1078 video-signaling forwarding + the `services/jt1078/` relay build-out implemented
(2026-08-11), per ADR-0024 §1/§8 and ADR-0025 §5.** `device-gateway`'s `vendors/jt808/` adapter
gained a new `commands/` package: `video_signaling.py` encodes/decodes `0x9101`/`0x9102`/
`0x9105`/`0x9205`/`0x9201`/`0x9202` (downlink, platform → terminal) and `0x1205` (uplink resource-
list report) against the confirmed supplier spec's own §6.2/§6.3 tables — a deliberate refinement
of ADR-0024 §8's literal "backend publishes already-encoded body" wording: the Business API
publishes structured, business-meaningful fields only, and device-gateway itself owns the wire
encoding, keeping every byte of JT/T 808/1078 protocol knowledge inside the device-plane
deployable (the Anti-Corruption-Layer principle ADR-0009 established, unchanged). A new, command-
family-agnostic `PendingCommandTracker`/`CommandSender` give every platform-initiated command real
correlation-ID tracking (`.claude/rules/jt808.md` #6); `TERMINAL_GENERAL_RESPONSE` (`0x0001`) is
now a real `CommandAckHandler` (previously a placeholder). A new `RedisVideoSignalingConsumer`
receives command requests from the broker and forwards them. **A real Business-API-side publisher
of those requests now exists too (2026-08-12)** — see the `VideoProviderPort` paragraph below;
this consumer was built and tested against that publisher's exact wire contract.

`services/jt1078/` is now a real, tested relay, not an empty scaffold — **runtime: Python 3.11+,
asyncio, stdlib + the already-approved `redis>=5.0` only, zero new dependency** (evidence-based:
the direct device-plane sibling of `device-gateway`, same deployment/Redis precedent, and
`device-gateway` itself already proves stdlib-only asyncio can hand-roll a closed wire protocol at
production quality — applied identically here to the JT/T 1078 extended-RTP payload and a minimal
hand-rolled WS-FLV server, RFC 6455, no WebSocket library). Implements: spec-verified extended-RTP
ingest demux + subpackaged-frame reassembly; session lifecycle (create → active → ended/failed,
viewer-count tracking, idle/ingest-timeout sweeps, a device stop-signal reusing the same
`Jt1078SignalCommandRequested` wire contract `device-gateway`'s consumer expects); signed,
single-use, session-scoped viewer tokens (D5 — the relay performs no RBAC of its own, structurally
never reaches a media byte without one); a repackage-only FLV muxer; the WS-FLV viewer delivery
server. Full ingest → repackage → viewer path proven over real loopback sockets with synthetic
frames. **Not built this phase, disclosed not silently assumed:** AVC/HEVC sequence-header
(SPS/PPS) population from a real device's own parameter sets; HLS (live/WS-FLV only this phase).
**Never tested against the physical MDVR** — everything above is verified against the supplier's
own written specification and synthetic byte fixtures only. Docker: new `jt1078-relay.Dockerfile`
+ a `jt1078-relay` service block mirroring `device-gateway`'s exact shape (own container, own
published ports 7910/7911, same Redis instance).

**Business API `VideoProviderPort` → JT1078 relay wiring implemented (2026-08-12).** Closes the
"no Business-API-facing control endpoint" gap the paragraph above originally flagged, connecting
the three previously-independent pieces into one working request path: `VideoApplicationService`
→ `Jt1078RelayAdapter` (`backend/raad/modules/video/infra/adapters.py`, the first real
`VideoProviderPort` implementation) → `Jt1078RelayRpcClient` (`infra/jt1078_relay_client.py`), a
new Redis list-based BLPOP/RPUSH RPC (`raad:jt1078:session_requests` /
`raad:jt1078:session_responses:{request_id}`) → `services/jt1078`'s new `SessionRequestServer`
(allocates ingest coordinates, mints the signed viewer token) → the adapter publishes a
`Jt1078SignalCommandRequested` event on the **existing** `raad:events` broker stream, the exact
wire contract `RedisVideoSignalingConsumer` (above) already expects → the real `0x9101`/`0x9201`
JT808 command reaches the device. **This RPC channel is new and additive, not a replacement for
ADR-0024 §8**: device-gateway ↔ relay coordination stays broker-only, unchanged; the RPC exists
only because the backend ↔ relay session-request/response shape doesn't fit the broker's fan-out
Stream model. `VideoProviderPort.start_live`/`start_playback` were widened to take
`terminal_id`/`channel_no`, resolved once in `routers.py` from `fleet_device`'s own DTOs (no
second, adapter-internal cross-module lookup) — the same deliberate, minimal port-evolution shape
ADR-0022 already established a precedent for. No new route; the existing three `/video/*` routes
are unchanged, and `enforce_d5()` still runs first, before any of this is reached — no media byte
ever transits the FastAPI process, and no new authentication model was introduced.
`Jt1078RelayAdapter` is conditionally bound in `core/di/bootstrap.py` only when both a broker and
`device_plane.jt1078_signaling_url` are configured (a real DI-ordering bug — `VideoApplicationService`
bound before the conditional block, silently resolving `video_provider=None` even with a broker
configured — was found and fixed while wiring this in, mirroring `PlatformStatsApplicationService`'s
own documented precedent for the identical constraint). **Two things flagged, not silently
resolved**: the **relay**, not the backend, mints the viewer token (ADR-0024 §5 point 2 reads
"minted by the backend") — the backend never holds `JT1078_RELAY_VIEWER_TOKEN_SECRET`, so it
structurally cannot mint one itself; the authorization property that section actually protects (no
session decision happens outside the backend's own D5/RBAC check, which runs before the RPC is
ever made) is unchanged. And the relay's own session-lifecycle events are not yet consumed back
into `VideoSession` (`video/events/subscribers.py` is still empty, pre-existing, unchanged by this
phase) — `VideoSession` reaches `ACTIVE` once the RPC + device signal succeed, not on a confirmed
"media is flowing" signal, and ADR-0024 §16's own reconciliation-timeout safety net for a session
stuck in `REQUESTED`/`ACTIVE` does not exist yet. **Never tested against the physical MDVR** —
this wiring is unit/integration-tested against fakes only.

## Domain Vocabulary

- **Fleet** — the set of buses/vehicles operated by a school or transport operator.
- **Route** — a defined path a bus follows, with an ordered set of stops.
- **Driver** — the operator assigned to a bus/route.
- **Student transportation record** — the association between a student and the route/bus they ride.
- **Parent notification** — an alert sent to a parent/guardian about their child's bus (e.g., approaching stop, boarded, dropped off).

## Repository Status

The Business API backend (`backend/`) is a running FastAPI modular monolith with **all ten**
bounded contexts implemented end-to-end (domain → application → infra → API → database
migration), backed by a live PostgreSQL schema. Cross-cutting RBAC (seeded permission matrix),
tenant/region `ScopeResolver`, CR-1/D5 policy enforcement, the `audit_entries` write
architecture, the Redis Streams event broker, both background workers, and three scheduled jobs
are implemented and verified. A real CI/CD gate and contract-test suite exist for all four
deployables (backend, frontend, mobile, device-gateway). **Current per-feature status
(✅ Complete / 🟡 Partial / ❌ Missing / ⏸ Deliberately deferred) lives in `PROJECT_STATUS.md`
§3** — this section covers only the architectural facts, cross-module rules, and non-obvious
invariants a future change must not violate, not a status snapshot that will drift.

### Tech stack (decided)

- **Language/framework:** Python, FastAPI (async, modular monolith — `.claude/rules/architecture.md`).
- **Database:** **PostgreSQL** via the `asyncpg` driver (ADR-0002, superseding an earlier MySQL 8.x
  decision — see `.claude/rules/database.md`). **Redis** backs `tracking`'s read-only
  `RedisLatestPositionPort` and, independently configurable (`RAAD_BROKER__URL`), the event
  broker (ADR-0008: Redis Streams) plus its `LockPort`/`DeadLetterQueue`.
- **ORM/migrations:** SQLAlchemy 2.x async + Alembic, revisions in `backend/migrations/versions/`.
- **Dependency injection:** a small hand-rolled composition root (`backend/raad/core/di/`), not a
  third-party DI framework.
- **Dev tooling** (pytest, ruff/mypy): still **not formally approved** — `backend/pyproject.toml`'s
  own comments track this as an open item. `black` is applied inconsistently across the codebase
  — don't assume every file is currently `black`-clean.

### Completed bounded contexts

Each has the fixed `api/application/domain/infra/events` module shape
(`.claude/rules/backend.md` #1), registered in `core/di/bootstrap.py` and
`interfaces/http/api_v1.py`. The notes below cover durable architectural facts only — what's
deliberately *not* built, cross-module id-handling rules, and non-obvious invariants — not
implementation history (see `PROJECT_STATUS.md` §3 for current per-feature status).

- **IAM** — users, JWT auth, seeded RBAC (`role_permissions`, ADR-0004) — `require_permission`
  resolves for real on every route. `users` starts empty on every fresh deployment, deliberately —
  no migration/seed creates an account, since every documented way to create a `User`
  (`POST /users`) requires an already-authenticated in-scope admin caller. `python -m
  raad.interfaces.cli.bootstrap_founder` is the one-time, operator-invoked bootstrap CLI (never a
  seeded row or an unauthenticated HTTP endpoint) — see `docs/runbooks/founder-bootstrap.md`.
  **ADR-0023** adds `GET /me`/`/me/students`/`/me/driver-profile` — see "Canonical `/me`" below.
- **Organization** — organizations, regions, tenant hierarchy, `region_assignments`/
  `support_assignments` backing a real `ScopeResolver` (ADR-0005).
- **Fleet Device** — vehicles, devices, cameras, device↔vehicle assignment lifecycle. RAAD owns
  and manages all GPS/MDVR hardware; schools never register, configure, or view device internals.
  `org_admin` holds **zero** `fleet_device.devices.*` permissions except the single ADR-0018
  `.read` grant below — `fleet_device.vehicles.*` stays fully granted, since vehicles are
  legitimately school fleet data. `devices` carries `imei`/`iccid`/`serial_number` (nullable,
  globally unique like `terminal_id`) for hardware-intake theft/fraud/RMA workflows.
  `VehicleApplicationService.get_vehicle_by_id` embeds only `tracking_status.last_seen_at` —
  deliberately no derived `is_connected` boolean, since no source in this module can answer
  "online right now" honestly — this is the *only* device-derived data an Org Admin session can
  ever reach; `list_vehicles` leaves it `null` to avoid an N+1 lookup per page. **ADR-0018**
  added `device_inventory` — a platform-scoped, pre-tenant pool with deliberately **no**
  `organization_id` column, "like `regions`/`plans`" — via a `DeviceInventoryItem` aggregate
  (`manufactured/in_stock/allocated/scrapped`). Two RAAD-only routes: `POST /device-inventory`
  (receive stock) and `POST /device-inventory/{id}/allocate` (allocates to an Organization,
  creating the `devices` row via the existing `Device.register()` in the same transaction,
  linked back by `devices.inventory_id`). **No `GET /device-inventory` list/detail route
  exists** — ADR-0018 documents only the two `POST` routes (routes are contract-driven here, not
  capability-driven) — a flagged real usability gap, not silently invented around. Allocation
  reuses the inventory item's own `serial_number` as the new device's `terminal_id` (confirmed
  with the user: LSZ has no real JT808 `terminal_id` concept; `serial_number` is already its wire
  identity — grounded in ADR-0009/0010/0015). `device_status_log` (Database Design §7.3) remains
  documented-but-not-built.
- **Tracking** — vehicle positions, geofence crossings. `RedisLatestPositionPort` is read-only;
  the JT808 Technical Design names the device-plane service itself, not this backend, as the
  writer of `vehicle:{id}:last` — `TrackingApplicationService.record_vehicle_position` persists
  history only, never also writes Redis. Both routes enforce `TrackingVisibilityPolicy`
  (`.claude/rules/security.md` #4's four-dimension predicate) via
  `interfaces/http/policy_guards.resolve_tracking_decision` — ADR-0006 resolves the D4-vs-CR-1
  conflict (safety-over-billing wins for genuinely live position during an active trip; trip
  history stays fully CR-1-gated).
- **Transport Operations** — `Student`, `Parent`, `student_parents` M:N link, `Driver`,
  `Route`+`Stop` child entity, `Trip`, and `StudentAssignment` ("the CR-1 access gate"). Only
  `trip_students` (the roster snapshot, Database Design §6.9) remains unbuilt — its data source,
  `student_assignments`, only recently landed, so `Trip` ships as vehicle+driver+route only, no
  student roster. The `/drivers` REST resource has no documented row in API Contracts §4.3 — built
  anyway on Database Design §6.1/ADR-0001's table ownership, the same uniform-CRUD precedent
  `student_parents` established. `Route.remove_stop`/`move_stop` and `Trip.interrupt`/`resume` are
  implemented and unit-tested but have no approved HTTP route this phase — the same
  "use-case-exists-no-endpoint-yet" posture `fleet_device`'s `RegisterCameraCommand` established.
  **`Trip.vehicle_id`/`StudentAssignment.vehicle_id` are opaque, format-validated-only
  cross-module ids with no existence check** — `transport_ops` cannot perform a cross-module DB
  read (`.claude/rules/backend.md` #3), and ADR-0003 (the only cross-module coordination design in
  this codebase) covers a write workflow, not read/validation; this mirrors the existing
  `Parent.user_id`/`Driver.user_id` precedent. **Known, unresolved event-catalog collision:**
  `StudentAssignment`'s four revocation events (`StudentAssignmentRemoved`/`StudentTransferred`/
  `StudentGraduated`/`StudentDisabled`) share three exact `event_type` strings with `Student`'s
  own status-change events — distinguishable only by `aggregate_type`, never disambiguated in the
  LLD's event catalog.
- **Billing (C8)** — `Plan`, `Subscription`, `Invoice`, `Payment` (no `retry()` — a retry is a
  brand-new `Payment.initiate(...)` with a fresh idempotency key), `TransportFee` (no HTTP route,
  no documented API surface). `Plan`/`Subscription` have no documented write routes at all.
  **Permanent gotcha:** `payments.idempotency_key` is `CHAR(64)` per the schema authority, and
  PostgreSQL blank-pads `CHAR(n)` storage on `SELECT` (unlike `VARCHAR`) — `infra/mappers.py`'s
  `model_to_payment` strips the padding before it reaches the domain layer; any future `CHAR(n)`
  column needs the identical treatment. A declined payment marks `Payment` `failed` and leaves the
  invoice unchanged (a resolved documentation conflict: `invoices.status` has no `failed` value in
  Database Design §8.3, despite Phase-2's narrative saying to mark the invoice failed). **Superseded
  by ADR-0022** — see "Payment Provider Architecture" below for the current design. ADR-0016
  removed the parent-billing path outright — see Business Model above.
- **Notifications (C7)** — `Notification` (create/mark_read, the in-app store) and `DeviceToken`
  (FCM registration). **`GET /notifications`/`GET /notifications/{id}` are scoped by personal
  ownership** (`recipient_user_id = principal.user_id`), **not tenant** — the first endpoints in
  this codebase scoped that way; a non-owner request 404s, never 403s, generalizing Backend LLD
  §14.3's "404-over-403 avoids confirming existence of out-of-scope data" from cross-tenant to
  cross-user. `notification_preferences` (Database Design §7.7) is unbuilt — no document gives it
  a route. **Real, unresolved event-contract conflict:** API Contracts §13.2 documents a single
  `student.assignment_changed` wire event with a `new_status` payload field; the actually-shipped
  `transport_ops` events are the four separate ones above, with no `new_status` field and no
  translation layer anywhere in this codebase. `notifications.data_json` established this
  codebase's first `JSONB` column (ADR-0002).
- **Reporting (C9)** — `ReportRun` (request/start/succeed/fail) is the only aggregate built.
  **Real, unresolved documentation gap:** `ReportDefinition` (Phase 2 §2/§10.1's conceptual
  pairing with `ReportRun`) has no table anywhere in Database Design (the schema authority) and no
  API route manages one. `ReportType` is therefore an opaque, non-empty, length-validated string
  (`report_runs.definition_key`), not a closed enum — no document gives exact wire-format values.
  No list route is documented, so none exists. Actual report rendering (PDF/Excel) is out of
  scope — `ReportRendererPort` is unbound (see Known gaps below).
- **Video (C6)** — `VideoSession` (`request_live`/`request_playback`/`activate`/`end`/`fail`) is
  the only aggregate built — `playback_requests` is read as descriptive elaboration of
  `window_start`/`window_end`, not a second aggregate. **Native JT1078 is explicitly not
  implemented** — built around an unbound `VideoProviderPort` abstraction (MVP: a hardware/vendor
  video API). All three routes call `interfaces/http/policy_guards.enforce_d5`
  (`.claude/rules/jt1078.md` #1: "Parents have zero reachable path to video, anywhere, ever")
  before any application-service call, resolving `organization_id` via `fleet_device` (no
  cross-module DB read). `video_sessions` carries no `stream_url`/token column — that stays
  Redis-owned by the (not-yet-built) JT1078 service; a bound provider's return value is surfaced
  only in the API response, never persisted.
- **Platform & Audit (C10)** — `AuditEntry` (`GET /admin/audit`, read-only) and `SystemSetting`
  (`GET`/`PATCH /admin/settings`) are built; `Integration` (Database Design §8.9) is not — no
  document gives it any lifecycle verbs or route. **`AuditEntry` is never created through this
  module** (ADR-0007): `audit_entries` is a shared-kernel table, written transactionally by every
  *other* module's own `UnitOfWork.commit()` via `core.audit.writer.AuditWriter`. `platform_audit`
  is purely the read side.

### Architecture patterns in use

All ten completed contexts apply the same patterns identically, enforced by an automated
`tests/architecture/` gate suite (ten tests: domain purity, layer dependency direction, module
boundaries, API-layer boundaries), not just asserted:

- **Clean Architecture / layered dependency direction:** `api → application → domain`; `infra`
  implements interfaces `domain` defines; domain never imports FastAPI or SQLAlchemy
  (`.claude/rules/backend.md` #2).
- **DDD:** aggregates with buffered domain events (`_AggregateRoot._record()` /
  `pull_domain_events()`, deliberately duplicated per module rather than shared), value objects,
  domain-owned invariants.
- **Repository pattern:** one `SqlAlchemy<Entity>Repository` per aggregate, composing
  `core.db.repository.SqlAlchemyRepositoryBase`; every repository keeps an in-memory identity map
  so in-place aggregate mutations get re-projected onto their ORM row via
  `flush_tracked_changes()` immediately before commit.
- **Unit of Work:** `core.db.unit_of_work.SqlAlchemyUnitOfWork`, extended per module to bundle
  that module's repositories onto one transaction boundary; `commit()` always flushes tracked
  changes, then delegates to the base class's outbox-write-then-session-commit.
- **Domain events + transactional outbox + transactional audit trail:** every state change
  buffers `DomainEvent`s on the aggregate; `commit()` writes them to the `outbox` table **and**
  the `audit_entries` table, in the *same* transaction as the business rows
  (`core/events/outbox.py`, `core/audit/writer.py` — ADR-0007) — no event without a committed
  change, no committed change silently missing its event or audit row. The outbox's publish/relay
  side is bound whenever a broker is configured (ADR-0008); `audit_entries`' read side
  (`GET /admin/audit`) has no such dependency and is fully live regardless.
- **Dependency injection:** one composition root, `core/di/bootstrap.py`; unbound dependencies
  fail loudly (`LookupError`/`NotImplementedError`) rather than resolving to a fake.
- **RBAC + tenant/region scope + domain policies (ADR-0004/0005/0006):** `require_permission` and
  `get_scope`/`ScopeResolver` both resolve for real on every route in every module.
  `interfaces/http/policy_guards.py` (outside any single module, since it orchestrates multiple
  modules' application services) is the CR-1/D5 enforcement point — `TrackingVisibilityPolicy` on
  both `tracking` routes, `VideoAccessPolicy` on all three `video` routes.

### Project structure (current)

```
backend/
├── raad/
│   ├── main.py            # ASGI app factory / composition root wiring
│   ├── core/               # cross-cutting kernel: config, security, tenancy, db, events, audit,
│   │                       # errors, logging, di, ids, time, workers
│   ├── modules/             # one package per bounded context, each:
│   │   └── <context>/
│   │       ├── domain/      # entities, value objects, domain events, repository interfaces
│   │       ├── application/ # commands, queries, DTOs, application services, ports
│   │       ├── infra/        # SQLAlchemy models, mappers, concrete repositories, UnitOfWork
│   │       ├── api/          # FastAPI routers, request/response schemas, DI deps
│   │       └── events/       # publishers/subscribers
│   └── interfaces/http/     # api_v1 router aggregation, shared deps, middleware, error handlers
├── migrations/               # Alembic env.py + versions/
└── tests/                    # unit/, integration/ (live-DB round trips), contract/, architecture/
```

### Migration status

- **Engine:** PostgreSQL (ADR-0002). Single linear Alembic chain, no branches, in build order:
  `iam → organization → fleet_device → tracking → transport_ops (student → parent →
  student_parents → driver → route → trip → student_assignment) → billing → notifications →
  reporting → iam (role_permissions, ADR-0004) → organization (region/support_assignments,
  ADR-0005) → video → core (audit_entries, ADR-0007) → platform_audit (system_settings)` (head,
  plus the RBAC-grant/payment/session-cap/analytics/`/me` migrations layered on since — see each
  ADR for its own revision).
- **Verified zero drift:** `alembic check` reports clean against the live schema; the full chain
  round-trips (`upgrade → downgrade → upgrade`) with no orphaned objects. **Permanent rule:**
  every migration introducing a PostgreSQL native `ENUM` type must include an explicit
  `DROP TYPE` in `downgrade()` — `alembic revision --autogenerate` never emits this itself, and
  omitting it breaks re-upgrade after a downgrade.
- `migrations/env.py` imports `infra/models` from all ten modules plus `core.audit.writer` — keep
  this in sync 1:1 with which modules/shared-kernel packages have a model-bearing source file.

### Known gaps (tracked, not hidden)

Full history of every closed phase (Final Backend Completion, Pagination/Filtering/Sorting,
WebSocket, Tenant Isolation Security Audit, and others) lives in `PROJECT_STATUS.md` §9. What
remains here is what's still genuinely open, plus two flagged, unresolved documentation
conflicts (do not silently pick a side on either):

- **`PaymentProviderPort` is resolved (ADR-0022, Stripe)** — see "Payment Provider Architecture"
  below. `VideoProviderPort`/`ReportRendererPort` remain unbound — no vendor/hardware video
  adapter and no report-rendering engine exist yet, both "fail loudly, don't fake it." Load
  tests (`docs/business/...Phase2...` §13.1 NFR targets) are not yet written —
  `testing/load/` is scaffolding only.
- **`ReportDefinition`** (Reporting, above) has no schema-authority table — will need an approved
  documentation update before report content generation can be meaningfully implemented.
- **The `student.assignment_changed`-vs-four-separate-events conflict** (Notifications, above) —
  will need an approved documentation update, not code-level invention, before the Notification
  Worker's event-contract handling can be reconciled with API Contracts §13.2.
- RBAC (`role_permissions`) and `ScopeResolver` grants are editable only via Founder-only routes
  (`POST /roles/{role}/permissions`(`/revoke`), `POST /scope-assignments/regions`/`/support`
  (`/revoke`)) — reachable at the application layer only before this, the same
  "use-case-exists-no-endpoint-yet" posture as `Route.remove_stop`/`Trip.interrupt`.
- **Event broker: Redis Streams (ADR-0008)**, bound whenever `RAAD_BROKER__URL` is configured.
  Notification Worker and Report Worker are both built (`interfaces/workers/`); three scheduled
  jobs run under `RedisLockPort` (`prune_vehicle_positions`, `sweep_expired_subscriptions`,
  `reconcile_expired_payments`). **Trip generation is deliberately not registered** — no document
  gives a schedule/recurrence data model to generate a `Trip` from.

## Permanent Engineering Lessons

Bugs found during implementation that represent a durable rule for future code, not just history
— apply these proactively rather than rediscovering them:

- **Tenant scope is enforced centrally, at the repository layer (ADR-0021) — this is the
  mandatory pattern for any new tenant-owned resource.** `SqlAlchemyRepositoryBase` takes the
  caller's `TenantRegionScope` at construction and applies it inside `get_by_id`/`list_page`/
  `list_all`/`list_cursor_page` via `_apply_scope` (`scope_by_own_id=True` only for
  `Organization`, the one aggregate that *is* the tenant root). **Never rely on a call site
  remembering to filter by `organization_id`** (`.claude/rules/backend.md` #4) — a live-reproduced
  vulnerability (a brand-new Org Admin's `GET /vehicles` returning other organizations' vehicles)
  found this exact mistake repeated across every module before the fix. Out-of-scope
  single-resource access 404s, never 403s. Any creation command that accepts a client-supplied
  `organization_id` needs an explicit `_enforce_own_organization`-style check too — the repository
  fix alone doesn't close a write-side IDOR on a command with no cross-aggregate reference to
  transitively validate against.
- **Aggregate-less domain events must pass `aggregate_id=None`, never a composite string.** A
  composite id like `f"{role}:{permission}"` reliably exceeds `outbox.aggregate_id`'s `CHAR(26)`
  and raises `StringDataRightTruncationError` in production despite passing every fake-backed
  unit test (a fake repository can't catch a real column-width constraint). `RolePermission`/
  `ScopeAssignment`-style "pure grant/revoke reference data" aggregates have no real minted ULID
  identity to begin with — `DomainEvent.aggregate_id` is `str | None` specifically to allow this.
- **Any datetime read back from Postgres and later compared against `Clock.now()` (tz-aware) must
  go through this codebase's existing `_aware_utc`/`_naive` helpers on *every* datetime field on
  that mapper, not just the one that first crashed.** `model_to_user` originally missed this on
  three of four datetime fields even after the crash on the fourth was fixed and understood.
- **Any *optional* hardening layer bound to Redis (rate limiting, caching) must fail open on
  `RedisError`** — logged once, never cascade-failing the endpoint it protects. Proven necessary
  when a configured-but-unreachable Redis took down `/auth/login` entirely until the middleware
  was fixed to distinguish "unbound" from "bound but down."
- **The broker and the cache share one `maxmemory` budget in this MVP topology, so
  `maxmemory-policy` is `noeviction`, never `allkeys-lru`.** An unconsumed outbox Stream entry is
  a lost domain event forever, not reconstructable state (unlike the cache side — latest
  position, geofence state, rate-limit counters), so silent eviction under memory pressure is
  never acceptable while broker and cache share one Redis instance. Splitting them onto separate
  processes so the cache side could safely use `allkeys-lru` is a documented future step, not
  attempted (`.claude/rules/architecture.md` #7: no premature microservices).
- **Any `CHAR(n)` column needs its padding stripped on read**, the same way `model_to_payment`
  strips `payments.idempotency_key`'s blank-padding — PostgreSQL pads `CHAR(n)` on `SELECT`
  (unlike `VARCHAR`), and the domain layer must never see the padding artifact.
- **Changing `--requirepass` on the shared Redis service requires updating its healthcheck in the
  same change.** A plain `redis-cli ping` healthcheck starts failing with `NOAUTH` the instant a
  password is added, marking every container in the stack "unhealthy" — the fix needs
  `CMD-SHELL` (not `CMD`, which never expands shell variables) plus `redis-cli -a
  "$REDIS_PASSWORD" --no-auth-warning ping`.
- **Prometheus counters must be labeled by the matched route *template*, never the raw request
  path** — labeling by raw path creates one time-series per resource ID (unbounded cardinality).
  `RequestLoggingMiddleware` reads `request.scope["route"].path` (populated by Starlette's own
  routing by the time `call_next` returns), falling back to the raw path only for a genuine 404.
- **Never log a database/cache connection string with its credential in plaintext** — redact
  `user:PASS@` down to `user:***@` on every log line, including inside operational shell scripts
  (`scripts/db/backup.sh`/`restore.sh` both originally logged the real password until this was
  caught during live verification).
- **A vendor-supplied field must be clamped/validated at the adapter boundary before it reaches
  domain logic that assumes it's already in range.** The LSZ vendor adapter
  (`services/device-gateway/src/vendors/lsz/handlers/position_handler.py`) was passing
  out-of-range `heading_deg`/`alarm_flags` straight through, silently failing *every* real
  position event (both of the vendor's own documented worked examples triggered it) until this
  was caught by live verification, not by any unit test.
- **Every hand-rolled `async def run_forever(self): while True: await self.poll_once()` consumer
  loop must catch and log per-iteration exceptions, never let one propagate out of the loop.**
  Found live (2026-08-19, ADR-0030 end-to-end verification against the physical bench unit): a
  single `redis.exceptions.BusyLoadingError` (Redis reloading its dataset — but any transient
  Redis error has the identical effect) on `services/jt1078/src/session/session_request_server.
  SessionRequestServer.run_forever`'s very first iteration silently killed that `asyncio.Task`
  for the rest of the process's life — nothing ever awaits or logs a fire-and-forget task's
  result until shutdown, so 22+ real, live session-creation requests piled up completely
  unprocessed with zero error output until the process was later stopped and `stop()`'s own
  `await self._session_request_task` finally surfaced the buried exception. The exact same
  unprotected pattern existed in two more places — `services/device-gateway/src/registry/
  redis_device_registry_consumer.RedisDeviceRegistryConsumer.run_forever` and
  `.../vendors/jt808/commands/redis_video_signaling_consumer.RedisVideoSignalingConsumer.
  run_forever` — fixed identically, all three now `catch Exception, log, `asyncio.sleep(1)`,
  continue`, matching the resilience this codebase's own `backend/raad/core/workers/base.py
  Worker._tick` already established as the correct shape for a supervised polling loop.
- **A Redis-backed in-memory projection needs an explicit, consumer-group-independent replay on
  cold start — an incremental consumer group alone is not enough.** Found in the same live
  session: `device-gateway`'s `DeviceRegistryProjection` is a plain in-memory `dict`, nothing
  about it survives a process restart, but the Redis consumer *group* reading it into existence
  (`device-gateway-registry`) is itself durable Redis state — its delivery cursor persists across
  restarts. A restarted process therefore combined an empty projection with an already-caught-up
  group, and `xreadgroup(..., {stream: ">"})` returned nothing, ever, for any device registered
  before the restart (`terminal_not_found` on a real, previously-working JT/T 808 registration).
  Fixed by `RedisDeviceRegistryConsumer.replay_from_start` — a one-time raw `XRANGE` (not
  `XREADGROUP`, so it never touches the group's own cursor) that rebuilds the full projection
  before any vendor adapter starts accepting connections (`gateway.DeviceGateway.start`),
  leaving the incremental consumer-group loop to handle only what's genuinely new afterward.
- **A BCD-encoded identity field re-derived in two different wire protocols is not guaranteed to
  be the same width.** JT/T 808-2019's own terminal-phone `terminal_id` is `BCD[10]` (20 hex
  digits, ADR-0025 §2); JT/T 1078's own extended-RTP ingest frame carries the *same* underlying
  SIM/phone-number identity as its own, narrower `BCD[6]` (12 hex digits) "SIM card number"
  field — the same value, right-justified/zero-padded into the wider field, not two different
  identities. `services/jt1078/src/session/session_manager.SessionManager.
  resolve_ingest_by_terminal_id` compared the two with plain `==` and could therefore never
  match a real device's ingest connection to its own session — confirmed live: the device
  correctly dialed the relay's ingest port and streamed valid frames, every one rejected as
  `unsolicited_ingest_connection_rejected` regardless of correctness. Fixed by matching on the
  narrower field's own trailing-suffix length (`_terminal_id_matches_sim_card_number`), not
  exact equality. **Any future cross-protocol identity comparison between this vendor's
  JT/T 808 and JT/T 1078 fields must check each spec table's own stated byte width first, never
  assume two identity-shaped fields are directly comparable.**
- **`docker-compose.yml` must wire every config value an adapter's own `from_env()` reads — an
  unset one degrading to a silently-wrong default is worse than a missing one that fails loudly.**
  `services/jt1078/src/config.RelayConfig.effective_public_ingest_host` falls back to
  `ingest_host`'s own default, `0.0.0.0` — a *bind* address, structurally never a valid
  destination — when `JT1078_RELAY_PUBLIC_INGEST_HOST` is unset. Live-verified: the device
  acknowledged every `0x9101`/`0x9201` (a wire-valid command), because `0.0.0.0` is syntactically
  a fine IP for that field: only the device's own subsequent, silent inability to dial it exposed
  the gap, and the JT808 side of the exchange gave no indication anything was wrong. Now wired in
  `docker-compose.yml`, documented in `docker/.env.example` with no safe universal default (the
  reachable address depends on network topology this file cannot know), and set to a real value
  in this environment's own `docker/.env`.

## Frontend Implementation Status

The React web dashboard (`frontend/`) follows `docs/architecture/frontend-flutter-master-roadmap.md`
(phases F0–F13 for React, M0–M5 for Flutter). Design source: `docs/architecture/RAAD Console
(Standalone).html` (the approved interactive mockup) and `docs/architecture/logo-raad.png`
(shield + location pin, brand blue `#1E63FF` / brand green `#2FBF4F`). The mockup was **extracted
into a design system, not converted 1:1** — three flagged departures: (1) ad-hoc pixel values
rationalized into one scale (`styles/tokens.css`); (2) the smallest label text raised to an 11px
legibility floor; (3) several interactive elements with no real accessibility semantics (a
non-interactive settings toggle `<div>`, a drawer with no dialog role/Escape handling) rebuilt
with real ARIA/keyboard support. `Skeleton`/`EmptyState` components exist because every
real network-backed view needs both — the mockup itself depicts neither.

**Two-dashboard architecture, not one app with a role switcher** (the mockup's "tap role to
switch view" was a demo convenience only — a `Principal` has exactly one role per session):

- **Platform Dashboard** (`/platform/*`) — Founder, Regional Manager, Support Staff, Finance
  Staff. Manages the whole platform, including tenant provisioning (`/platform/organizations`).
- **Organization Dashboard** (`/org/*`) — Org Admin only, scoped server-side to their own
  organization; no "Organizations" nav item.
- Driver/Parent have **no web dashboard** — both are mobile-only (`.claude/rules/flutter.md` #1);
  `MobileOnlyPage` shows a clear redirect message if either reaches the web login.

This mapping lives in `shared/auth/dashboard.ts`; per-role nav trees in `app/layout/navConfig.ts`.
**Live Video is absent from every platform role's nav**, not just hidden from Parents — a
deliberate reading of `.claude/rules/api.md` #2 ("Org-Admin only," not "Org-Admin plus RAAD
staff"). Finance Staff's nav is pruned to Dashboard/Organizations/Billing/Reports
(`.claude/rules/security.md` #3's "billing scope only") — presentation only
(`.claude/rules/frontend.md` #2); the backend's RBAC matrix remains the real gate regardless.

**Phase F0** (design tokens, component library, app shell, routing, `PlaceholderPage` for every
unbuilt route) is complete. New deps this phase: `lucide-react` (the mockup's icon set is Lucide's
exact names), `@fontsource/manrope`/`sora`/`jetbrains-mono` (self-hosted, replacing the mockup's
Google Fonts CDN calls), `@tanstack/react-table` (headless table logic; sorting/pagination stay
server-driven per API Contracts §7/§8), `clsx`. **The dashboard home page shows no fabricated
KPI numbers** — no aggregate summary endpoint existed at the time, and fabricating numbers would
break this project's "fail loudly, don't fake it" posture (closed later by ADR-0020, above).

**Phases F1–F5 and the Device Domain Overhaul are complete** (Organizations/Regions, Users,
Vehicles/Devices, Students/Parents/linking, Drivers/Routes/Stops) — each entity gets one shared
component pair reused across both `/platform/*` and `/org/*` where both dashboards need it.
`/org/devices` was **removed entirely**, matching the backend's `org_admin`-holds-zero-device-
permissions posture — `VehiclesPage`'s own "Tracking" drawer section (`last_seen_at` only) is the
only device-derived data an Org Admin session can reach.

**Phase F6 — Trips & StudentAssignment** is complete. **A real backend whitelist gap was found
while building this, not silently worked around:** `Driver`/`Route` repositories (`transport_ops`)
whitelist only `status` as a filter — no `organization_id` — while `Vehicle` (`fleet_device`)
does whitelist it. `ScheduleTripForm`'s vehicle picker is therefore organization-scoped for real;
its driver/route pickers are deliberately global, with a hint that a cross-organization pick will
be rejected server-side (the backend's own `DomainError`, surfaced verbatim, is the real safety
net — never a client-side filter that can't be built honestly). **`StudentAssignment` — "the CR-1
access gate" — deliberately has no dedicated nav page**, matching the approved mockup: built as a
second section on `StudentsPage`'s own detail drawer, a flagged, narrow exception to
`.claude/rules/frontend.md` #1's "no cross-folder `api.ts` import" discipline (a component import,
not a duplicated data read). Shows only the current active assignment, not a history list — the
response carries no `assignedAt`/`endedAt` to order past rows by.

**Map provider: Mapbox GL JS (ADR-0011, user-confirmed)**, behind a pluggable
`shared/map/MapProvider.ts` interface (`.claude/rules/frontend.md` #6 requires this). New deps:
`mapbox-gl`/`@types/mapbox-gl`. `tracking`'s existing REST/WebSocket contracts already expose
plain decimal-degree `lat`/`lng` — no backend change was needed.

**Phase F7 — Live Monitoring & Maps** is complete, but deliberately the "per-vehicle detail view"
half of live tracking, **not** an always-every-vehicle fleet map — `/ws/tracking` supports exactly
one active vehicle subscription per connection (a documented backend simplification), so the page
is a vehicle picker plus one live map. No ETA anywhere (no backend capability exists). Explicitly
out of scope: simultaneous multi-vehicle live markers, and trip position history/playback
(`GET /tracking/trips/{id}/positions`, a distinct scrubber feature).

**Phase F8 — Notifications** is complete. `GET /notifications` is scoped by personal ownership,
not tenant (see Notifications, above) — there is no "every notification in this organization"
admin view. First cursor-paginated page in this frontend (`useInfiniteQuery`, matching the
backend's cursor-only contract — no client-chosen sort). Live-updated over `/ws/notifications` by
**refetching**, not merging WS fields into the cache, since the push frame deliberately carries no
`status`/`read_at`/`data`. `AppShell`'s topbar bell badge goes live for the first time
(`useUnreadCount`, capped at the most recent 50 notifications — a disclosed real limitation, not a
fabricated total).

**Phase F9 — Billing** is complete, **read-only by design** — no `Plan`/`Subscription`/`Invoice`
write route exists this phase, confirmed before writing any UI. **`POST /billing/payments` has no
client function at all** (`features/billing/api.ts`'s own documented decision) — with no
`PaymentProviderPort` bound at the time, every click would both show a broken action *and* leave a
real, permanently-`PENDING` database row behind; this extends the "fail loudly, don't fake it"
posture from *data* to *affordances* (don't offer a control guaranteed to fail). Superseded at
`/org/billing` specifically by ADR-0022 below; `/platform/billing` is unchanged. First tabbed page
in this frontend (`shared/components/Tabs/`, distinct from `FilterChips`). A confirmed RBAC gap
shapes the tab switcher: Regional Manager/Support Staff hold `billing.plans.list` alone, not
`.subscriptions.list`/`.invoices.list` — the tab switcher is omitted for that pair, mirroring the
Founder Dashboard's "omit what would 403" precedent.

**Development Redis environment (ADR-0008/ADR-0010 made runnable):** `docker/docker-compose.yml`'s
`redis` service is real now (`redis:7-alpine`, AOF, healthcheck); the Business API broker and the
Device Gateway's event bus share one local Redis instance by convention
(`redis://localhost:6379/0`). Live verification of this environment found and fixed a real bug —
see the LSZ clamping lesson in Permanent Engineering Lessons above.

**Device onboarding readiness audit** (`docs/architecture/device-onboarding-readiness-audit.md`,
run before F7): confirmed registration and GPS→Postgres ingestion genuinely work end to end;
found gaps outside F7's own scope — no writer anywhere for the Redis `vehicle:{id}:last` key
(neither this backend nor the device-gateway — since resolved for the online/offline half by
ADR-0020's `devices.is_online`, the position-cache half remains open), the geofence pipeline fully
coded but never invoked from the live position-ingestion path, and no boarding/alighting/
overspeed/SOS/ignition implementation anywhere. None of these gate F7 itself.

## Production Readiness Hardening (Priority 1)

A read-only production-readiness audit (`PROJECT_STATUS.md` §9) found nine concrete gaps between
this repository and a real VPS deployment — `PROJECT_STATUS.md` §5's Priority 1 list. Items 1–4
were worked strictly one at a time (architecture review → implementation → tests → live
verification → docs → `PROJECT_STATUS.md` update); Items 5–9 were directed to run back to back
without per-item approval, per explicit user instruction, still each getting its own review/
tests/verification/docs. **All nine are now complete, live-verified, or correctly
audited-and-left-unbuilt pending an external dependency** — full verification detail (exact test
counts, live-verification transcripts, bug-hunt narratives) lives in `PROJECT_STATUS.md` §5/§15,
not duplicated here. What follows is only what a future change must know:

1. **Backups** — a `backup` Compose service runs `pg_dump --format=custom` on a schedule (chosen
   specifically because it enables `pg_restore --clean --if-exists`, which a plain-SQL dump
   can't). `restore.sh` requires an explicit `--target-url` and `--confirm` — never an implicit
   "current database" — so a mistyped invocation can't silently wipe the wrong one. Off-site copy
   via `rclone` is a deliberately pluggable, **not-yet-configured** hook (`BACKUP_RCLONE_REMOTE`
   unset — no cloud storage account provisioned; `PROJECT_STATUS.md` Known Issue #12). The live
   drill (seed → backup → restore into a throwaway DB → assert round-trip) is CI-enforced
   (`testing/backups/test_backup_restore.sh`). Runbook: `docs/runbooks/backup-and-restore.md`.
2. **TLS/HTTPS** — mechanism complete, **not yet live-tested against a real domain** (no Docker
   daemon in this sandbox). Two-phase bootstrap avoids the chicken-and-egg cert problem:
   `prod.conf` (plain HTTP + ACME webroot, the safe always-bootable default) → get a certificate →
   flip to `prod-tls.conf`. `${DOMAIN_NAME}` substitution uses nginx's own official templating
   mount, not a custom render step. `certbot` reloads nginx via shared PID namespace
   (`pid: "service:nginx"`), deliberately not a Docker-socket mount (which would grant
   effectively-root host access for the same outcome). Runbook:
   `docs/runbooks/tls-setup.md` (first live test is a Let's Encrypt **staging** request, so no
   rate-limit consequence on the first real exercise).
3. **Auth rate limiting + account lockout** — account lockout lives on the `User` aggregate
   (`record_failed_login`/`is_locked`, default 5 attempts / 15 minutes, both configurable) and is
   identity-based (locks the account regardless of source IP); rate limiting is IP-based (Redis
   `INCR`+`EXPIRE` fixed window, `LoginRateLimiter`, scoped only to `POST /auth/login` — not a
   general per-route framework). Live-verified end to end against real HTTP/Postgres.
   Rate-limiting's own counting logic is unit-tested only against a fake Redis — no reachable
   Redis in this sandbox (`PROJECT_STATUS.md` Known Issue #14).
4. **Redis production hardening** — mechanism complete, **not yet live-tested against a running
   Redis process**. `--requirepass` now required (`REDIS_PASSWORD`); broker and cache split onto
   separate logical Redis DBs (0 cache / 1 broker) sharing one `maxmemory` budget under
   `noeviction` (see Permanent Engineering Lessons above for why). New `RedisConnectionSettings`
   makes connect/socket timeouts and health-check interval explicit for both clients (previously
   relying on undocumented library defaults). Runbook: `docs/runbooks/redis-operations.md`.
5. **Real health checks + minimum monitoring** — `/health/ready` now runs real, timeout-bounded
   checks (Postgres `SELECT 1` mandatory; each Redis client's `PING` only gating if actually
   configured). New hand-rolled `/metrics` (no new dependency — the actual need doesn't justify a
   full Prometheus client library), labeled by route *template* (see Permanent Engineering Lessons
   above). Grafana/Sentry/OpenTelemetry deliberately not built — each needs a real external
   account/target this session cannot obtain or fabricate meaningfully
   (`docs/runbooks/monitoring.md`).
6. **RBAC grant/revoke routes** — Founder-only routes now expose the previously
   application-layer-only `PermissionApplicationService`/`ScopeAssignmentApplicationService`. See
   the `aggregate_id=None` lesson in Permanent Engineering Lessons above — the bug this item found
   and fixed.
7. **Deployment & rollback runbooks** — `docs/runbooks/vps-deployment.md` (provisioning, firewall,
   Docker, `.env` walkthrough) and `docs/runbooks/rollback.md` (application-code rollback vs.
   migration rollback — the latter names ADR-0016's billing cutover as this codebase's own real
   precedent for a genuinely destructive migration, not a blanket "every migration is safely
   reversible" claim). Necessarily unverified against a real running VPS.
8. **Payment provider integration** — audited, genuinely blocked on two external dependencies at
   the time (no real EVC Plus merchant account/API docs; no documented webhook signature scheme
   or a `Principal` shape for a non-human caller). **A real, still-unresolved documentation
   conflict, flagged not resolved:** Phase 2 §20 describes a **Parent-Pays** EVC Plus workflow
   that ADR-0016 (Organization-only billing) removed outright — no later document redesigns the
   *payment* workflow for the model that replaced it. **Superseded for Stripe specifically by
   ADR-0022** below; EVC Plus/Zaad remain unresolved per this same conflict.
9. **Mobile App MVP** — built directly against the approved
   `docs/architecture/frontend-flutter-master-roadmap.md` §5 (M0–M5). M0 (Foundation) and M2
   (Driver) are code-complete. **M3 (Parent) was partially blocked** on a real backend gap found
   while wiring it: `GET /parents/{parent_id}/students` has no ownership check on the
   path-supplied `parent_id` — since closed by ADR-0023's `/me` endpoints below, though the mobile
   client itself is not yet rewired to them (a follow-up, not done in that pass). M4 (FCM push)
   and M5 (offline resilience + store release) were not attempted — both need real external
   accounts (Firebase; Play Store/App Store Connect). **The one categorical, disclosed limitation
   for this entire item:** no Flutter/Dart SDK exists in this sandbox — every Dart file written is
   "written and carefully reviewed, not yet verified" (parsed/compiled/run) until a real `flutter
   analyze`/`flutter test`/`flutter run` actually succeeds against it, unlike every other Priority
   1 item, which retained some independent verification path despite an incomplete environment.

## Payment Provider Architecture + Organization Billing (ADR-0022, 2026-08-06)

Direct continuation of the program above, at explicit user directive: Organization Billing needed
a real, self-scoped UI, and "no placeholder payment functionality should ship... leaving only real
provider credentials... to be added after VPS deployment," targeting **Hostinger VPS via
Coolify**. Full design record: `docs/architecture/adr/0022-payment-provider-architecture.md`.
Four genuinely blocking design forks were resolved via `AskUserQuestion` before implementing (all
"(Recommended)" options accepted): (1) **Stripe** gets a real, verified adapter now; EVC
Plus/Zaad stay interface-complete stubs (no real merchant docs exist for either, and Phase 2
§20's own EVC Plus workflow describes the Parent-Pays flow ADR-0016 removed — flagged, not
silently picked around, same as Priority 1 Item 8 above). (2) Secrets are environment variables,
composition-root only (`core/di/bootstrap.py`) — **never** `SystemSetting`, since `org_admin`
holds `admin.settings.read`/`.update` too, which would let any Org Admin read/tamper with a
platform-wide secret. (3) The webhook authenticates via a per-provider HMAC signature (Stripe's
own `Stripe-Signature` scheme) over a shared secret — no `Principal`/RBAC involved at all;
`SYSTEM_PRINCIPAL` (now a shared constant in `core/tenancy/principal.py`) represents the caller
for the audit trail only. (4) Coolify owns reverse-proxy/TLS for its own deployment path — this
stack's own `nginx`/`certbot` stay the alternative generic-VPS path, never both running together.

**`PaymentProviderPort` redesign.** Three findings from reading the actual code first: the
previous port was shaped entirely around mobile money, with no way to carry a client-tokenized
card `payment_method_id`; `Payment.mark_paid`/`mark_failed` had no same-state idempotency guard
(a real bug — every provider retries a webhook until it gets a `200`, and a duplicate "paid"
callback would have re-run `subscription.renew(...)` a second time, double-advancing the billing
period — fixed at both the entity level and a service-level short-circuit, with a regression test
proving a replayed callback doesn't move `current_period_end` twice); `infra/adapters.py` was
empty. Now three methods (`charge`, `verify_webhook_signature`, `parse_webhook_event`).
`StripePaymentAdapter` (new `httpx` dependency, chosen over the official `stripe` SDK — matching
this codebase's "hand-roll a narrow need" pattern) calls the real Payment Intents API
(`confirm=true`, no 3D Secure/SCA flow — a deliberate v1 scope cut) and implements Stripe's
documented HMAC-SHA256 webhook scheme, verified against self-constructed test vectors (no live
Stripe account exists in this environment). `EvcPlusPaymentAdapter`/`ZaadPaymentAdapter`
implement the full interface but raise a clear "no merchant API documentation exists" error.

**Webhook route, wired for real.** `POST /billing/payments/callback` has **no**
`Depends(require_permission(...))` — the HMAC signature check *is* this route's authentication; a
missing/invalid signature is a `401`, logged (no `audit_entries` row — no aggregate mutation
happens for a rejected request). New `GET /billing/payments` (payment history — no list route
existed for `Payment` before) behind a new `billing.payments.list` permission. **Permanent
lesson:** a route with no `Depends(require_permission(...))` can still transitively need a
`Principal` through its UoW dependency — `get_billing_uow_unscoped` (mirroring `iam.api.deps.
get_iam_uow`'s `login`/`refresh` precedent) was needed because `get_billing_uow` otherwise
resolves scope from an authenticated caller that doesn't exist for a signed webhook.

**Frontend — `OrgBillingPage` + a real "Pay Invoice" flow.** `/org/billing` is a dedicated,
`principal.organizationId`-scoped page; `/platform/billing` (the shared, cross-organization
`BillingPage`) is untouched. `InvoicesSection` mounts only once a subscription id is known,
since `GET /billing/invoices` is not tenant-scoped server-side (a real, pre-existing gap) — an
unfiltered call at mount time would leak every organization's invoices for a moment. New
`shared/components/ConfirmDialog/` — this frontend's first genuinely consequential/hard-to-reverse
action (charging a real card) gets a real confirm step, distinct from every prior mutation's
"loading button + toast" convention. Stripe Elements (`@stripe/stripe-js` +
`@stripe/react-stripe-js`, new dependencies, required for PCI-compliant client-side tokenization —
the raw card number never reaches this backend) mounts inside it, gated by a
`getBillingProviderConfig()` read against the existing `GET /admin/settings`.

**Deployment — a Coolify overlay, alongside the existing generic-VPS path.** Coolify already runs
its own Traefik reverse proxy with automatic TLS, so this stack's `nginx`/`certbot` must not also
run. `nginx`/`certbot` are gated behind a new `gateway` Compose profile, defaulted **on** via
`docker/.env.example` so every existing dev/generic-VPS command is unaffected — Coolify simply
never activates it. Runbook: `docs/runbooks/coolify-deployment.md` (mechanism-verified only, not
live-tested against a running Coolify instance).

**What remains, genuinely external:** a real Stripe (or EVC Plus/Zaad, once real merchant
documentation exists) merchant account's live credentials, and a real Hostinger VPS + Coolify
instance.

## Canonical `/me` Self-Service Identity Resolution (ADR-0023, 2026-08-07)

At explicit user direction, closes `PROJECT_STATUS.md` Known Issue #17 (discovered while building
the Mobile App MVP): neither `parent` nor `driver` had any safe way to resolve its own domain
identity (`Parent.id`/`Driver.id`) from an authenticated `Principal`, and
`GET /parents/{parent_id}/students` took `parent_id` straight from the URL path with **no
ownership check** comparing it to the caller's own linked `Parent.user_id` — a real cross-parent
privacy leak in waiting. Per `.claude/rules/workflow.md` #8,
`docs/architecture/adr/0023-canonical-me-identity-resolution.md` was written and accepted before
any implementation.

**One canonical capability.** `GET /me` resolves the caller's own cross-module identity in one
place (`user_id`/`role`/`organization_id`, plus `parent_id`/`driver_id` only when the role
matches and a linked row resolves); `GET /me/students` and `GET /me/driver-profile` are thin views
built on that same resolution. Org Admin (and every RAAD-staff role) needs no separate lookup —
`organization_id` is already on `Principal` directly.

**Ownership: `iam`, composing `transport_ops`'s application services** — the same legal
cross-module shape ADR-0020's `PlatformStatsApplicationService` established (application-layer
only, confirmed against the architecture-gate module-boundary test). `iam` was chosen as the
owning module because it already owns `Principal`/`User`/`GET /auth/me` — the natural home for
"who am I, across the whole platform." New mirror methods, each already precedented 1:1 by an
existing sibling: `DriverRepository.get_by_user_id`/`DriverApplicationService.
get_driver_by_user_id` (mirroring `Parent`'s existing equivalent, added during Backend
Stabilization for CR-1 enforcement).

**No client-supplied `parent_id`/`driver_id` — structural, not a runtime check.** Every method
`MeApplicationService` exposes takes only a `Principal` as its identity input; the route
signatures have no `parent_id`/`driver_id` parameter to accept, so there is nothing for a caller
to override — this directly closes the IDOR class Known Issue #17 described, by construction, not
by adding a check that could later be forgotten on a new route. The pre-existing
`GET /parents/{parent_id}/students` (still Org-Admin-reachable) was **not** fixed by this ADR —
explicitly out of scope, a materially different risk since it's usable only by roles that can
already see any organization's data by design.

**Authorization: self-scoping, not RBAC** — matching `GET /auth/me`'s existing posture. `/me`
routes are gated by `Depends(get_current_user)` alone, no `require_permission`, safe specifically
because every response derives from `principal.user_id` alone. **Zero RBAC migration, zero schema
migration.** 404-over-403 when no linked domain record resolves (`/me/students`/
`/me/driver-profile`); `/me` itself never 404s.

**One real, previously unflagged RBAC finding, recorded not silently corrected:**
`transport_ops.student_parents.list` is not actually Org-Admin-only, as earlier documentation
claimed — `founder`/`regional_manager`/`support_staff` also hold it (a later RBAC migration
revoked `.students.*`/`.parents.*` from RAAD-staff roles but never touched
`.student_parents.list`). `parent`/`driver` still hold neither, so this ADR introduces no new
exposure either way.

**What remains:** wiring the mobile app's Parent/Driver screens to these endpoints — no Flutter
SDK in this environment to verify any such change against, the same disclosed limitation Priority
1 Item 9 above carries.

## CI Hardening — Frontend + Device Gateway CI (2026-08-07)

`PROJECT_STATUS.md` §14's own process (re-verify the repo, read this file, continue only the next
approved roadmap item) led here after every Priority 1 item was complete or externally blocked:
the next actionable Priority 2 backlog item was CI hardening (the other five Priority 2 items are
each blocked on an unresolved architecture/documentation gap, a new-dependency decision needing
`.claude/rules/workflow.md` #1/#2's explicit go-ahead, or a real external account — recorded as
such in `PROJECT_STATUS.md` §5, not silently skipped).

New `frontend-pipeline.yml` and `device-gateway-pipeline.yml` (`.github/workflows/`), mirroring
`backend-pipeline.yml`'s exact scope discipline — build/install → test only, **no lint/
security-scan gate**, since `eslint` has no config anywhere in `frontend/` yet and `ruff`/`mypy`
remain formally unapproved (`backend/pyproject.toml`'s own tracked-as-open comment) — and using
only already-approved tooling (`npm`/Vitest; stdlib `unittest` + the already-approved `redis>=5.0`).
**Zero new dependencies, zero new external accounts.** `jt808-pipeline.yml`'s filename is
deliberately left as-is, not renamed — the original JT/T 808 code still lives on, dormant, inside
`services/device-gateway/src/vendors/jt808/` (ADR-0009/0010). Not live-tested against a real
GitHub Actions run — no way to trigger one in this sandbox, the same disclosed posture every other
workflow file in this repository already carries.

## Parent Video Access Authorization (ADR-0026, 2026-08-12)

At explicit user direction: organizations must be able to grant individual, named parents live
and/or playback video access — off by default for every parent, server-enforced, never a
client-side toggle. This is a formal, narrow revisit of D5 ("Parents have zero reachable path to
video, anywhere, ever"), not a weakening of it — and not a new requirement invented from
nothing: `docs/business/Project_Brief_v1.md` §4.8 always said Parents may "View live video (if
enabled by the organization)," and `docs/architecture/frontend-flutter-master-roadmap.md` §2.5
point 2 had already found this conflict during frontend planning and deliberately deferred it,
naming its own resolution condition verbatim: *"a 'business requirement changes' trigger only if
you want to actually revisit D5 itself."* This ADR is that trigger.
`docs/architecture/adr/0026-parent-video-access-authorization.md` has the full design; this
section records what changed and why, per this file's own division of labor with
`PROJECT_STATUS.md`.

**Two independent booleans on `Parent`, not a new permission system.** `has_video_live_access`/
`has_video_playback_access` (`.claude/rules/naming.md`'s `is_`/`has_` boolean convention; the
user's own "video_live_access"/"video_playback_access" vocabulary is the prose/permission name)
live directly on the `transport_ops.Parent` aggregate, off by default, mutated only by four new
idempotent domain methods (`grant_video_live_access`/`revoke_video_live_access`/`grant_video_
playback_access`/`revoke_video_playback_access`) — mirroring `Parent.activate`/`disable`'s exact
shape, the same "boolean capability flag on the owning aggregate" pattern `StudentParent.
is_primary`/`devices.is_online` already established. RBAC (`role_permissions`) grants
per-*role*, not per-instance, so a per-parent flag has no home there without inventing a parallel
system — this was investigated and ruled out before touching schema, per the user's own explicit
instruction. Migration `1470274175d8` (additive, `server_default=false`), live-Postgres
round-tripped in this session.

**Grant/revoke: a dedicated, more restrictive endpoint, not folded into ordinary profile edits.**
`PATCH /parents/{id}/video-access` (org_admin + founder only, a **new**
`transport_ops.parents.grant_video_access` permission — deliberately distinct from
`.parents.update`, since granting access to a child's live video feed is materially more
sensitive than editing a phone number, `.claude/rules/security.md` #1).

**The authorization chain, exactly as specified, entirely server-side**:
`Parent (Principal) → D5 role gate (VideoAccessPolicy, now includes Role.PARENT narrowly) → self
identity (_resolve_parent_id, reused) → explicit permission (matching purpose — live/playback
independently, one flag never satisfies the other) → child/device ownership (new
find_owned_student_id_for_device: device_id → its active vehicle assignment → the existing CR-1
find_owned_student_id_for_vehicle, unmodified) → only then VideoSession/VideoProviderPort.`
`interfaces/http/policy_guards.resolve_d5_decision`/`enforce_d5` were widened to take
`device_id`/`purpose`; all three `/video/*` routes updated. **A parent owning nothing at all
raises `NotFoundError` (404), never `403`** — this codebase's established cross-tenant-probing-
avoidance convention (`resolve_cr1_decision`'s own precedent), extended to video; only an
owning-but-ungranted parent gets `403 VideoForbiddenError`. RBAC additionally grants Parent the
same three `video.*` permissions Org Admin already holds — layer-2 "may attempt," not "may
succeed," the identical split CR-1 already established for `tracking.vehicles.read_latest`.
`GET /me` (ADR-0023) now surfaces both flags for client-side UI gating — presentation only,
never a second authorization system (`.claude/rules/frontend.md` #2).

**Relay-lifecycle reconciliation, concurrency ceilings, and real SPS/PPS/AVCC — the remaining
software-only JT1078 gaps this same session's own prior report had flagged, closed together.**
`VideoApplicationService`'s eager, optimistic `session.activate()` (fired synchronously right
after the provider RPC returned, before the relay had any real signal media was flowing) is
removed; a new `video/events/subscribers.py` (previously empty) consumes the relay's own
already-published `VideoSessionActivated`/`Ended`/`Failed` events and drives real `activate`/
`end`/`fail` transitions, mirroring `fleet_device`'s own `DeviceConnectivityProcessor` shape
exactly. `services/jt1078`'s `SessionManager` gained configurable global (default 50, citing
Phase 2 §13.1's own "e.g., start 50 global") and per-organization concurrency ceilings, raising
`SessionCapacityExceededError` before any allocation. `flv_muxer.py` gained real SPS/PPS
extraction and `AVCDecoderConfigurationRecord` construction (ISO/IEC 14496-15), closing the seam
`build_avc_sequence_header_tag` previously left unpopulated. `audit_entries` needed no new code
at all — every `VideoSession` transition and every parent video-access grant/revoke already
flows through the existing `UnitOfWork.commit()` → `AuditWriter` pipeline (ADR-0007); the
reconciliation fix above was the only real gap, now live-Postgres-verified with two dedicated
tests.

**One prior-ADR amendment, in place, same session — mirroring ADR-0025's own precedent for
revising a document once it's actually implemented.** ADR-0024 §5 point 2 read "a signed viewer
token minted by the *backend*"; the shipped design has the **relay** mint it (the backend never
holds `JT1078_RELAY_VIEWER_TOKEN_SECRET`, so it structurally cannot). Corrected in ADR-0024 itself
rather than left as a silent contradiction — the security property that section actually
protects (no session decision happens outside the backend's own D5/RBAC/permission check, which
always runs first) is unchanged.

**Mobile player: Flutter only, confirmed via `AskUserQuestion`, not assumed.** The web dashboard
has no Parent login at all — a web-only player would be permanently unreachable by any parent —
so `.claude/rules/flutter.md` #3 ("no live video anywhere in the mobile app") is narrowly
amended for Parent only; Driver's own exclusion is unaffected, and `.claude/rules/frontend.md` #4
(web dashboard, Org-Admin-only) is untouched. New mobile dependency `media_kit`/`media_kit_video`/
`media_kit_libs_video` (MIT license) for FLV decode/render, also confirmed via
`AskUserQuestion` before adding (`.claude/rules/workflow.md` #1) — the relay's bespoke WS-FLV
binary-frame protocol is bridged to an ordinary `http://127.0.0.1` URL via a new `FlvRelayBridge`
(the already-approved `web_socket_channel` in, `dart:io.HttpServer` out, no new dependency for
the bridge itself). Carries the identical "written, not compiled or run" limitation every prior
mobile phase already discloses — no Flutter SDK in this sandbox.

**What remains, disclosed not silently dropped:** HLS; ADR-0024 §16's own defensive
reconciliation-timeout job (for the case where *no* relay lifecycle event ever arrives at all,
e.g. a relay crash); the Org-Admin web video player (F10 — the user's own explicit
Flutter-only choice this phase); a real Flutter SDK and a physical MDVR to verify any of this
against, backend through mobile.

**Note on ADR-0027/0028/0029 (2026-08-16) and F10:** the paragraph above's "F10 — Flutter-only
choice this phase" was accurate when ADR-0026 was written, but ADR-0028 (Unified Vehicle
Operations Frontend) later built the Org-Admin **web** video player after all, alongside ADR-0027
(a `GET /vehicles/{vehicle_id}/device-assignment` read model + `Device.is_online`) and ADR-0029
(extending Platform Admin — Founder/Regional Manager/Support Staff — the same live-video access).
All three are `Accepted`/implemented (commits `560580d`/`8b5bd0c`/`857d68b`) but this file's own
narrative was never updated to reflect them — see `docs/PROJECT_STATUS.md` §4's own flagged note
next to those three ADR rows, and each ADR's own file, for the authoritative detail; not
duplicated here to avoid a second copy that can drift.

## Automatic Camera/Channel Discovery (ADR-0030, 2026-08-18)

A read-only bench-test diagnostic against the physical `LSZ-C5804DG-Q-F` unit found JT808
registration/heartbeat/GPS fully working but zero `Camera` rows: `RegisterCameraCommand` existed
at the application layer with no HTTP route, and no event subscriber turned a device-reported
channel list into a `Camera` row. The user explicitly declined a one-off manual fix for the test
device and asked for the generic product workflow — any JT/T808/1078-compliant MDVR added through
**Add Device** should have its cameras discovered and registered automatically, no database/shell
intervention ever. Per `.claude/rules/workflow.md` #8,
`docs/architecture/adr/0030-automatic-camera-channel-discovery.md` was written and accepted before
implementation.

**A real correction found while investigating:** the message pair that actually reports channel
*count/capability* is `0x9003`/`0x1003` ("Query/Upload Terminal A/V Attributes",
`mdvrdocs/MDVR-808-1078-spec.pdf` §6.1.1/§6.1.2) — not `0x9205`/`0x1205`
(`commands/video_signaling.py`'s `QueryResourceList`/`ResourceListReport`), which the code's own
existing comment already correctly scoped as the terminal's own **recording** resource list
(browsing recorded files), not physical channel capability. `0x9003`/`0x1003` was net-new protocol
code (`services/device-gateway/src/vendors/jt808/commands/av_attributes.py`,
`handlers/av_attributes_handler.py`), reusing the *existing* `Jt1078SignalCommandRequested` broker
wire contract verbatim (one new entry in `redis_video_signaling_consumer.py`'s `_BUILDERS` table —
no new consumer, no new event type on the request side).

**Discovery trigger: once per device, on first successful authentication** — a new, purely
additive `devices.av_attributes_requested_at` column (migration `7d3a9c1e5b42`) is the idempotency
guard `DeviceApplicationService.record_device_seen` sets (widened to return `str | None`: the
device's own `terminal_id` exactly when this `DeviceOnline` transition should trigger discovery,
`None` otherwise) and `fleet_device.events.subscribers.DeviceConnectivityProcessor` checks before
publishing the `0x9003` request — a later reconnect never re-triggers it. **Channel-to-position
mapping deliberately defaults to `position=other`/`label="Channel N"`, never guessed semantics** —
the vendor spec's own channel-numbering convention (Table 5.31) is not hardcoded as a
platform-wide mapping, since RAAD cannot confirm it holds for every future JT/T1078-compliant
vendor (ADR-0010's multi-vendor premise); an Org Admin can rename/reposition a discovered camera
once a camera-editing surface exists (none does yet — a disclosed, pre-existing gap this ADR does
not close). A new `DeviceAvAttributesReportedProcessor` (`fleet_device/events/subscribers.py`)
consumes the resulting `DeviceAvAttributesReported` event and calls the existing, previously-
unreachable `DeviceApplicationService.register_camera` once per channel `1..max_video_channels` —
idempotent by construction via `register_camera`'s own `ux_cameras__device_channel` invariant
(`ConflictError` on replay, caught and logged, not treated as an error).

**Two real gaps found and fixed while verifying this work, not by the original implementation
pass — the same "a fake can't catch a real wiring gap" lesson this file's Permanent Engineering
Lessons section already names for the LSZ adapter's field clamping.** (1) The new
`DeviceAvAttributesReported` event was never added to device-gateway's
`events/publisher_port.DeviceEvent` union, `LoggingEventPublisher`, or
`events/redis_event_publisher._fields_for` — with the real `RedisEventPublisher` this raised
`TypeError` on every `0x1003` reply (the final `raise TypeError("Unrecognized device-plane event
type...")` fallthrough), and with the default `LoggingEventPublisher` the event silently vanished
with no log line; both handler unit tests used a recording fake publisher, so `pytest` never
caught either failure mode. Fixed by adding the missing branch to all three. (2)
`backend/tests/unit/test_fleet_device_application.py::RecordDeviceSeenTests::
test_updates_last_seen_at_and_commits` still asserted the pre-ADR-0030 always-`None` return value
against the now-widened `str | None` signature — fixed, plus a new regression test proving a
second `DeviceOnline` for the same device does not re-trigger discovery. Verified after both
fixes: device-gateway's full suite (419 tests, including the new `test_av_attributes*`/
`test_pending_commands`/`test_redis_video_signaling_consumer` cases, 24 of them) and backend
`tests/unit` + `tests/architecture` (1427 tests + 10 subtests) all pass; `tests/integration` (278
tests + 21 subtests) passes with migration `7d3a9c1e5b42` applied and an upgrade→downgrade→upgrade
round trip clean (`alembic check`: zero drift) — the only integration failures are two pre-existing
Redis-timeout tests unrelated to this change (no reachable Redis broker in this sandbox).
`tests/contract`'s pre-existing `NoSilentUndocumentedRoutesTests` failure (routes from ADR-0017
through ADR-0023 never added to that suite's own documented-routes accounting) is untouched — this
ADR adds no new HTTP route — and is flagged, not fixed, here.

**What this ADR does not do**, per its own text: build a camera-editing UI/API; route the JT1078
relay through nginx/Coolify; touch any other JT/T808/1078 message; change how
`POST /video/live`/`/playback` resolve a camera (already generic via `device.cameras`); or start
`services/jt1078` by default in every environment (it already has no Compose `profile` gate).
