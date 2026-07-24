# Hardware Integration Plan — MDVR (Shenzhen Tianyou / "LSZ") vs. RAAD Architecture

**Status:** Planning/analysis only when written. **Since implemented** — Decision Point 1 below
was resolved as ADR-0009, and the device-plane deployable this document calls `services/jt808/`
throughout was subsequently renamed `services/device-gateway/` and reorganized into
`src/vendors/{jt808,lsz,...}/` (ADR-0010). Every `services/jt808/` path reference below is
historical (accurate when this document was written, before either ADR), not current — see
ADR-0009/ADR-0010 for what was actually built.
**Depends on:** `docs/vendor/HARDWARE_ANALYSIS.md` (read that first — every finding below traces
back to a specific section there).

This document compares the actual, documented hardware capability against RAAD's existing,
approved architecture (`CLAUDE.md`, `.claude/rules/*.md`, `docs/business/`, `docs/architecture/
frontend-flutter-master-roadmap.md`) and RAAD's actual current codebase (`services/jt808/`,
`services/jt1078/`, the ten completed backend bounded contexts). Per `.claude/rules/documentation.
md` #2, every conflict found is recorded explicitly rather than silently resolved. Per
`.claude/rules/workflow.md` #8, no business logic or implementation is proposed here — only the
comparison, the gaps, and the decisions that need sign-off before any code is written.

---

## 0. The central finding, and the decision it forces

**`docs/vendor/HARDWARE_ANALYSIS.md` §2 establishes that the procured hardware does not speak
JT/T 808 or JT/T 1078 at all.** It speaks a proprietary vendor protocol. This single fact is the
root of nearly every item in this document, so it is stated once here rather than repeated at each
affected section below.

This directly conflicts with:

- `CLAUDE.md`'s "Core Technical Domains" section, which names JT808/JT1078 as "first-class
  architectural concerns" for "most real-time tracking and live video features in this codebase."
- `.claude/rules/architecture.md` #2 ("Device connectivity is a separate plane. JT808
  (`services/jt808/`) and JT1078 (`services/jt1078/`) are independent deployables").
- `.claude/rules/jt808.md` and `.claude/rules/jt1078.md` in their entirety — both rule files assume
  compliance with the named national standards throughout.
- The **already-built, tested** `services/jt808/` code (Phases 9.1–9.6 per its own `README.md`):
  real JT/T 808-2013 frame escaping, XOR checksum, BCD header/terminal-phone decoding, and handlers
  for message IDs `0x0100`/`0x0102`/`0x0200`/`0x0704`. None of this can parse a single frame this
  hardware actually sends.

This is not a gap that can be silently patched with a "vendor dialect" adapter as
`.claude/rules/jt808.md` #2 already anticipates for *ordinary* vendor variation — that rule assumes
variation *within* JT/T 808 framing (e.g. an extra alarm field, a nonstandard bit meaning). What was
found here is a completely different frame delimiter, a completely different message-identity
scheme (ASCII keyword vs. binary message ID), a completely different checksum/escape mechanism (none
vs. XOR/`0x7e`-escaping), and a completely different media-streaming transport. Treating this as an
"adapter" would misrepresent the size of the change to anyone reading `jt808.md`'s ACL rule later.

**This forces a decision only the user/stakeholders can make, before any further design or code:**
see Decision Point 1 below.

---

## Decision Point 1 — Where does RAAD terminate this hardware's protocol?

`docs/vendor/HARDWARE_ANALYSIS.md` documents two structurally different integration surfaces:

**Option A — RAAD terminates the device protocol directly** (a new/replaced device-plane
deployable speaking the vendor's own `$$dc`/`@@$$dc` socket protocol, publishing the same domain
events `services/jt808/` already contracts with `tracking` today).

- Matches `.claude/rules/architecture.md` #2/#3 exactly: device connectivity stays a separate
  deployable, communicating with the business plane only via broker events — no change to that
  principle, only to what sits inside the device-plane deployable.
- RAAD fully owns and controls the integration; no dependency on a third-party server being
  deployed and kept alive somewhere.
- Cost: RAAD must implement the vendor's registration/heartbeat/position/alarm/media protocol from
  scratch (§9, §6 of the Hardware Analysis), including a GPS-encoding normalization layer and a
  network-layer compensating control for the complete absence of device authentication (§11).
- The binary media-channel opcode family (`0x60xx`/`0x64xx`) is under-specified in the vendor's own
  documents (worked examples only, no formal field layout) — implementing live video under this
  option carries real reverse-engineering risk and may need direct vendor clarification.

