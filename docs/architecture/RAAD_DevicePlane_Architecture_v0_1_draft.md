# RAAD Platform — Device Plane Architecture (Consolidated Blueprint)

**Status:** DRAFT v0.1 — PROPOSED, not yet formally adopted.
**Prepared by:** Principal Software Architect (design documentation only; no implementation code).
**Traceability:** Phase-2 Enterprise Architecture (§4, §5, §11.3, §12.7, §19, §21, §22), Phase-3.4 JT808
Technical Design, Phase-3.5 JT1078 Technical Design, Database Design §5/§7, Backend LLD §10,
API Contracts §13, `.claude/rules/jt808.md`, `.claude/rules/jt1078.md`, `.claude/rules/architecture.md`,
`.claude/rules/security.md`, locked decisions **D1–D6**, **CR-1**.

> **How to read this document.** Approved designs for the device plane already exist (Phase 3.4,
> Phase 3.5, Phase 2 §19/§21/§22, Database Design §5). This document does **not** redesign them —
> it consolidates them into one blueprint, extends into areas the approved set does not cover, and
> flags every point of conflict. Every section is marked with one of:
>
> - **[APPROVED]** — restates an already-approved design; the cited document is the source of truth.
> - **[PROPOSED]** — new design filling a documented gap; requires formal adoption (ADR) before
>   implementation.
> - **[CONFLICT]** — the requested capability contradicts an approved rule or locked decision; a
>   human decision (and an ADR superseding the old rule) is required before any design is final.
>
> Per `.claude/rules/documentation.md` #1–2, nothing marked [PROPOSED] or [CONFLICT] may be
> implemented until adopted.

---

## 0. Executive Summary

RAAD's device plane is **two independent deployables** — the JT808 service (GPS/telematics/commands)
and the JT1078 service (live media relay) — plus one **[PROPOSED]** third component (Evidence Ingest,
for AI-alarm attachments). They share no process with the Business API, never write business tables,
and communicate with the business plane through **asynchronous domain events (uplink)** and **one
narrow synchronous signaling API (downlink, D6 seam)**.

The single most important architectural stance, already locked and reaffirmed here: **the device
plane is domain-thin.** It is protocol machinery — framing, parsing, session state, command relay,
media repackaging. All *meaning* (what a position implies for a trip, who may watch video, whether
an alarm notifies a parent, whether a device may be bound to a bus) lives in the Business API's
bounded contexts. If a future feature is tempted to put a business rule inside the JT808/JT1078
services, that temptation is a design error.

**Decisions this document needs from the platform owner** (detailed in §18):

| # | Decision | Default recommendation |
|---|----------|------------------------|
| 1 | Broker selection (open item since Phase 2 §4.3) | Decide **before** any device-plane implementation; Kafka-compatible if the 10k+ bus roadmap is real |
| 2 | Factory/warehouse inventory (pre-tenant devices) | New platform-scoped `device_inventory` table — ADR |
| 3 | AI-alarm evidence storage (snapshots/clips at rest) | Bounded evidence store with strict retention — ADR (touches the "no video storage" rule) |
| 4 | Cloud video recording | **Keep the approved "no cloud recording" rule**; evidence clips only via decision 3 |
| 5 | Engine cutoff | **Do not build.** Record a "will-not-implement" ADR now |
| 6 | Face recognition / "unknown person" | **Defer.** Biometric processing of minors; requires legal charter first |
| 7 | Intercom client surface | Defer until an approved client surface exists (none today) |
| 8 | Firmware/OTA ownership | `fleet_device` capability + JT808 execution — ADR |

---

## 1. Planes and Bounded Contexts

### 1.1 The four planes **[APPROVED — Phase 2 §4; extended]**

```
+---------------------------------------------------------------------------------+
| CLIENT PLANE                                                                    |
|   Web dashboard (React) · Parent app (Flutter) · Driver app (Flutter)           |
+---------------------------------------------------------------------------------+
        | HTTPS /api/v1 + WSS /ws/*                          ^ push (FCM)
        v                                                    |
+---------------------------------------------------------------------------------+
| BUSINESS PLANE (modular monolith, one deployable + workers)                     |
|   iam · organization · fleet_device · transport_ops · tracking · video          |
|   notifications · billing · reporting · platform_audit        (10 contexts,     |
|   fixed set — architecture rule #6)                                             |
+---------------------------------------------------------------------------------+
        ^ async domain events (broker)         | sync signaling API (D6 seam,
        |                                      |  downlink commands only)
        |                                      v
+---------------------------------------------------------------------------------+
| DEVICE PLANE (independent deployables, DMZ subnet — Phase 2 §11.3)              |
|   JT808 service (TCP gateway, sharded)                                          |
|   JT1078 service (media ingest/relay)                                           |
|   [PROPOSED] Evidence Ingest (AI-alarm attachment receiver)                     |
+---------------------------------------------------------------------------------+
        ^ JT808 TCP / JT1078 media streams
        |
   AI MDVR terminals on buses (GPS, cameras, DMS/ADAS/BSD, passenger counting)
+---------------------------------------------------------------------------------+
| MEDIA PLANE (delivery half of JT1078 service)                                   |
|   Repackager (JT1078 -> WebRTC / HLS / FLV) · token-gated Viewer Edge           |
+---------------------------------------------------------------------------------+
| NOTIFICATION PLANE (delivery half of the notifications context)                 |
|   notifications workers · FCM adapter · WS fan-out (/ws/notifications)          |
+---------------------------------------------------------------------------------+
```

The Media Plane and Notification Plane are **logical planes, not new deployables**: media delivery
is the egress half of the JT1078 service; notification delivery is the worker half of the
`notifications` context. Naming them separately matters because their scaling profiles and security
postures differ from their hosts (see §13, §16).

### 1.2 Module ownership map

The requested module list (Device, Gateway, Session, Location, Video, Alarm, Media, Command,
Firmware, Connectivity) mixes two different kinds of thing: **business bounded contexts** and
**technical components of the device services**. Conflating them is how business logic leaks into
the device plane. The correct assignment:

| Requested "module" | Actual owner | Kind | Trace |
|---|---|---|---|
| **Device** (identity, lifecycle, binding) | `fleet_device` context (Business) | Bounded context | DB §5, Phase 2 §19 — [APPROVED] |
| **Gateway** (TCP, framing, parsing) | JT808 service — Acceptor/Framer/Codec components | Technical component | Phase 3.4 §2/§6 — [APPROVED] |
| **Session** (connectivity state) | JT808 service — Session Manager (Redis + durable mirror) | Technical component | Phase 3.4 §5, jt808 rule #4 — [APPROVED] |
| **Location** (positions, geofences, trips-on-map) | `tracking` context (Business); JT808 only *produces* events | Bounded context | Phase 3.4 §10, Phase 2 §22 — [APPROVED] |
| **Video** (authority, sessions, who-may-watch) | `video` context (Business); JT1078 executes media only | Bounded context | Phase 3.5 §1, D5 — [APPROVED] |
| **Alarm** (normalization) | JT808 service ACL normalizes; `tracking`/`notifications` consume and decide | Split — see §10 | Phase 3.4 §11, ADR-808-9 — [APPROVED] |
| **Media** (ingest, repackage, edge) | JT1078 service | Technical component | Phase 3.5 §1 — [APPROVED] |
| **Command** (authority vs execution) | Authority: owning business context. Execution: JT808 Command Executor | Split — see §9 | Phase 3.4 §12, ADR-808-7 — [APPROVED] |
| **Firmware** | [PROPOSED] `fleet_device` capability (catalog, campaigns) + JT808 execution (0x8108) | New — see §9.5 | No approved source — ADR required |
| **Connectivity** (online/offline monitoring) | JT808 emits `DeviceOnline/Offline`; `fleet_device` owns the durable status read-model & exception workflows | Split | Phase 2 §21, jt808 rule #7 — [APPROVED] |

