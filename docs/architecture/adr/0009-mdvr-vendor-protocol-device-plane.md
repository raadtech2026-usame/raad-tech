# ADR-0009: Device Plane Terminates the Procured MDVR's Proprietary Protocol Directly

## Status
Accepted (Decision Point 1 of `docs/vendor/HARDWARE_INTEGRATION_PLAN.md`, resolved). Supersedes
the implicit JT/T 808 / JT/T 1078 wire-protocol assumption in `CLAUDE.md`'s "Core Technical
Domains" section and in `.claude/rules/jt808.md`/`.claude/rules/jt1078.md` for the currently
procured hardware only — see Consequences below for exactly what those documents still govern
and what they no longer describe correctly.

## Context
`docs/vendor/HARDWARE_ANALYSIS.md` establishes, tracing only to the vendor's own documentation
(`mdvrdocs/`), that the procured hardware (Shenzhen Tianyou Security Technology Co., Ltd, brand
"LSZ", model `LSZ-C5804DG-Q-F`) does not implement JT/T 808 or JT/T 1078 at all. It implements a
proprietary ASCII/binary protocol (internally called "mdvr网络通信协议" by the vendor) with a
different frame delimiter, a different message-identity scheme (ASCII keyword vs. binary message
ID), no checksum/escaping mechanism, and a different media-streaming transport. This is confirmed
against the codebase, not just the vendor documents: `services/jt808/`'s already-built, tested
Phase 9.1–9.6 implementation (real JT/T 808-2013 frame escaping, XOR checksum, BCD header
decoding, `0x0100`/`0x0102`/`0x0200`/`0x0704` handlers) cannot parse a single frame this hardware
actually sends.

`docs/vendor/HARDWARE_INTEGRATION_PLAN.md` §Decision Point 1 laid out two structurally different
integration architectures (Option A: RAAD terminates the vendor protocol directly in its own
device-plane deployable; Option B: RAAD integrates against the vendor's own CMS server product via
its Web Service/SDK/ActiveX/DB/OA-push surfaces) without choosing between them, since the choice
"permanently affects the platform" per `.claude/rules/workflow.md` #1's own framing for
consequential decisions.

## Decision
**Option A.** RAAD's device plane terminates this vendor's proprietary protocol directly, in a
RAAD-owned, RAAD-operated deployable — not via the vendor's CMS server.

- `.claude/rules/architecture.md` #2's "device connectivity is a separate plane... independent
  deployables" and #3's "the device plane communicates with the business plane exclusively
  through asynchronous domain events over the broker" remain the architecture, unchanged. What
  changes is only *which wire protocol* that deployable terminates, not the deployable boundary,
  the event-only communication rule, or the domain event contract
  (`DevicePositionReported`/`DeviceOnline`/`DeviceOffline`/`DeviceAlarmRaised`) any of it
  publishes.
- `.claude/rules/jt808.md` #2 already establishes the right *principle* for this — "vendor dialect
  variation is isolated in an Anti-Corruption Layer... a new vendor means a new adapter, never a
  change to the core parser/dispatcher/handlers" — this decision applies that same principle at a
  coarser grain than originally written for: not a dialect variation *within* JT/T 808 framing,
  but a full protocol swap, isolated the same way. The "core" that stays untouched is redefined
  as the parts of `services/jt808/` that were always protocol-agnostic by construction
  (`connection/`'s transport lifecycle, `session/`'s `DeviceSession`/`DeviceSessionRegistry`/
  `DeviceSessionManager`, `events/`'s `DevicePositionReported` shape and `EventPublisher` port) —
  none of which reference JT/T 808 wire format at all, confirmed by reading each module's source
  directly, not assumed. Only `protocol/` (framing/escaping/checksum/header/parser/encoder),
  `dispatcher/`'s `message_id`-keyed registry, and `handlers/`'s JT/T-808-body-specific parsers are
  JT/T-808-specific — those are what get a parallel, vendor-specific implementation, not a
  patched "dialect" on top of the existing one.
- **`services/jt808/`'s existing Phase 9.1–9.6 JT/T 808 implementation is kept, untouched, not
  deleted.** It is real, tested code against a real national standard this platform may still
  need if a future vendor's hardware genuinely is JT/T 808-compliant (`architecture.md` #6/#7:
  RAAD's bounded contexts and deployables are not casually multiplied, but this is the *same*
  deployable gaining a second protocol adapter, not a new one). Deleting working, tested code
  because the *first* procured vendor doesn't need it would be a real loss with no benefit —
  `.claude/rules/workflow.md`'s own "don't take destructive shortcuts" spirit applies here even
  though this is a design decision, not a git operation.
- **One small, additive change to previously "pure" transport code is required and accepted**:
  `connection/connection.py`'s `Connection` class hardcoded its own `protocol.framing.FrameBuffer`
  internally — the one place the "protocol-agnostic by construction" claim in that file's own
  docstring didn't quite hold. Fixed by making the frame decoder an injectable constructor
  parameter (defaulting to the existing `FrameBuffer`, so every existing caller/test is
  byte-for-byte unaffected), the same dependency-injection pattern that file already uses for
  `on_frame`/`on_activity`/`on_close`. This is the *only* change to any existing file this decision
  requires.