**Option B — RAAD integrates against the vendor's own CMS server** (`GPS数据获取.docx`'s Web
Service / SDK / ActiveX / DB / OA-push surfaces), i.e. the vendor's CMS software sits between the
buses and RAAD.

- The **Web Service** (HTTP+JSON polling) is the easiest to consume from RAAD's existing Python
  stack, but is GPS-only, poll-based (conflicts with `.claude/rules/frontend.md` #3's "real-time
  data goes over WebSocket, not REST polling" spirit for the *ultimate* data path, even though this
  specific hop is server-to-server), and carries no video or alarm surface at all.
- The **OA-push channel** (CMS-initiated outbound connection using `OAPacketHead_S`/
  `GPSVehicleState_S`) is push-based and fits the event-driven spirit better, but is also GPS-only,
  and requires a **third-party Windows-oriented CMS server to be stood up and operated somewhere**
  — a new, foreign operational dependency this platform has nowhere else in its stack (the entire
  backend, both device-plane services, and both mobile/web frontends are Python/TypeScript/Dart;
  nothing here today runs on Windows).
- The **Windows SDK and ActiveX/COM control** are non-starters for this stack outright: ActiveX is a
  legacy Windows-only COM technology with no Linux/cross-platform story, and adopting either would
  mean embedding a Windows-only native client inside an otherwise cross-platform Python service — a
  precedent with no analog anywhere else in this codebase, and one that would need its own ADR even
  to consider.
- Direct **database table access** (`dev_status`) is explicitly not recommended under any
  circumstance: it is schema-coupling to a foreign vendor's live production database with no
  documented support/versioning guarantee — a tighter, riskier coupling than `.claude/rules/
  backend.md` #3 already forbids RAAD's *own* modules from doing to each other.
- Under Option B, no video-session control exists at all — `GPS数据获取.docx` never describes the
  CMS relaying video to a third party, only position data. Video (C6)'s already-abstract
  `VideoProviderPort` would remain unbuildable against this vendor regardless.

**Recommendation (not a decision — flagging per `.claude/rules/workflow.md` #1):** Option A is the
better architectural fit — it preserves `architecture.md` #2/#3 as written, keeps RAAD in control of
both GPS and video, and introduces no foreign Windows dependency. Option B's only real advantage is
short-term implementation speed for GPS-only tracking, at the cost of a materially different
risk/ownership posture than this codebase's architecture docs assume, and it does not solve Video at
all. **This document does not choose for you — this is exactly the kind of decision
`.claude/rules/workflow.md` #7 requires stopping for.**

The remainder of this document is written primarily against **Option A** (since it requires the
deeper backend changes and is the recommended path), with Option B's deltas called out inline
wherever they'd materially differ.

---

## 1. Backend changes

- **A new (or heavily reworked) device-plane deployable** implementing the vendor's ASCII/binary
  protocol: signaling-channel registration (`V101`)/heartbeat (`C501`/device heartbeat)/position
  report (`V114`) parsing, the alarm family (§8 of the Hardware Analysis), and — if video is in
  scope for this phase — the media-channel opcode family (§6, §9).
- **A GPS-normalization Anti-Corruption Layer step**, mapping the vendor's two internally
  inconsistent coordinate encodings (integer D°M′S″ in position reports, decimal-degree float
  strings in geofence-alarm context — Hardware Analysis §5) into whatever single decimal-degree
  representation `tracking`'s `RecordVehiclePositionCommand` already expects. This is in addition
  to, not instead of, the already-flagged `latitude/longitude` vs. `lat/lng` naming reconciliation
  the roadmap's B2 phase already names — that reconciliation is still needed regardless of which
  device protocol produces the event.
- **No change required inside `tracking`, `notifications`, `/ws/tracking`, or `/ws/notifications`**
  — all four already consume `DevicePositionReported`/domain events at the event-shape level, not
  the wire-protocol level; as long as the new/reworked device-plane service publishes the same
  event contract, none of these four need to know a different vendor is now upstream.
- **`fleet_device`'s domain model needs no schema change for device identity** — `devices.imei` and
  `devices.serial_number` (both nullable, globally unique, added in the Device Domain Overhaul per
  CLAUDE.md) already map cleanly onto this vendor's IMEI field and "vehicle device serial number"
  field respectively. This is a genuine point of existing compatibility, not a gap — worth noting
  explicitly since most of this document is gap-finding.
- **`fleet_device`'s planned B1 provisioning-bridge design needs revision, not just implementation**
  — see Conflict #4 below.
- **A concrete `VideoProviderPort` adapter becomes designable for the first time** against this
  vendor's actual media-channel protocol (Option A) or CMS surface (Option B, though B offers none)
  — today it is deliberately unbound/abstract per CLAUDE.md's Video (C6) entry; this hardware
  analysis is the first concrete input to that design. This is a positive unblock, not a new gap.
- **No changes needed to any of the other seven bounded contexts** (iam, organization,
  transport_ops, billing, reporting, platform_audit) — none of them touch device-plane protocol
  detail directly.

## 2. Frontend changes

**None required as a direct consequence of this hardware analysis.** `/ws/tracking` and
`/ws/notifications` are consumed by the frontend at the already-documented wire-frame level (API
Contracts §11), which does not change based on which device protocol produces the underlying
events. Phase F7 (Live Monitoring & Maps) and Phase F10 (Video) both remain scoped exactly as the
master roadmap already describes them — this analysis affects what backs those phases, not their
frontend contract. The one indirect effect: F7's "no live data source connected" honest-placeholder
state (already planned per the roadmap) will likely persist longer than if the hardware had turned
out to be JT/T 808-compliant out of the box, since more backend integration work is now needed
first (see §9, Required refactoring).

## 3. Database changes

- **No new tables appear strictly required** for the core tracking/video path — `vehicle_positions`,
  `devices`, `video_sessions` already have the columns needed once GPS values are normalized to
  decimal degrees at the ingestion boundary (a mapping concern, not a schema concern).
- **Possible, not required:** if RAAD wants to surface the vendor's read-only SIM/cellular-traffic
  counters (Hardware Analysis §16) or hardware-alarm history (§8) as a product feature, new storage
  is needed — but no such feature is approved yet (see §7, Missing features, and §8, Conflicts).
  `fleet_device`'s own `Integration` entity and `device_status_log` table are already flagged in
  CLAUDE.md as "documented-but-not-built" for unrelated reasons — either could plausibly host this,
  but that is a product decision, not one this document makes.
- **Verify, don't assume:** whether the existing `devices.terminal_id` column (added earlier,
  seemingly modeled after a JT/T 808-style terminal identity) is the right home for this vendor's
  "vehicle device serial number," or whether `devices.serial_number` (added in the Device Domain
  Overhaul) is the correct field instead, should be confirmed against `fleet_device`'s actual domain
  code before any device-plane service is wired to write to it — not asserted here without reading
  that code in this pass.