**Rule restated (architecture rule #6):** the ten business bounded contexts are a fixed set. Nothing
in this document adds an eleventh. Everything device-side is *components of the two (plus one
proposed) device services*, which are deployables, not bounded contexts of the monolith.

### 1.3 Internal component layout of the device services **[APPROVED — Phase 3.4 §1, 3.5 §1]**

```
JT808 service                              JT1078 service
+--------------------------------+         +--------------------------------+
| TCP Acceptor / Conn Manager    |         | Media Ingest (JT1078 frames)   |
| Framer (0x7e, escape, XOR)     |         | Stream Registry (Redis)        |
| Packet Parser + Vendor ACL     |         | Port Pool Manager              |
| Packet Dispatcher              |         | Repackager (WebRTC/HLS/FLV)    |
| Message Handlers               |         | Viewer Edge (token-gated)      |
|   register/auth/heartbeat/     |         | Video Session Manager          |
|   location/alarm/multimedia/   |         | Event Publisher                |
|   command-ack/backfill         |         +--------------------------------+
| Session Manager  <-> Redis     |
| Command Executor (downlink)    |         [PROPOSED] Evidence Ingest
| Event Publisher (local outbox) |         +--------------------------------+
| Local store: outbox, session   |         | Attachment receiver (vendor    |
|   mirror, raw-frame audit      |         |   AI-alarm file upload dialect)|
+--------------------------------+         | Object-store writer (ADR)      |
                                           | EvidenceStored event publisher |
                                           +--------------------------------+
```

---

## 2. Domain Model

### 2.1 Where the domain lives

The device plane deliberately has **no DDD aggregates persisted in the business sense**. Its
"entities" (Session, CommandExecution, StreamSession) are runtime technical state in Redis with
durable operational mirrors (Phase 3.4 §5/§14/§15). The rich domain model lives in the Business
API, primarily in `fleet_device`:

### 2.2 `fleet_device` domain model **[APPROVED — DB §5, Phase 2 §19; aggregate shaping is standard elaboration]**

**Aggregates**

| Aggregate | Root | Contains | Invariants |
|---|---|---|---|
| `Device` | Device | `Camera` entities (child, `ux_cameras__device_channel`) | terminal_id globally unique; lifecycle transitions per §3; a suspended/retired device is rejected at the gateway; auth key hash never exposed |
| `Vehicle` | Vehicle | — | per-tenant plate uniqueness (`ux_vehicles__org_plate`) |
| `DeviceAssignment` | DeviceAssignment | — | **one active binding per device AND per vehicle** (generated-column UX indexes, DB §5.4); driver is deliberately absent (device ≠ driver, Phase 2 §19.1) |

**Value objects:** `DeviceId`, `TerminalId` (JT808 identity, edition-aware — see §7), `Imei`,
`Iccid`, `Msisdn` (masked in logs — DB §5.2), `SerialNumber`, `DeviceLifecycleState`
(`registered|activated|assigned|suspended|retired` — DB §5.2 enum), `CameraChannel`,
`CameraPosition` (`in_cabin|road_facing|other` — D5-relevant), `FirmwareVersion` [PROPOSED].

**Domain events (published by `fleet_device`, consumed by the device plane's registry projection —
see §3.4):** `DeviceProvisioned`, `DeviceActivated`, `DeviceAssignedToVehicle`,
`DeviceUnassignedFromVehicle`, `DeviceSuspended`, `DeviceRetired`, `DeviceReplaced`,
`DeviceAuthKeyRotated`, `CameraRegistered`. PascalCase, past tense, per naming rules.

**Repository interfaces (domain-defined, infra-implemented — backend rule #2):**
`DeviceRepository` (get, get_by_terminal_id, add), `VehicleRepository`,
`DeviceAssignmentRepository` (active_for_device, active_for_vehicle, history, add),
`CameraRepository` (by_device).

**Policies:**
- `OneActiveDevicePerVehiclePolicy` — safety-critical, requires explicit regression tests
  (testing rule #3).
- `DeviceAuthPolicy` — a device may authenticate iff lifecycle ∈ {activated, assigned} and auth
  key matches (Phase 2 §12.7).
- `DeviceCommandPolicy` — which roles may issue which command class against which device (§9.2);
  evaluated in the Business API, never in the device plane (ADR-808-7).

**Factories:** `Device.provision(...)` (mints identity, initial lifecycle `registered`, hashes auth
key); `DeviceAssignment.bind(device, vehicle, actor, clock)`.

**Domain services:** `DeviceReplacementService` — the atomic swap operation (§3.3): close old
assignment, retire/return old device, provision/bind new device, preserving continuous history for
the vehicle. This is a domain service because it coordinates two `Device` aggregates and a
`DeviceAssignment` under one business transaction.

### 2.3 `video` context domain model **[APPROVED — Phase 3.5 §2, DB §7.4]**

Aggregates `VideoSession` and `PlaybackRequest` (control metadata only — never media);
`VideoAccessPolicy` enforcing D5 (Parent: no path, by construction; `in_cabin` cameras admin-only —
ADR-1078-8). Domain events: `VideoSessionStarted`, `VideoSessionEnded`, `PlaybackRequested`,
`PlaybackCompleted` — every one audited (jt1078 rule #6).

### 2.4 `tracking` context **[APPROVED — Phase 2 §22, DB §7.1]**

No device aggregate — tracking consumes `DevicePositionReported` and owns `vehicle_positions`
(partitioned), trip summaries, and the Geofence Evaluator. Live views use only `event_time ≈ now`,
never backfill (jt808 rule #3, ADR-808-5).

### 2.5 Device-plane runtime entities (not business aggregates) **[APPROVED — Phase 3.4 §5/§14]**

| Entity | Store | Lifecycle |
|---|---|---|
| `Session` | Redis `session:{terminal_id}` + durable mirror | connect → drop; refreshed by heartbeat |
| `CommandExecution` | Redis `cmd:{correlation_id}` | request → ack/timeout |
| `StreamSession` | Redis (JT1078 registry) | signal → teardown |
| `BackfillDrain` | in-process + session | reconnect → buffer drained |

---

## 3. Device Registration & Lifecycle

### 3.1 The approved lifecycle **[APPROVED — Phase 2 §19.2, DB §5.2]**

`registered → activated → assigned ⇄ (unassigned=activated) → suspended ⇄ → retired`

### 3.2 Mapping the requested stages **[stages before tenant allocation are PROPOSED]**

| Requested stage | Maps to | Status |
|---|---|---|
| Factory | `device_inventory.manufactured` | **[PROPOSED]** — see §3.5 |
| Warehouse | `device_inventory.in_stock` | **[PROPOSED]** |
| Installation | `devices.registered` (row created under the buying org; installer records IMEI/ICCID/SN, mounts hardware) | [APPROVED] |
| Activation | `devices.activated` — first successful JT808 register+auth handshake verified end-to-end | [APPROVED] |
| Binding to Bus | `devices.assigned` + active `device_assignments` row | [APPROVED] |
| Binding to School | implicit: `devices.organization_id` (tenant) — a device belongs to exactly one org; the *vehicle* belongs to the same org | [APPROVED] |
| Replacement | `DeviceReplacementService` (§3.3) | [APPROVED shape; service naming new] |
| Removal | unassign (assignment row closed with `unassigned_at`) → lifecycle back to `activated` | [APPROVED] |
| Retirement | `retired` (terminal); gateway rejects any future connection and audits it (jt808 rule #5) | [APPROVED] |

```
[PROPOSED: platform inventory]          [APPROVED: tenant-owned lifecycle]
manufactured -> in_stock -> allocated ==> registered -> activated -> assigned
                                              ^              |          |
                                              |         (unassign)      |
                                              |              v          |
                                              +---------- activated <---+
   any tenant state -> suspended (admin disable; connections rejected)
   activated/suspended/unassigned -> retired (terminal)
```

**Transition authority** (least privilege, security rule #1): inventory transitions — RAAD staff
(Founder/ops); registered/activated — RAAD staff or installer flow; assign/unassign — Org Admin or
RAAD staff in scope; suspend — Org Admin (own org) or RAAD staff; retire — RAAD staff. Every
transition emits its domain event and an audit entry.

### 3.3 Replacement (the case that breaks naive designs)

A failed MDVR on a bus mid-year must be swapped **without corrupting history**: old positions/alarms
remain attributed to the old `device_id` but the *vehicle's* history is continuous because
`vehicle_positions` and trips key on `vehicle_id` (DB §7.1) — this is precisely why the gateway
resolves `terminal_id → device → vehicle → org` at ingest time and stamps events with all three.
`DeviceReplacementService`: (1) close active assignment of old device; (2) old device →
`retired` (or back to inventory if refurbishable — [PROPOSED]); (3) new device must already be
`activated`; (4) bind new device to vehicle; (5) emit `DeviceReplaced {vehicle_id, old_device_id,
new_device_id}` so the device-plane registry projection cuts over atomically.

### 3.4 How the device plane learns all this **[APPROVED — ADR-808-4]**

The device plane **never reads the business DB**. `fleet_device` lifecycle events feed a **device
registry projection** in the device plane's Redis:

```
registry:{terminal_id} -> { device_id, vehicle_id?, organization_id,
                            lifecycle_state, auth_key_hash, vendor, cameras[] }
```

- Gateway authentication and event enrichment read only this projection.
- The projection is **reconstructable**: a rebuild endpoint/worker can replay a snapshot on
  cold start (Redis loss is survivable — Phase 3.4 §14).
- **Consequence to accept:** eventual consistency — a just-suspended device may complete one more
  heartbeat before the projection catches up. Acceptable; suspension is not a hard-real-time
  security control (network-level controls are — Phase 2 §11.3).

### 3.5 [PROPOSED — ADR required] Platform inventory (`device_inventory`)

**Gap found:** `devices.organization_id` is `NOT NULL` (DB §5.2) — correct for tenant isolation,
but it makes factory/warehouse stock unrepresentable (stock belongs to RAAD, not to any tenant).

**Options:**
1. Make `organization_id` nullable — **rejected**: weakens the multi-tenant invariant on a
   tenant-owned table (database rule #2) for a marginal need.
2. A RAAD-internal pseudo-organization — **rejected**: pollutes tenant semantics, poisons
   every `organization_id`-scoped query.
3. **A separate platform-scoped `device_inventory` table** (like `regions`, no `organization_id`),
   owned by `fleet_device`, holding pre-tenant units (SN, IMEI, ICCID, model, vendor, state:
   `manufactured|in_stock|allocated|scrapped`). Allocation to a tenant creates the `devices` row
   and links back by `inventory_id`. — **Recommended.**

---

## 4. Connection Lifecycle

**[APPROVED — Phase 2 §21.1, Phase 3.4 §3/§9/§17; presented here with the requested state names
mapped onto the approved machine]**

```
                       TCP accept            0x0100 ok             0x0102 ok
   OFFLINE ────────────► CONNECTING ────────► REGISTERED ─────────► AUTHENTICATED
 (Disconnected)              │                                            │
      ▲                      │ reject: unknown/suspended/retired          │ first heartbeat
      │                      ▼      (audited — jt808 rule #5)             ▼ /location
      │                   [closed]                                     ONLINE ⇄ IDLE
      │                                                                   │   (stationary,
      │        heartbeat/read timeout or socket drop                      │    reduced cadence)
      ├───────────────────────────────────────────────────────────────────┤
      │                                                                   │
      │    reconnect                     reconnect w/ buffered data       │
      └──► CONNECTING ──► ... ──► ONLINE      └──► BACKFILLING ──► ONLINE
                                                    (0x0704 / late 0x0200,
                                                     original ts + backfill=true)
```

| Requested state | Disposition |
|---|---|
| Offline / Connecting / Registered / Authenticating / Online / Heartbeat / Reconnect | Direct states/edges of the approved machine above |
| Temporary Disconnect | `Offline` before the offline-threshold timer fires — no `DeviceOffline` event yet (debounce) |
| Permanent Offline | **Escalation tier, not a state:** `Offline` beyond a configurable threshold (e.g. 24h) raises an operational exception in `fleet_device` monitoring; during an active trip, offline immediately surfaces to the Org Admin monitor and may flag the trip `Interrupted` (Phase 2 §21.2) |
| Session Expired | Redis session TTL lapse (no heartbeat refresh) → device must re-register/re-auth on next contact; half-open sockets reaped by read timeout |
| Shutdown (platform side) | Graceful drain: stop accepting, keep serving until sessions migrate (sticky LB re-hash), flush local outbox, then exit. Device sessions survive node death because Redis + durable mirror are the source of truth (Phase 3.4 §5) |

**Timer table (configurable, per Phase 2 §13.1):** heartbeat interval (device-set via 0x8103);
read timeout ≈ 3× heartbeat; offline threshold (event emission); session TTL; backfill drain rate
limit (protects the broker from reconnect floods — see §16.4).

**Single-active-session rule [APPROVED — ADR-808-8]:** newest authenticated connection wins; the
older socket is closed. Prevents half-open ghosts after network flaps.

`DeviceOnline` / `DeviceOffline` are emitted **only** on debounced transitions (jt808 rule #7) and
drive: device-status read-model (`devices.last_seen_at` durable mirror), ops monitoring, the
`camera offline` / `video lost` derived alarms (§10), and trip-interruption policy.

---

## 5. JT808 Architecture

**[APPROVED — Phase 3.4 in full. This section is a compressed restatement plus the deltas the new
capabilities need. Phase 3.4 remains the source of truth for everything restated.]**

### 5.1 Core (restated)

- **TCP server:** async event-loop acceptor; thousands of persistent connections per node; 0x7e
  framing with escaping + XOR checksum; per-connection buffer limits and backpressure (§2).
- **Authentication:** 0x0100 registration → 0x8100 (+auth code) → 0x0102 authentication → 0x8001;
  validated against the registry projection (§3.4); unknown/unauthenticated rejected **and
  audited** (jt808 rule #5). Compensating controls per security rule #9: device auth keys, IP/APN
  allowlisting where supported, DMZ isolation, traffic anomaly detection.
- **Heartbeat:** 0x0002 refreshes session TTL; drives §4 timers.
- **Location upload:** 0x0200 (single), 0x0704 (batch/backfill). Handlers normalize (vendor ACL),
  resolve identity, write `vehicle:{id}:last` to Redis, publish `DevicePositionReported`.
  Backfill: original timestamp + `backfill=true`; live map and geofence evaluation ignore it
  (jt808 rule #3, ADR-808-5).
- **Alarm upload:** alarm bits in 0x0200 + vendor AI dialect messages → canonical taxonomy via ACL
  (§10), dedupe in Redis, publish `DeviceAlarmRaised`.
- **Command response:** 0x0001 (terminal general ack) + command-specific responses matched by
  serial number to `cmd:{correlation_id}` (§9.4); result events published.
- **Packet routing:** dispatcher keyed by message ID → handler; multi-packet reassembly (subpackage
  flag in header) with bounded reassembly buffers; duplicate-serial dedupe.
- **Acknowledgement matrix:** every uplink that requires ack gets 0x8001 with matching serial;
  ack discipline is per JT/T 808 spec — never “best effort”.
- **Connection recovery:** reconnect → single-session rule → backfill drain (rate-limited).
- **Event publishing:** local transactional outbox → relay → broker; envelope per API Contracts
  §13.1; consumers idempotent by `event_id` (Phase 3.4 §13).
- **Local store [APPROVED — ADR-808-2]:** JT808's **own** small durable store (its outbox, session
  mirror, optional raw-frame audit). This is *not* the business DB and holds no business tables.
- **Scaling:** sticky TCP LB → sharded nodes; Redis session registry is the shared truth so any
  node resolves any device; cross-shard command routing via `shard:{terminal_id}` (§16).

### 5.2 Deltas required by the AI MDVR scope **[PROPOSED unless noted]**

| Delta | Design | Status |
|---|---|---|
| **Protocol editions** | ACL must handle JT/T 808-2013 vs 2019 (different terminal-ID widths, attribute fields). Edition detection per vendor adapter; canonical `TerminalId` VO hides it | [APPROVED in spirit — ADR-808-3 vendor ACL; edition detail is implementation guidance] |
| **AI alarm dialect ingestion** | DMS/ADAS/BSD alarms arrive as vendor-extended messages (Su-biao T/JSATL12-style: extended alarm payloads in 0x0200 additional-info + attachment-upload sub-protocol). New handler family + per-vendor adapters. Canonical output: `DeviceAlarmRaised` with `alarm_class=ai`, evidence refs | **[PROPOSED]** — §10, §12 |
| **Attachment upload** | Vendor AI alarms push evidence files (JPEG snapshots, short clips) over a *separate* TCP connection with its own handshake (0x1210/0x1211/0x1212-style). This is neither GPS nor live media → the **[PROPOSED] Evidence Ingest** component (§12.3) so JT808 nodes aren't blocked by file transfers | **[PROPOSED]** — ADR required (storage) |
| **Passenger counting** | Counts arrive as vendor extensions (0x0200 additional info or proprietary message). ACL normalizes to `PassengerCountReported {boarded, alighted, occupancy, door, ts}` telemetry events | **[PROPOSED]** — §12.4 |
| **Multimedia (snapshot) upload** | 0x8801 (capture command) → device replies 0x0805 → uploads via 0x0801 multimedia-data message **over JT808**, not JT1078. Handler stores via Evidence Ingest path | **[PROPOSED]** (command approved-shape; storage needs ADR) |

---

## 6. JT1078 Architecture

**[APPROVED — Phase 3.5 in full; compressed restatement plus deltas.]**

### 6.1 Core (restated)

- **Media server:** standalone; accepts JT1078 RTP-style media from MDVRs on pooled ports;
  **stores no video** (ADR-1078-1); repackages (not transcodes where possible) to WebRTC (primary)
  and HLS/FLV (fallback) — jt1078 rule #5, ADR-1078-5.
- **Stream registry:** Redis — active sessions, port leases, tokens, per-org/global concurrency
  counters. Ports leased on session open, reclaimed on teardown (jt1078 rule #4).
- **Video/audio channels:** `cameras.channel_no` (DB §5.3) is the JT1078 logical channel; camera
  `position` drives D5 exposure rules (`in_cabin` admin-only — ADR-1078-8). Audio channels ride the
  same session (stream type audio/video/AV).
- **Live streaming flow:** Org Admin → Business API → `VideoAccessPolicy` (D5) → mint short-lived
  signed stream token + allocate session → signal device via JT808 downlink 0x9101 (server
  IP/port/channel/type) → device pushes media → ingest → repackage → token-gated Viewer Edge.
  0x9102 stops. FastAPI and JT1078 never open a device control socket (D6, ADR-1078-3).
- **Playback:** 0x9205 (query device-side recordings) → 0x9201 (playback request) → device streams
  from **its own storage** → same repackage path; 0x9202 controls (pause/seek/stop). Availability
  is best-effort — the MDVR is the sole system of record (ADR-1078-7).
- **Recording:** local on MDVR only. Cloud recording: **[CONFLICT]** — see §11.3.
- **Snapshot:** flows over JT808 (§5.2), not JT1078 — listed here because users think of it as
  “video” but architecturally it is a command + file upload.
- **Stream authorization:** all authorization upstream in the Business API; JT1078 verifies only
  the signed token (audience, expiry, session binding) — it never decides *who* (ADR-1078-2).
  Parents: no token is ever minted, no endpoint exists — no path, by construction (D5, ADR-1078-4).
- **Audit:** every session open/close audited with actor, device, camera, time (jt1078 rule #6).
- **Concurrency:** per-org + global ceilings, admission control, queue-or-refuse with a clear
  message (jt1078 rule #4, ADR-1078-6); idle teardown (Phase 3.5 §18.4).

### 6.2 Deltas **[PROPOSED]**

| Delta | Design | Status |
|---|---|---|
| **Intercom (two-way audio)** | JT1078 supports bidirectional talk (0x9101 data-type=2). Media path is symmetric: platform must *send* audio to the device. Technically an extension of the repackager (browser mic → server → JT1078 audio frames). **Blocker:** no approved client surface exists — web dashboard has no talk UI in any approved doc, and Flutter rules forbid live media surfaces on mobile. **Recommendation:** design the media-plane seam now (session type `intercom`, same token/ceiling/audit machinery), build nothing until a client surface is approved | **[PROPOSED — deferred]** |
| **Evidence clips at the media plane** | None — evidence flows through Evidence Ingest (§12.3), not the live-media path. Keeping them separate protects live-stream latency from file transfers | **[PROPOSED]** |

---

## 7. Device Identity

### 7.1 Identity fields and their single sources of truth

| Field | What it is | Owner / storage | Uniqueness | Notes |
|---|---|---|---|---|
| `device_id` | Platform identity (ULID) | `fleet_device.devices.id` | global PK | The only ID other contexts may reference (by ID only — database rule #3) |
| `terminal_id` | JT808 wire identity (the BCD “phone number” in every message header; 6 bytes in 2013, 10 in 2019) | `devices.terminal_id` | **global unique** (`UX`, DB §5.2) | The gateway's lookup key; edition differences hidden by the `TerminalId` VO/ACL |
| SIM (MSISDN) | The SIM's phone number | `devices.sim_msisdn` | not unique (SIM swaps) | Masked in logs (DB §5.2) — PII |
| IMEI | Modem hardware identity | `devices` **[PROPOSED column — gap]** | unique | Approved schema lacks it; needed for theft/fraud checks and vendor support. Additive migration + ADR note |
| ICCID | SIM card identity | `devices` **[PROPOSED column — gap]** | unique per SIM | Detects SIM swaps (`SIM removed` alarm correlation, §10) |
| Serial number | Vendor hardware SN | `devices` **[PROPOSED column]** / `device_inventory` (§3.5) | unique per vendor | Warehouse/RMA workflows |
| VIN | Vehicle identity | **`vehicles`** [PROPOSED column], *not* `devices` | unique | A VIN identifies the bus, not the box — putting it on the device is a modeling error that breaks replacement (§3.3) |
| Bus assignment | `device_assignments` active row | `fleet_device` | one active per device & per vehicle | DB §5.4 generated-column UX |
| School assignment | `devices.organization_id` | `fleet_device` | one org per device | The tenant boundary; never inferable from traffic, always from provisioning |

### 7.2 How identity works at runtime

```
JT808 header terminal_id
      │  registry:{terminal_id} (projection, §3.4)
      ▼
{ device_id, vehicle_id?, organization_id, lifecycle, auth_key_hash, vendor }
      │
      ▼
every published event stamped with device_id + vehicle_id + organization_id
```

- **Resolution happens exactly once, at the gateway.** Downstream consumers never re-resolve —
  they trust the stamped IDs. This keeps tenancy on every event (multi-tenant rule) and lets the
  tracking consumer partition by vehicle without lookups.
- **Anti-spoofing:** terminal_id alone is trivially spoofable (it's plaintext in every header).
  Authentication = auth key (0x0102, hash compared against projection) + optional IP/APN allowlist
  + anomaly detection (security rule #9). A registered-but-never-activated terminal_id cannot
  authenticate.
- **Unassigned-but-online** (activated, no vehicle): positions are accepted, stamped with
  `vehicle_id=null`, retained for install verification, but never enter trip/geofence evaluation.

---

## 8. Bus Integration (context relationships without violating DDD)

### 8.1 Ownership of each relationship

```
organization (C2)                who owns what:
    │ organization_id              org --< vehicle        fleet_device
    ▼                              org --< device         fleet_device
fleet_device (C3)                  device >--< vehicle    fleet_device (device_assignments)
    vehicle ◄──── device           vehicle : camera(s)    fleet_device (via device)
       ▲   (active assignment)     driver >-- trip        transport_ops
       │                           route --< stop         transport_ops
transport_ops (C4)                 student >--< route     transport_ops (student_assignments)
    trip ──references──► vehicle_id, driver_id, route_id (IDs only, no FK across contexts)
    student ◄── parent (parent-own-children-only — testing rule #3)
tracking (C5)
    vehicle_positions(vehicle_id, trip_id) — consumes device events, owns position truth
video (C6)
    video_sessions(device_id, camera_id, actor) — control metadata only
```

**The rules that keep this clean (all approved):**
1. Cross-context references are **IDs only**, no cross-module FKs (database rule #3), no
   cross-module DB reads (backend rule #3).
2. The **device never knows about students, parents, routes, or trips.** It reports positions,
   alarms, counts. Meaning is assigned in the business plane: the tracking consumer joins
   position→trip via the active-trip read-model; transport_ops joins trip→students via
   assignments; notifications joins students→parents via its own read-model.
3. **Driver is not in the device↔vehicle relationship** (Phase 2 §19.1). Changing a driver never
   touches device state. The Driver app is a Business-API client; the driver's phone is **not** a
   tracking source (flutter rule #2).
4. **Camera position (`in_cabin` vs `road_facing`)** is a fleet_device fact that the video
   context's policy consumes — D5's “by construction” depends on this field being provisioning
   data, not runtime-configurable by tenants.

### 8.2 The enrichment chain for one position

```
device (terminal_id) → gateway stamps {device_id, vehicle_id, org_id}
  → tracking consumer attaches {trip_id?} from trip:active:{vehicle_id}
    → geofence evaluator attaches {stop_id?, event}
      → notifications resolves {students on trip} → {parents of those students}
```

Each arrow is one context consuming the previous context's event — never a synchronous call into
another module, never a cross-module join.

---

## 9. Command Architecture

### 9.1 The split that must never blur **[APPROVED — ADR-808-7, D6]**

**Authority** (may this actor do this to this device, now?) lives in the Business API — RBAC +
tenancy + domain policy. **Execution** (encode, dispatch, track, ack) lives in the JT808 Command
Executor. The device plane executes any command the Business API hands it; it never re-checks
business permissions (it has none to check) — which is exactly why no client may ever reach the
device plane's signaling API directly (network-enforced, D6 seam).

### 9.2 Command catalog

| Command | JT808 msg | Authority (context, role) | Risk class | Offline policy | Status |
|---|---|---|---|---|---|
| Restart terminal | 0x8105 (word 4) | fleet_device — Org Admin / RAAD support | medium | reject if offline | [APPROVED shape] |
| Factory reset | 0x8105 (word 5) | fleet_device — RAAD support only | high | reject | [APPROVED shape] |
| Snapshot | 0x8801 → 0x0805/0x0801 | video — same matrix as live video (D5: never Parent) | low | reject | **[PROPOSED]** (storage ADR) |
| Video start (live) | 0x9101 | video — `VideoAccessPolicy` | medium | reject | [APPROVED] |
| Video stop | 0x9102 | video | low | n/a | [APPROVED] |
| Playback query/start/ctl | 0x9205/0x9201/0x9202 | video | medium | reject | [APPROVED] |
| Intercom open | 0x9101 (type 2) | video — **no approved surface** | medium | reject | **[PROPOSED — deferred]** (§6.2) |
| Text to driver display | 0x8300 | transport_ops or fleet_device — Org Admin | low | queue-until-online OK | [APPROVED shape] |
| Set parameters (reporting cadence, APN, server) | 0x8103 / query 0x8104/0x8106 | fleet_device — RAAD support (server params), Org Admin (cadence within bounds) | high (bricking risk) | queue-until-online OK | [APPROVED shape] |
| Geofence update (device-side) | 0x8600/0x8601/0x8602… | tracking — **note:** RAAD's geofence evaluation is platform-side (Phase 2 §22); device-side fences are an optional redundancy, not the system of record | medium | queue OK | [APPROVED — platform-side is primary] |
| OTA firmware | 0x8108 | fleet_device — RAAD support only, via campaigns (§9.5) | **very high** | queue-until-online required | **[PROPOSED — ADR]** |
| Engine cutoff | 0x8500 | — | **extreme** | — | **[CONFLICT — recommend never]** (§9.6) |

### 9.3 Command state machine **[APPROVED shape — Phase 3.4 §12; elaborated]**

```
REQUESTED (Business API: authz passed, correlation_id minted, audit written)
   │  signaling API → JT808 (D6 seam)
   ▼
DISPATCHED (executor encoded + wrote cmd:{correlation_id}, sent on device socket)
   │ 0x0001 ack (serial match)              │ timeout (per class)
   ▼                                        ▼
ACKED ──► SUCCEEDED / FAILED (result msg)  TIMED_OUT ──► retry (bounded) or surface
   │
   ▼ (0x8103/0x9101 etc. may have a second, command-specific result)
RESULT event → broker → owning context persists outcome + audit closes the loop
```

Every command is **correlation-ID tracked end to end** (jt808 rule #6): requesting use-case →
dispatch → device ack → result event → audit. Idempotency: command requests carry an idempotency
key; re-dispatch after crash re-uses the correlation ID; duplicate device acks are dropped by
serial dedupe.

### 9.4 Offline handling policy

Default **reject-if-offline with a clear error** — silent queues create dangerous surprises
(a “restart” queued Friday executing Monday mid-route). Per-class opt-in `queue_until_online`
(text messages, parameter sets, OTA) with a TTL and cancellation surface.

### 9.5 [PROPOSED — ADR required] Firmware / OTA

No approved document covers firmware. Proposed ownership: **`fleet_device` capability** (not an
eleventh context): firmware catalog (versions, checksums, vendor/model compatibility), rollout
campaigns (target cohorts, canary %, pause/abort), per-device install state. Execution via 0x8108
through the standard command pipeline. Non-negotiable safeguards: staged rollout (canary → cohort →
fleet), never during active trips (check trip read-model), automatic halt on elevated
offline/rollback rates, signed firmware only, RAAD-staff-only authority. The binary artifact store
is the same object-store decision as evidence (§12.3, one ADR can cover both).

### 9.6 [CONFLICT — recommend refusal] Engine cutoff

0x8500-class vehicle control on a **school bus** is a life-safety actuator. Wrong-vehicle targeting,
replayed/spoofed commands, or cutoff at speed are catastrophic failure modes; several jurisdictions
regulate or prohibit remote immobilization of passenger-carrying vehicles. Recommendation: adopt a
**“will not implement” ADR now** so the decision is deliberate and visible. If ever revisited:
separate signed command channel, multi-party authorization, speed-conditioned interlock enforced by
the device (not the platform), regulatory review — a project in its own right, not a command-table
row.

---

## 10. Alarm Architecture

### 10.1 Pipeline **[APPROVED — Phase 3.4 §11, ADR-808-9; extended taxonomy PROPOSED]**

```
raw source                normalize            decide & route
──────────                ─────────            ──────────────
JT808 0x0200 alarm bits ─┐
vendor AI messages ──────┼─► Vendor ACL ─► canonical DeviceAlarmRaised ─► broker
platform-derived ────────┘    (taxonomy,      {alarm_type, severity, device/vehicle/org,
 (built in business plane)     dedupe in       ts, evidence_refs?, backfill?}
                               Redis)                       │
                                     ┌──────────────────────┼──────────────────────┐
                                     ▼                      ▼                      ▼
                               tracking (ops           notifications         platform_audit
                               monitor, trip           (catalog-gated —      (always)
                               exception flags)        most alarms are NOT
                                                       parent-facing)
```

### 10.2 Alarm taxonomy

| Alarm | Source | Detected by | Severity | Parent-facing? | Status |
|---|---|---|---|---|---|
| Overspeed | 0x0200 alarm bit / ADAS | device | high | no (ops) | [APPROVED] |
| Fatigue driving | 0x0200 bit + DMS AI | device | high | no | bit [APPROVED]; AI **[PROPOSED]** |
| Harsh braking / acceleration | vendor g-sensor ext | device | medium | no | **[PROPOSED]** |
| Collision / rollover | 0x0200 bits / g-sensor | device | **critical** | no (ops escalation; parent comms are a human/ops decision, not an auto-notification) | [APPROVED bits] |
| Geofence in/out | **platform** geofence evaluator (Phase 2 §22) — device-side fence alarms accepted as redundant input, platform is authoritative | platform | info–medium | **yes** — this is the approved parent-notification family (approaching/arrived) | [APPROVED] |
| SOS (panic button) | 0x0200 bit | device | **critical** | no (ops + org escalation) | [APPROVED] |
| Video lost / camera occlusion | vendor ext + JT1078 stream telemetry | device + platform | medium | no | **[PROPOSED]** |
| Camera offline | derived: expected camera set (fleet_device) vs stream health | **platform** | medium | no | **[PROPOSED]** |
| Power loss (main supply cut) | 0x0200 bit | device | high (theft/tamper signal) | no | [APPROVED] |
| SIM removed | vendor ext; corroborate with ICCID change on reconnect (§7) | device + platform | high | no | **[PROPOSED]** |
| Storage failure (SD/HDD) | vendor ext | device | medium (playback SLA risk — flag loudly: MDVR is the only recording, ADR-1078-7) | no | **[PROPOSED]** |
| Passenger left behind | **derived, business plane:** trip ended ∧ occupancy>0 (§12.4) or in-cabin motion after end | **platform (transport_ops)** | **critical** | escalation to org + designated staff; parent contact is an ops workflow | **[PROPOSED]** |

**Design rules:** (1) the ACL translates vendor codes to the canonical taxonomy — a new vendor is a
new adapter, never a parser change (ADR-808-3). (2) Dedupe per `{vehicle, alarm_type}` window in
Redis — a flapping sensor must not melt the notification plane. (3) **Severity ≠ routing**: routing
is decided by the notifications context against its approved catalog; the device plane never
decides who gets told (ADR-808-9). (4) Backfilled alarms carry `backfill=true` and never trigger
live escalation — only history.

---

## 11. Video Architecture

### 11.1 Live + playback **[APPROVED]** — consolidated in §6.1; authorization matrix per Phase 3.5
§6/§10: Founder/RAAD staff (governed + audited), Org Admin (own org, 24/7), Driver — no, Parent —
**no path, by construction** (D5). `in_cabin` cameras: admin-only (ADR-1078-8). Web dashboard is
the only live-video surface (frontend rule #4); no mobile video for any role (flutter rule #3,
ADR-1078-10).

### 11.2 Retention

- **Local (MDVR):** sole system of record; loop-recording capacity is a hardware sizing question
  per org (typ. 3–14 days at school-bus duty cycles). `Storage failure` alarm (§10) is what makes
  this posture operationally honest.
- **Cloud:** none (ADR-1078-1). Session/playback **metadata** persists in the business DB
  (`video_sessions`, `playback_requests` — DB §7.4) — control facts, never media.

### 11.3 [CONFLICT — decision required] Cloud recording

Requested “Cloud Recording” directly contradicts jt1078 rule #2 / ADR-1078-1 (“RAAD is not a video
archive… stores no video”). Options:

| Option | Consequence | Recommendation |
|---|---|---|
| A. Keep the rule (no cloud video) | Zero media-at-rest risk (minors!), zero storage cost, playback SLA bounded by MDVR health | **Default — keep** |
| B. Alarm-evidence clips only (short, bounded, auto-expiring) | Small, capped object store; huge investigative value for collision/SOS; **still video-at-rest** → encryption, retention limits, access audit, privacy review | Worth an ADR — pairs with §12.3, which needs the same store for snapshots anyway |
| C. Full cloud DVR | Massive cost, maximal privacy exposure of children, contradicts the entire approved posture | **Reject** |

### 11.4 Bandwidth optimization **[APPROVED — Phase 3.5 §16; consolidated]**

Request **sub-stream** (JT1078 stream-type selector) for live monitoring by default, main-stream
on demand; repackage-not-transcode (ADR-1078-5); admission control + per-org/global ceilings
(ADR-1078-6); idle teardown; viewer count per session capped (one ingest, N viewers via the edge —
never N device streams); playback rate-limited per device uplink (cellular is the bottleneck:
one 2–4G modem can rarely sustain 2 simultaneous main-streams — surface “channel busy” honestly).

---

## 12. AI Events

**[PROPOSED throughout — no approved document covers AI events. Requires adoption before build.]**

### 12.1 Taxonomy

| Family | Events | Canonical event |
|---|---|---|
| DMS (driver-facing) | distraction, phone usage, smoking, yawning/fatigue, seatbelt off, driver absent | `DriverBehaviorEventDetected {type, confidence, evidence_refs}` |
| ADAS (road-facing) | forward collision warning, lane departure, headway too close, pedestrian | `AdasEventDetected {...}` |
| BSD | blind-spot object during turn | `AdasEventDetected {type=bsd}` |
| Cabin | passenger standing while moving, door open while moving | `CabinSafetyEventDetected {...}` |
| Counting | boarded/alighted per door event, occupancy | `PassengerCountReported {...}` (telemetry, not alarm) |
| Unknown person | face-recognition mismatch | **deferred — see 12.5** |

All are **vendor-dialect messages** normalized by the ACL (§5.2) — the taxonomy above is the
platform contract; vendor codes never leak past the adapter.

### 12.2 Processing stance

The MDVR does the AI (edge inference). The platform **does not run inference in MVP** — it ingests,
normalizes, correlates, and routes. This keeps the device plane domain-thin and the cost model flat.
(A future platform-side inference tier would be a new deployable behind the same event contracts —
§17.)

High-frequency, low-confidence events (yawns) are **telemetry** aggregated into driver-safety
scoring (reporting context, batch); low-frequency, high-severity events (collision, phone-while-
driving) are **alarms** through §10's pipeline. The severity/threshold split is per-org
configuration owned by the business plane — never hardcoded in the ACL.

### 12.3 Evidence Ingest (the new component) **[PROPOSED — ADR required]**

AI alarms arrive with attachments (JPEG frames, 5–10 s clips) via a vendor file-upload
sub-protocol on a separate TCP connection. Design:

- A dedicated **Evidence Ingest** deployable in the device plane (not inside JT808 nodes — file
  transfer must never block the telemetry hot path; not inside JT1078 — it is not live media).
- Writes to an **object store** (new infrastructure — the ADR this requires is the same one as
  §9.5's firmware artifacts and §11.3-B's clips): encrypted at rest, per-org prefixes,
  strict TTL (e.g. 30–90 days, configurable), access only via Business-API-minted signed URLs,
  every access audited. Contains images of **children** — treat with the same severity as video.
- Publishes `EvidenceStored {alarm_correlation_id, object_key, kind, ttl}`; the alarm consumer in
  the business plane links evidence to the alarm record. Evidence is referenced by key, never
  embedded in events.

### 12.4 Passenger counting — the honest boundary

Counting is **anonymous occupancy telemetry**. It must never be conflated with per-student
boarding/alighting identity (which would require RFID cards or face-ID — not in approved scope).
Legitimate uses now: occupancy on the ops monitor; **`passenger left behind`** derived alarm
(trip ended ∧ occupancy > 0 — §10); count-vs-roster discrepancy flags for ops. Explicitly forbidden
without new approval: “your child boarded” parent notifications driven by a counter — that is a
correctness lie (counts ≠ identity) with real safety consequences.

### 12.5 Unknown person / face recognition — **[CONFLICT — recommend defer]**

Biometric identification of minors: the heaviest legal/ethical item in the entire request
(GDPR-class biometric rules, guardian consent, retention, cross-border storage). Not designable as
a footnote. Recommendation: **defer**; if pursued, it starts with a legal/privacy charter and its
own ADR series. The event taxonomy reserves the name; nothing more.

---

## 13. Business API ↔ Device Plane Boundary (the contract table)

### 13.1 The four boundaries

| # | Boundary | Direction | Mechanism | The rule |
|---|---|---|---|---|
| 1 | Device → Business (uplink) | one-way, async | Domain events over broker (local outbox → relay). Topics: `device.position_reported` (firehose, partitioned by vehicle), `device.online/offline`, `device.alarm_raised`, `device.command_result`, `device.passenger_count`, `media.evidence_stored`, `video.session_started/ended` | **Only** path for device data into the business plane. Device plane never writes business tables (jt808 rule #1), never RPCs into business modules |
| 2 | Business → Device (downlink) | one-way, sync | The **signaling API** (D6 seam — already configured: `RAAD_DEVICE_PLANE__JT808_SIGNALING_URL` / `JT1078_SIGNALING_URL`): narrow, internal-network-only, mTLS/service-auth, request = pre-authorized command envelope with correlation ID | The **only** synchronous call between planes. Authorization already happened (§9.1); the device plane trusts the envelope because the network makes it unreachable by anyone but the Business API |
| 3 | Business → Device (projection) | one-way, async | `fleet_device` lifecycle events → device-registry projection in device-plane Redis (§3.4) | The device plane's *only* source of provisioning truth. Never a DB read |
| 4 | Business → Media Plane (viewer authority) | one-way | Signed short-lived stream tokens minted by Business API; Viewer Edge verifies signature/expiry/session only | The media plane never evaluates roles. No token → no stream. Parents: no token is ever minted (D5) |

### 13.2 The “never” list (each is a design-review blocker)

- Device plane holding business-DB credentials — never (any environment).
- FastAPI (or any business module) opening a device socket — never (D6).
- A client (web/mobile) reaching the signaling API or media ingest — never (network + no route).
- The device plane deciding notification routing, video permission, trip meaning — never.
- Synchronous business-plane call *into* the device plane other than boundary #2 — never.
- Notification plane consuming raw device events — never; it consumes **business** events
  (`TripStarted`, `VehicleApproachingStop`…) produced by business contexts after enrichment.

---

## 14. Event Flow (end-to-end text diagrams)

### 14.1 Live position → parent sees the bus

```
MDVR ──0x0200──► JT808 gateway
                   │ resolve terminal→{device,vehicle,org}; Redis vehicle:last
                   │ outbox → broker: device.position_reported (backfill=false)
                   ▼
        tracking consumer (Business)
                   │ attach trip_id (trip:active read-model); persist vehicle_positions
                   │ WS fan-out /ws/tracking (capability ∧ scope ∧ ownership ∧ time-window)
                   ├────────────► Org Admin live map (24/7, own org)
                   │ geofence evaluator ──► VehicleApproachingStop
                   ▼
        notifications consumer
                   │ resolve students-on-trip → parents; SubscriptionAccessPolicy (CR-1:
                   │ safety notifications never billing-gated — D4)
                   ▼
              FCM push ──► Parent app (active-trip-only live view — flutter rule #4)
```

### 14.2 AI alarm with evidence

```
MDVR ──vendor DMS msg──► JT808 ACL ──► device.alarm_raised {type=phone_usage, corr_id}
   └─attachment TCP──► Evidence Ingest ──► object store ──► media.evidence_stored {corr_id}
                                   (both events, broker)
                                          ▼
                     tracking/fleet ops consumer: alarm record + evidence link
                                          ▼
                     ops monitor (Org Admin) · driver-safety score (reporting, batch)
                     [no parent notification — ADR-808-9]
```

### 14.3 Live video session

```
Org Admin (web) ──► Business API: video.start {vehicle, camera}
    │ VideoAccessPolicy (D5) ∧ scope ∧ camera.position rules ∧ ceilings → audit
    │ allocate session + port lease + mint stream token
    ├──signaling (D6)──► JT808 ──0x9101──► MDVR
    ▼                                        │ JT1078 media stream
Admin player ◄──WebRTC/HLS── Viewer Edge ◄── Repackager ◄── Media Ingest
    (token-gated)                    teardown: 0x9102, port reclaim, session_ended, audit
```

### 14.4 Command round-trip

```
Use-case (Business) ──authz+audit──► signaling API ──► JT808 Command Executor
   ──encode+cmd:{corr_id}──► device ──0x0001 ack──► executor
   ──► broker: device.command_result {corr_id, outcome} ──► owning context closes loop
   (timeout ⇒ TIMED_OUT result; bounded retry per class — §9.3/§9.4)
```

### 14.5 Reconnect with backfill

```
MDVR (2h offline, buffer full) ──reconnect/auth──► JT808
   ──0x0704 batch──► events with ORIGINAL timestamps + backfill=true (rate-limited drain)
   ──► tracking: history/trip-replay only — live map & geofences ignore (jt808 rule #3)
```

---

## 15. Database & Storage Ownership (no dual ownership, anywhere)

| Store | Owner (sole writer) | Contents |
|---|---|---|
| Business MySQL — iam, organization tables | respective contexts | (already implemented) |
| Business MySQL — `vehicles`, `devices`, `cameras`, `device_assignments`, [PROPOSED] `device_inventory`, [PROPOSED] firmware tables | `fleet_device` | Device/vehicle identity, lifecycle, bindings |
| Business MySQL — `vehicle_positions` (partitioned), geofence events, trip summaries | `tracking` (its broker consumer) | Position truth. **JT808 never writes it** (ADR-808-4) |
| Business MySQL — `video_sessions`, `playback_requests` | `video` | Control metadata only |
| Business MySQL — notifications, billing, reporting, `audit_entries` (append-only) | respective contexts | per Database Design |
| Business MySQL — `outbox` | every business module writes via UoW; relay reads | Backend LLD §10 |
| **JT808 local store** (own schema/instance — never the business DB) | JT808 service | its own outbox, durable session mirror, optional raw-frame audit (ADR-808-2) |
| **Device-plane Redis** (separate instance from any business Redis) | JT808/JT1078 services | sessions, latest positions, cmd correlations, alarm dedupe, registry projection, stream registry, port leases, token cache, concurrency counters — all reconstructable hot state |
| **Object store** [PROPOSED — one ADR] | Evidence Ingest (writes); Business API (mints read URLs) | AI evidence snapshots/clips, firmware artifacts. Encrypted, TTL'd, audited |
| Broker | shared **infrastructure** — topics have exactly one producer-side owner each | the inter-plane contract |
| Shared infrastructure (no data ownership) | — | observability stack, secrets manager, LBs |

**Read-model corollary:** any data a plane needs from the other arrives as an event-fed projection
it owns locally (device registry in device-plane Redis; `trip:active` and device-status in the
business plane). Projections are disposable and rebuildable; the emitting context's tables remain
the only truth.

---

## 16. Scalability

### 16.1 The load model

| Tier | Buses | Conns | Position msg/s (10 s cadence) | GPS points/day | Concurrent video |
|---|---|---|---|---|---|
| T1 | 100 school / ~1,000 | 1k | ~100 | ~4–8 M | tens |
| T2 | 10,000 | 10k | ~1,000 | ~40–80 M | hundreds |
| T3 | 100,000 | 100k | ~10,000 sustained; **30–50k burst** | ~0.4–1 B | thousands |

Bursts dominate the design, not averages: morning ignition storms (thousands of near-simultaneous
reconnects) and backfill floods after regional cellular outages.

### 16.2 JT808 tier scaling

- Nodes: async TCP comfortably holds 20–50k idle-ish conns/node ⇒ T1 = 2 small nodes (HA),
  T2 = 2–3, T3 = 4–8 + headroom. Sticky TCP LB; Redis session registry makes nodes
  interchangeable; `shard:{terminal_id}` routes cross-node downlink (all approved).
- **Storm controls:** accept-rate limiting + auth backoff on reconnect storms; per-session
  backfill drain rate limit; jittered device retry (set via 0x8103 where the vendor honors it).
- Redis: single HA pair through T2; Redis Cluster (hash by terminal_id) at T3.

### 16.3 Event backbone

- `device.position_reported` partitioned by `vehicle_id` (ordering per vehicle preserved,
  consumers scale horizontally — Phase 3.4 §13).
- T1 works on any broker; **T3 is Kafka-shaped territory** (10k+/s sustained, replayable firehose,
  consumer groups). The broker is still an open Phase-2 item — see §18, decision 1: choosing it is
  **prerequisite zero** for the device plane.
- Consumers batch-insert positions (N-hundred-row batches) — single-row inserts die at T2.

### 16.4 Position storage

Monthly RANGE partitions + 90-day raw retention (database rule #6) keep MySQL viable through T2
(40–80 M rows/day is already demanding — batch inserts + partition pruning mandatory). **At T3,
MySQL for raw positions is the wrong tool**: the approved TSDB seam (Phase 2 §10.3) must be
exercised — same consumer, different sink; trip summaries/geofence events stay in MySQL. Plan the
migration during T2, not at T3.

### 16.5 Media tier

Bandwidth, not CPU, dominates (repackage-not-transcode). Sub-stream ~0.5–1.5 Mbps ⇒ 1,000
concurrent ≈ 1–3 Gbps egress: a small autoscaled pool of media nodes; port-pool per node; session
manager places new sessions on least-loaded node. Ceilings (per-org + global) are the cost-control
backstop (ADR-1078-6) — raise them consciously, never remove them. T3 with thousands of streams ⇒
regional media POPs (device pushes to nearest ingest; viewers edge-served); WebRTC TURN capacity
planned explicitly (TURN relay ≈ another full copy of the stream).

### 16.6 Business API / WS fan-out

WS tracking fan-out moves through Redis pub/sub across API replicas (Phase-2 shape); notification
workers scale by queue depth; per-org fan-out sharding at T3.

---

## 17. Future Extensions (and why they don't force redesign)

**The stable seams are the canonical event contracts and the ACL adapter pattern** — never the
wire protocols. Anything that can be normalized into (position | alarm | telemetry-metric |
media-meta | command-result) plugs in without touching consumers.

| Extension | How it lands | What changes / what doesn't |
|---|---|---|
| Dashcams (non-MDVR, often proprietary/HTTP) | New vendor adapter if JT808-speaking; if not, a **sibling gateway service** publishing the *same* canonical events | Consumers unchanged; new deployable behind the same broker contract (needs its own mini-LLD + ADR) |
| Electric buses (SoC, range, charging) | New telemetry family `VehicleMetricReported {metric, value, unit}` via vendor ACL (0x0900 transparent data or vendor ext) | New reporting/monitor read-models; device plane core untouched |
| Generic IoT sensors (temp, door, fuel) | Same `VehicleMetricReported` envelope; if sensors are not wired through the MDVR, an **MQTT gateway sibling service** (ADR when real) | Same |
| OBD / CAN bus | CAN frames arrive via MDVR passthrough (0x0900) or vendor ext; a **CAN decode adapter** (per vehicle make DBC) inside the ACL layer | Decode tables are config/adapters, not core |
| Fuel sensors | `VehicleMetricReported {metric=fuel_level}` + a derived business alarm (possible theft) in the business plane | Alarm derivation is business-plane, per §10's rule |
| Temperature sensors | Same pattern | Same |
| Driver tablets | **Business-plane clients** (JWT, REST/WS — a driver-app surface), *not* device-plane devices. They authenticate as users, not terminals | No device-plane change at all |
| Platform-side AI (video analytics in cloud) | New analytics deployable consuming media/evidence via its own tap; publishes the same alarm taxonomy | Explicitly out of MVP; own ADR series |

Two disciplines keep this true: **(1)** every new input family gets a canonical event type with a
versioned schema (API Contracts §13 envelope) before any adapter is written; **(2)** vendor code
never crosses the ACL — the day a vendor constant appears in a consumer, the seam is broken.

---

## 18. Risks, Challenged Assumptions, and Pre-Implementation Gaps

### 18.1 Gaps in the current (implemented + approved) architecture that would hurt JT808/JT1078 integration — fix before Phase 7

| # | Gap | Why it bites | Action |
|---|---|---|---|
| G1 | **Broker not chosen** (Phase-2 §4.3 open item; `RAAD_BROKER__URL` empty; `OutboxPublisher` unbound) | The entire uplink boundary rides on it; retrofitting a broker choice after gateway code exists means rework of publisher/consumer semantics (ordering, partitioning, redelivery) | Decide now. If T2+ roadmap is real: Kafka-compatible (Kafka/Redpanda). If T1-only for 2 years: NATS JetStream / Redis Streams acceptable with a documented migration seam. **ADR required** |
| G2 | **Outbox relay + broker consumers don't run yet** (business plane has an outbox and a relay design, but no live relay/consumer loop; `InMemoryIdempotencyStore` is process-local) | Tracking consumer is the first real consumer; idempotency must be Redis/DB-backed before more than one worker exists | Build relay + consumer harness + durable idempotency as the first device-plane-adjacent phase |
| G3 | **`devices.organization_id NOT NULL` vs pre-tenant inventory** | Factory/warehouse stock unrepresentable | §3.5 ADR (`device_inventory`) |
| G4 | **No object storage anywhere in the approved design** | AI evidence, snapshots, firmware artifacts all need one | One ADR covering store choice, encryption, TTL, signed-URL access, audit (§12.3) |
| G5 | **`devices` schema lacks IMEI/ICCID/SN columns** | SIM-swap detection (§7), RMA/warehouse flows | Additive migration, note in ADR with G3 |
| G6 | **RBAC PermissionEvaluator + ScopeResolver still unbound** (known, pre-existing) | Command authority (§9) and video authority are permission-matrix decisions; device-plane work will immediately hit this wall via `require_permission` | Approve the RBAC matrix before or alongside device-plane phases |
| G7 | **Redis not provisioned** (`RAAD_REDIS__URL` empty) | Session registry, projections, dedupe, stream registry — all Redis | Provision per-plane instances (business vs device — §15) |
| G8 | **No schema-registry/versioning discipline for events yet** | The position firehose is the first event whose schema will be consumed by code you can't atomically deploy with | Adopt event-versioning rules (additive-only within `version`; new `version` for breaking) before the first device event ships |
| G9 | **Time honesty across vendors** | JT808 BCD timestamps are frequently device-local (often UTC+8 defaults); one vendor lying about timezone corrupts trip history silently | Make timezone normalization a mandatory, per-vendor-tested ACL concern; reject/flag positions with implausible clock skew (> tolerance vs server time, unless backfill) |
| G10 | **MySQL-for-positions has a T2 ceiling** | §16.4 | Exercise the TSDB seam during T2 planning, not at T3 panic |

### 18.2 Requested capabilities that conflict with approved rules (restated for visibility)

| Item | Conflicts with | Disposition |
|---|---|---|
| Cloud recording | jt1078 rule #2, ADR-1078-1 | Keep rule; evidence-clips-only variant via ADR (§11.3) |
| Engine cutoff | Safety posture; regulatory exposure | **Will-not-implement ADR recommended** (§9.6) |
| Unknown person / face ID | Minors' biometrics; no legal charter | **Defer** (§12.5) |
| Intercom | No approved client surface; flutter rule #3 adjacency | Design seam only; defer build (§6.2) |
| Counter-driven “child boarded” notifications | Correctness (counts ≠ identity); D1-class scope discipline | Forbidden without new approval (§12.4) |

### 18.3 Challenged assumptions (Principal-Engineer notes)

1. **“AI MDVR” marketing ≠ one protocol.** Vendors ship JT808 cores with mutually incompatible AI
   extensions. The ACL is not an abstraction nicety — it is the survival mechanism. Budget real
   per-vendor certification (a test harness with recorded frame corpora per vendor/firmware) as a
   first-class deliverable, or vendor #2 will cost more than the platform.
2. **Don't build for 100k buses now — build the seams.** T3 changes the storage engine (G10), the
   broker tier, and adds media POPs; it does not change a single contract in this document if the
   seams (canonical events, ACL, projection pattern, signaling API) are respected. Premature T3
   infrastructure would violate the no-premature-microservices rule in spirit.
3. **The MDVR-as-sole-video-archive posture is a business risk, not just a technical rule.** When
   an incident happens and the SD card is dead, “we never stored video” must be a deliberate,
   documented, org-acknowledged trade-off. The `storage failure` alarm + §11.3's decision table
   exist to make that trade-off honest.
4. **Backfill will be your first production fire.** Regional cellular outage → thousands of
   devices reconnect and dump hours of buffered 0x0704 simultaneously. The rate-limited drain +
   `backfill=true` discipline (already approved) must be load-tested (testing rule #5), not just
   implemented.
5. **The projection (§3.4) is the boundary most likely to be “shortcut” under deadline** — someone
   will propose “just let JT808 read the devices table, it's one query.” That query is the first
   crack in plane isolation (credentials, coupling, migration lockstep). The rebuild-from-events
   path must exist from day one so the shortcut is never the easy path.

### 18.4 Recommended implementation sequencing (post-adoption)

```
Phase A  Broker ADR + relay/consumer harness + durable idempotency        (G1, G2)
Phase B  fleet_device context: domain/app/infra/API + inventory ADR      (§2.2, §3, G3, G5)
Phase C  Device registry projection + signaling API skeleton (D6 seam)   (§3.4, §13)
Phase D  JT808 service core: TCP/framing/auth/session/heartbeat/0x0200   (Phase 3.4)
         + tracking consumer + live map read path
Phase E  Alarms (standard bits) + commands (restart/params/text) + audit (§9, §10)
Phase F  JT1078 live video (web, Org Admin) + ceilings + audit           (Phase 3.5)
Phase G  Playback; AI-alarm ACL + Evidence Ingest (needs G4 ADR)         (§6, §12)
Phase H  Firmware/OTA campaigns (needs ADR); counting + derived alarms   (§9.5, §12.4)
```

Each phase lands behind the existing workflow rules (design-first, verify, commit, review).

---

## 19. Glossary (delta to the approved ubiquitous language)

**Terminal** — the JT808-speaking unit on the bus (the MDVR). **Terminal ID** — its wire identity
(§7). **Uplink/Downlink** — device→platform events / platform→device commands. **ACL** —
anti-corruption layer of vendor adapters in the parser. **Projection** — an event-fed, disposable
local read-model (§3.4). **Sub-stream/Main-stream** — JT1078 low/high-bitrate encodings of the same
camera. **Evidence** — alarm-attached snapshot/clip files (§12.3). **Backfill** — buffered data
re-sent after reconnect, time-honest and live-excluded.

---

*End of Device Plane Architecture v0.1 (DRAFT). Design documentation only — no implementation
code, models, endpoints, or migrations. Adoption path: review → resolve §18.2 conflicts + §0
decisions → record ADRs (`docs/architecture/adr/`) → then implementation phases per §18.4.*