- The new vendor-specific implementation lives in a new sibling package,
  `services/jt808/src/vendors/lsz_mdvr/`, with its own `protocol/`, `dispatcher/`, and `handlers/`
  — mirroring the existing package shape exactly, so the two protocol stacks read as structurally
  equivalent, swappable adapters rather than one being a special case bolted onto the other.
  `DeviceSession`/`DeviceSessionRegistry`/`DeviceSessionManager`/`ConnectionManager` are reused
  unchanged from the parent package — `DeviceSession.terminal_id` is reused as the generic
  "device-identity session key" field it already was designed to be (this vendor's "vehicle
  device serial number" fills that same role; no rename, no duplication).

## Options Considered

### Option A — RAAD terminates the vendor protocol directly (chosen)
See Decision above. Full reasoning and tradeoffs in `docs/vendor/HARDWARE_INTEGRATION_PLAN.md`
§Decision Point 1.
- **Pro:** Preserves `architecture.md` #2/#3 exactly; RAAD retains full control of both GPS and
  (later, B3) video; no foreign operational dependency.
- **Con:** RAAD must implement the vendor's registration/heartbeat/position/alarm protocol from
  scratch, including a GPS-encoding normalization layer and a network-layer compensating control
  for the protocol's complete absence of device authentication (Hardware Analysis §11).

### Option B — Integrate via the vendor's own CMS server
- **Con (decisive):** Every viable sub-option carries a disqualifying cost — the Web Service is
  REST-polling-only and GPS-only; the OA-push channel is push-based but still GPS-only and
  requires operating a third-party Windows-oriented CMS server, a class of dependency nowhere
  else in this stack; the Windows SDK/ActiveX control are non-starters for a Python/asyncio
  service without their own ADR-worthy precedent; direct database access couples to an
  undocumented foreign schema, a tighter coupling than `.claude/rules/backend.md` #3 already
  forbids RAAD's own modules from doing to each other. No sub-option offers a video path at all.
  Rejected in full — not one sub-option addresses both GPS and video with an acceptable
  operational/architectural cost.

## Consequences
- **`CLAUDE.md`'s "Core Technical Domains" section and `.claude/rules/jt808.md`/
  `.claude/rules/jt1078.md` remain the architecture's *target*/*default* framing for device-plane
  work in general** (a future genuinely-JT/T-808-compliant vendor would still be built exactly as
  those documents describe) **but no longer describe the currently-integrated hardware.** Both
  rule files are annotated (not rewritten) to point here.
- **A second, currently-unresolved decision from the Integration Plan remains open**: the
  disposition question of whether `services/jt808/`'s dormant JT/T 808 code should ever be
  actively maintained alongside the new vendor adapter, or left purely as reference/optionality.
  This ADR answers "keep, don't delete" — it does not commit to any future maintenance obligation
  for the dormant code.
- **B1 (JT808 Provisioning Bridge)'s originally-planned scope is revised, not implemented
  verbatim**: `devices.auth_key_hash`/`DeviceProvisioningPort.verify_auth_code` assumed a
  credential this protocol does not have (Hardware Analysis §11) — the vendor-specific
  provisioning port authorizes registration by serial-number allow-list only, with the missing
  cryptographic assurance shifted to network-layer compensating controls
  (`.claude/rules/security.md` #9), a design gap this ADR records as accepted-and-flagged, not
  silently closed.
- **A GPS-coordinate-normalization Anti-Corruption Layer is a new, permanent piece of this
  deployable** — the vendor's own protocol is internally inconsistent about coordinate encoding
  (Hardware Analysis §5), and neither encoding matches JT/T 808's signed-integer convention either,
  so this layer exists regardless of what a future JT/T-808 vendor might additionally need.
- **`fleet_device`'s `device_registered` domain event payload needs a small, additive field
  addition (`serial_number`, alongside the already-present `terminal_id`)** for a future
  device-registry projection (consumed by this new deployable) to resolve a vendor serial number
  back to `{device_id, organization_id, vehicle_id}` — discovered while implementing this ADR;
  tracked as its own follow-up, not bundled silently into an unrelated change.

## Verification
- `services/jt808/tests/test_mdvr_*.py` (new): frame boundary detection, message parsing against
  the vendor documents' own worked examples verbatim, GPS coordinate normalization, registration/
  heartbeat/position handler behavior — mirroring the existing `test_framing.py`/`test_parser.py`/
  `test_position_body.py` conventions exactly (stdlib `unittest`, no new test dependency).
- Existing `services/jt808/tests/test_framing.py`/`test_*` for the JT/T 808 stack are unaffected
  (the one shared-file change, `Connection`'s injectable frame decoder, defaults to the existing
  `FrameBuffer` and changes no existing behavior).

## References
- `docs/vendor/HARDWARE_ANALYSIS.md`
- `docs/vendor/HARDWARE_INTEGRATION_PLAN.md` (§Decision Point 1, §11 Conflicts, §12 Required
  refactoring)
- `.claude/rules/architecture.md` #2, #3
- `.claude/rules/jt808.md` #2, #4, #5
- `.claude/rules/security.md` #9
- `.claude/rules/workflow.md` #1, #2, #7
- `services/jt808/README.md` (Phase 9.1–9.6 status, unchanged by this ADR)