## 4. API changes

- **No changes needed to any existing `/api/v1` REST contract.** This entire integration is
  internal to the device plane and its published events (`.claude/rules/architecture.md` #3);
  nothing here adds or changes a business-plane HTTP endpoint.
- **One existing, already-flagged gap becomes newly relevant, not newly created:** `fleet_device`'s
  `RegisterCameraCommand` has no HTTP route yet (CLAUDE.md's own flagged gap, and the master
  roadmap's B3 sub-phase already names closing it). Actually onboarding this hardware's cameras
  needs that route to exist — this raises B3's priority relative to B1/B2, it does not add new API
  surface beyond what B3 already planned.

## 5. Device lifecycle

`fleet_device`'s existing device lifecycle (register → activate → assign/reassign/unassign) is
orthogonal to the wire protocol and needs **no change** — it already models "a device exists and is
associated with a vehicle" independently of how that device talks to the platform. What changes is
only the *signal* that drives online/offline detection: previously implicitly assumed to be JT/T
808 registration (`0x0100`) + heartbeat; now driven by this vendor's `V101` registration + its own
heartbeat mechanism instead. The already-flagged, still-open "`AUTHENTICATED → ONLINE` transition
trigger" item in `services/jt808/README.md` remains conceptually identical — it just needs to be
re-anchored to this vendor's actual wire messages if Option A is chosen, inside whichever service
ultimately owns that logic.

## 6. Provisioning workflow

Per Hardware Analysis §12, this vendor's provisioning is **entirely center-side and out-of-band**:
a device only ever becomes reachable after its serial number is manually entered into whichever
system terminates the protocol (RAAD's own new service, under Option A). This actually matches
`fleet_device`'s existing `POST /devices` registration flow reasonably well **in spirit** — an
operator registers a device in RAAD first, and only a subsequently-connecting physical unit
presenting that same serial number is accepted. What must change is the **mechanism** by which the
device-plane service learns which serial numbers are valid: the master roadmap's B1 phase already
anticipated exactly this shape ("a local device-registry projection kept current by consuming
`fleet_device`'s own already-emitted `DeviceRegistered`/`DeviceActivated`/`DeviceAssignedToVehicle`
events") — that plan does not need to change, only the specific field it keys on (serial number
rather than a JT/T 808 terminal ID) and the specific auth semantics it can enforce, since this
vendor's protocol has none (see Conflict #4 below).

## 7. Tracking workflow

Needs the GPS-normalization step described in §1 above. No change to `tracking`'s own domain
logic, geofence evaluation, `RedisLatestPositionPort`, or `/ws/tracking` fan-out — all of that
operates on the already-normalized `DevicePositionReported` event shape regardless of source
protocol. `trip_id` resolution and backfill (`is_backfill`) classification logic in the device-plane
service can follow the same pattern `services/jt808/`'s `LocationHandler`/`BulkLocationHandler`
already establish (live vs. buffered classification), substituting this vendor's own "drive flag"
field (Hardware Analysis §5: 0 = live poll, 1 = periodic upload, 2 = requested poll, 3 = video-sync)
for JT/T 808's `position_data_type` byte.

## 8. Video workflow

This is where the hardware analysis provides the most genuinely new, concrete input: `VideoProviderPort`
has been abstract since Video (C6) was built ("MVP: a hardware/vendor video API," per CLAUDE.md).
This document does not design that adapter (no implementation yet, per this document's own scope
limit), but records what any future adapter design must account for:

- The mutual-exclusivity constraint (Hardware Analysis §6/§17-#10): live video, file
  playback/download, and firmware upgrade cannot run concurrently on one device's media channel.
  `jt1078.md` #4's "per-org and global max-concurrent-stream ceiling" was written assuming
  concurrency limits *across* devices — it did not anticipate needing to also coordinate *within* a
  single device against non-video operations (a firmware push in progress, a file download in
  progress). This is a real gap in the existing concurrency model's scope, not a bug in it.
- The session/registration handshake (`C508` → `V102` → `0x6000` → `0x6002` → `0x6011`/`0x6012`/
  `0x6013` → `0x6403`) needs to be either terminated directly by a new device-plane service (Option
  A) or is entirely unavailable (Option B has no video path at all, per Hardware Analysis's own
  finding that `GPS数据获取.docx` never mentions video).
- The binary opcode family is under-specified in the vendor's own documents (worked examples only)
  — any adapter built against it carries real implementation risk until confirmed against either
  vendor clarification or live-device packet capture.
- `jt1078.md` #5 ("media is repackaged, never passed through raw... clients never speak JT1078
  directly") remains the right target *shape* regardless of source protocol — the repackaging
  target (WebRTC primary, HLS/FLV fallback) is unaffected; only the *ingest/demux* front end
  (unwrapping this vendor's `0x6011`/`0x6012`/`0x6013` opcodes into raw H.264/H.265 NALUs) is new
  work that `services/jt1078/`'s currently-scaffold-only `ingest/` component would need to account
  for, in place of a JT/T 1078 PS-frame demuxer.

## 9. Alarm workflow

RAAD's only currently-built alarm-adjacent capability is the Notification Worker's D1 catalog
(`trip_started`/`trip_completed`/`approaching_stop`/`arrived_org`) — all **student-transportation**
events, not raw device-hardware events. `DeviceAlarmRaised` is named as an event type the device
plane should publish (`architecture.md` #3, `jt808.md` #1) but **no consumer for it exists anywhere
in the built backend today** — not in `tracking`, not in `notifications`, not in a dedicated
context. This vendor's hardware exposes a rich alarm catalog (Hardware Analysis §8: camera
tampering, hard-disk error, panic button, fatigue, geofence, temperature, fuel-level-change, etc.)
that has no home in any of RAAD's ten bounded contexts today. This is recorded as a **missing
feature** (§10 below), not silently mapped onto an existing context that doesn't fit it — folding
"hard disk error" or "camera tampering" into the Parent-facing `Notification` aggregate, for
example, would conflate a fleet-maintenance/security concern with a parent-facing transportation
update, a scope mismatch worth a real product decision rather than a convenient reuse.

## 10. Missing features

Capabilities this hardware can now support that no current RAAD bounded context has a documented
home for — none of these are implemented or scoped by this document; all require an approved
design before any code, per `.claude/rules/workflow.md` #8:

1. **Device hardware-alarm ingestion, storage, and surfacing** (§9 above).
2. **SIM/cellular-data-usage telemetry** (Hardware Analysis §16) — `fleet_device`'s own
   `Integration` entity is already flagged in CLAUDE.md as undocumented/not built; this is more
   evidence such a capability might eventually belong there, not a decision that it does.
3. **Remote device configuration push/pull** (`C520`/`C521`) — no RAAD concept of remote
   device-configuration management exists in any bounded context today.
4. **Fleet-wide firmware/OTA orchestration** (`V106`) — no RAAD concept of firmware rollout
   management exists today.
5. **Two-way voice intercom** (`C550`/`C551`/`V130`) — never named as a RAAD requirement in the
   Project Brief or any Phase 2/3.x document. This would be a genuinely new product feature
   request, not an extension of an existing one — flagged per `.claude/rules/workflow.md` #8 rather
   than built speculatively.

## 11. Conflicts (explicit list)

1. **CLAUDE.md, `architecture.md` #2, `jt808.md`, and `jt1078.md` all assume this hardware is JT/T
   808- and JT/T 1078-compliant. It is not** (Hardware Analysis §2). This is the primary conflict
   underlying every item in this document.
2. **`services/jt808/`'s existing, tested Phase 9.1–9.6 implementation cannot parse this hardware's
   actual wire format** — the mismatch is at the framing/checksum/message-identity level, not a
   "vendor dialect" `jt808.md` #2's ACL pattern was designed to absorb.
3. **`security.md` #9 and `jt808.md` #5 require device authentication and rejection of
   unauthenticated devices; this hardware's protocol provides no cryptographic mechanism to do
   either** (Hardware Analysis §11). Only network-layer compensating controls (mutual TLS, IP
   allow-listing, DMZ isolation — all already named in `security.md` #9 as generic compensating
   controls) can close this gap; none is designed yet.
4. **The master roadmap's planned B1 (JT808 Provisioning Bridge) scope — specifically exposing
   `devices.auth_key_hash` and implementing `DeviceProvisioningPort.verify_auth_code`** — assumes a
   credential/secret this hardware's protocol does not have. B1 needs to be **redesigned**, not
   simply implemented as originally scoped, once Decision Point 1 is resolved.
5. **The vendor's own GPS coordinate encoding is internally inconsistent** (two different formats
   in two different message types, Hardware Analysis §5) — any normalization layer must handle
   both, and real-device behavior should be confirmed rather than assumed if it ever diverges from
   either documented worked example.
6. **`architecture.md` #2's "independent deployables" principle assumes RAAD builds and owns the
   device-plane service.** Under Option B (§Decision Point 1), the deployable RAAD would actually
   depend on is a foreign vendor's Windows CMS server RAAD does not build, own, or control the
   source of — a materially different risk/ownership posture than that rule was written assuming.

## 12. Required refactoring

In dependency order:

1. **Resolve Decision Point 1** (Option A vs. B) — blocks everything below.
2. **Decide the disposition of `services/jt808/`'s existing Phase 9.1–9.6 work** — keep as dormant
   code for a possible future genuinely-JT/T-808-compliant vendor, or repurpose only its
   transport/connection-lifecycle/session-management scaffolding (which is protocol-agnostic) while
   discarding its JT/T-808-specific parser/escaping/checksum/message-ID layer. This is its own
   decision, not implied by Decision Point 1 alone.
3. **Scaffold (or rework) a device-plane deployable** implementing the vendor's actual protocol,
   publishing the existing `DevicePositionReported`/`DeviceOnline`/`DeviceOffline`/
   `DeviceAlarmRaised` event contract unchanged, so `tracking`, `notifications`, `/ws/tracking`, and
   `/ws/notifications` need zero modification.
4. **Design and implement the GPS-normalization ACL step**, resolving both the D°M′S″-vs-decimal
   inconsistency (Hardware Analysis §5) and the pre-existing `latitude/longitude`-vs-`lat/lng`
   naming mismatch the roadmap's B2 phase already flagged.
5. **Redesign B1's provisioning-bridge scope** to drop the unsupported auth-key/verify-auth-code
   assumption, substituting an explicit network-layer compensating-control design (likely its own
   ADR, given `security.md` #9 already anticipates exactly this class of gap generically).
6. **Design the `VideoProviderPort` adapter** concretely against this vendor's media-channel
   protocol (Option A) — genuinely unblocked by this analysis, a positive outcome — accounting for
   the mutual-exclusivity constraint's cross-cutting effect on `jt1078.md` #4's concurrency-ceiling
   model.
7. **Decide the disposition of each item in §10 (Missing features)** — build, defer, or explicitly
   reject each, per `.claude/rules/workflow.md` #8's "never implement business logic without an
   approved design."

---

## Next step

This document and `docs/vendor/HARDWARE_ANALYSIS.md` are both complete. **No implementation code
has been written.** Per the task instructions, this work now stops and waits for approval —
specifically, Decision Point 1 above needs a decision before any further design or code follows.
