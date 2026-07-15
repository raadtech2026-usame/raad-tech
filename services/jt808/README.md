# JT808 TCP Server

Terminates persistent TCP connections from bus terminals, parses JT/T 808 messages, maintains device
sessions, normalizes telemetry into domain events, and relays platform commands down to devices.
Independently deployable — the Business API never opens a device socket.

Source of truth: `docs/business/RAAD_Phase3.4_JT808_Technical_Design_v1.md`,
`docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §5.1, and — for wire-level packet
structure specifically (Phase 9.3 onward) — the primary JT/T 808-2013 standard
(`JTT808-2013.pdf`, repo root; Chinese-language; 2013 edition only, no JT/T 808-2019
compatibility attempted).

**Language/runtime: Python (asyncio)**, confirmed with the user for Phase 9.1 (no approved
document names one — see git history for the confirmation). `pyproject.toml` declares zero
third-party dependencies; the transport layer uses only the standard library.

## Structure (logical components — see `.claude/rules/jt808.md`)

```
src/
├── connection/   # TCP Acceptor / Connection Manager               [Phase 9.1: implemented]
├── protocol/     # Packet Parser / Framer + vendor Anti-Corruption Layer
│                 #   - frame boundary detection (0x7e)              [Phase 9.1: implemented]
│                 #   - unescape/checksum/header parsing/reassembly  [Phase 9.3: implemented]
│                 #   - message-specific body field decoding (0x0100/0x0102/0x0200/0x0704 only,
│                 #     in src/handlers/ — see below)                [partial, Phases 9.5-9.6]
│                 #   - vendor ACL (dialect normalization)             [not yet implemented]
├── dispatcher/   # Packet Dispatcher — routes by message_id to handlers  [Phase 9.4: implemented]
├── handlers/     # Message Handlers: register, auth, heartbeat, location,
│                 # bulk/backfill location, alarm, command-ack
│                 #   - registration (0x0100 -> 0x8100) and authentication (0x0102 -> 0x8001):
│                 #     real protocol behavior, session binding, reject/fail + close
│                 #     [Phase 9.5: implemented, in src/handlers/]
│                 #   - location (0x0200) and bulk/backfill location (0x0704): body parsing,
│                 #     device/vehicle/org resolution, DevicePositionReported publishing
│                 #     [Phase 9.6: implemented, in src/handlers/]
│                 #   - placeholder (no-op, logs only) for the remaining 4 named message IDs
│                 #     [Phase 9.4: implemented, in src/dispatcher/placeholder_handler.py]
│                 #   - real business logic for heartbeat/alarm/command-ack/logout
│                 #                                                  [not yet implemented]
├── session/      # Session Manager
│                 #   - transport-level ConnectionSession, keyed by connection_id
│                 #     [Phase 9.1: implemented, in-memory only]
│                 #   - device-level DeviceSession, keyed by terminal_id, bound after auth;
│                 #     duplicate-terminal supersede (ADR-808-8); expiration; online/offline
│                 #     lifecycle (AUTHENTICATED/ONLINE/OFFLINE only - no IDLE/BACKFILLING/
│                 #     REGISTERED, which need packet parsing this phase doesn't have)
│                 #     [Phase 9.2: implemented, in-memory only]
│                 #   - node_id / cross-shard command routing / Redis backing store /
│                 #     AUTHENTICATED -> ONLINE `touch()` trigger (still nothing calls it —
│                 #     Phase 9.6's Location handler deliberately does not, see Status below)
│                 #                                                  [not yet implemented]
├── commands/     # Command Executor — downlink (real-time A/V request, playback, config, text)
│                 #                                                  [not yet implemented]
└── events/       # Event Publisher: DevicePositionReported shape + EventPublisher port +
│                 # LoggingEventPublisher default (no real outbox/broker — none approved yet)
│                 #                                                  [Phase 9.6: implemented]
store/            # Local persistent store: outbox, device_session, raw_frame_audit, command_log
│                 #                                                  [not yet implemented]
```

## Key rule

JT808 never writes Business API tables directly — it only publishes domain events
(`DevicePositionReported`, `DeviceOnline`, `DeviceOffline`, `DeviceAlarmRaised`, command-result
events) consumed by the Business API. See `.claude/rules/jt808.md`.

## Status

**Phase 9.1 (Transport Layer): implemented.** TCP server bootstrap (`src/server.py`), async
connection accept/read/write loops and lifecycle (`src/connection/`), JT808 frame boundary
detection — delimiter-only, no unescaping/checksum/field parsing (`src/protocol/framing.py`),
an in-memory, connection-scoped session registry (`src/session/`), and idle-timeout
infrastructure (framework only — tracks "bytes received recently," not JT808 heartbeat
semantics). Verified with a real TCP server, real socket clients, and mocked frames
(`tests/`).

**Phase 9.2 (Session Management): implemented.** `DeviceSession`/`DeviceSessionRegistry`/
`DeviceSessionManager` (`src/session/device_session*.py`) — terminal-identity-keyed sessions
bound after authentication (`create()`, called by a future `AuthHandler`, not built yet),
duplicate-terminal supersede (ADR-808-8: newest authenticated connection wins), reconnect,
expiration (framework only, no protocol-level heartbeat), and online/offline lifecycle. A
documented conflict between Phase 3.4 §21.1's sequence diagram and both approved state-machine
diagrams (Phase 3.4 §3, Phase 2 §21.1) over exactly when a session becomes `Online` was
resolved with the user before implementing (see `device_session_manager.py`'s module
docstring). Verified with real TCP clients wired through the real `Jt808Server` (`tests/`).

**Phase 9.3 (Packet Parser): implemented.** `src/protocol/escaping.py` (unescape, verified
against the primary spec's own worked example), `checksum.py` (XOR verification), `header.py`
(fixed 12-byte header + optional 4-byte subpackage block, BCD terminal-phone decode,
body-attributes bit layout), `reassembly.py` (multi-part message reassembly, bounded +
timeout-evicted), `message.py` (`InboundMessage`), `parser.py` (`PacketParser`, orchestrating
all of the above in the spec-mandated unescape -> verify checksum -> parse order). Produces an
untyped `body: bytes` — message-specific body decoding stays out of scope (§8 Handlers, a
later phase). Encrypted bodies (RSA, body-attributes bit 10) are tagged via `encryption_
method`, never decrypted. Wired into `server.py`'s `on_frame` (replacing Phase 9.1's log-only
default): malformed/checksum-fail frames are logged and dropped, never crashing the
connection. Verified against the primary JT/T 808-2013 spec text directly (extracted via
PyMuPDF after the default `pdftotext` silently produced zero readable Chinese characters — a
failure caught, not missed) and with real TCP clients sending genuinely hand-framed packets to
a live server (`tests/`, plus a manual script exercising escaping, checksum failure resilience,
and cross-frame subpackage reassembly).

**Phase 9.4 (Message Dispatcher): implemented.** `src/dispatcher/dispatcher.py`'s
`MessageDispatcher` routes a decoded `InboundMessage` (Phase 9.3's `PacketParser` output) to
the handler registered for its `message_id` (`registry.py`'s `HandlerRegistry`), or to
`unknown_handler.UnknownMessageHandler` if none is registered — JT808 Technical Design §7's
documented behavior: unknown message IDs get a real, wire-encoded `0x8001` "not supported"
general response (§8.2), never silently dropped. Exactly 8 named message IDs are registered
(`message_ids.py`, each cross-checked against its own primary-spec section), all bound to a
single reusable `PlaceholderMessageHandler` — no business logic, logs receipt only, sends no
response (a documented, user-confirmed scope decision: extending the "unknown -> not
supported" behavior to known-but-unimplemented message IDs was considered and deliberately not
done). A handler exception is caught and reported (`on_handler_error`), never crashing the
connection. Added the encode-side mirror of Phase 9.3's decoder (`protocol/encoder.py`,
`escaping.escape`, `header.encode_bcd_phone`) and two minimal additions to Phase 9.1's
`ConnectionManager` (`send_to_connection`, alongside the existing `close_connection`) — both
needed for the dispatcher to actually send the automatic acknowledgment. Verified with real TCP
clients sending genuinely hand-framed packets through the full TCP -> Transport -> Codec ->
Dispatcher stack against a live server, confirming each of the 8 message IDs reaches its own
correctly-named handler (`tests/`, plus a manual script).

**Phase 9.5 (Authentication & Registration): implemented.** `src/handlers/registration_handler.py`
(`TerminalRegistrationHandler`, `0x0100 -> 0x8100`) and `authentication_handler.py`
(`TerminalAuthenticationHandler`, `0x0102 -> 0x8001`) — the first *real* message handlers in
this service, JT808 Technical Design §4/§8 and JT/T 808-2013 §8.5/§8.6/§8.8. Both depend only
on an injected `DeviceProvisioningPort` (`handlers/provisioning_port.py`) — a ports/interfaces
seam, per the task's explicit "if future persistence is required, use ports/interfaces only";
no concrete implementation exists yet (no Database, no Fleet Device integration, no Redis), so
`server.py`'s composition root binds the fail-closed `NullDeviceProvisioningPort` by default
(every registration/auth rejected until a real port is wired). A flagged, unresolved conflict
between JT808 Technical Design §4 (reads as: a static, pre-provisioned device secret) and the
primary JT/T 808-2013 spec (reads as: a platform-issued code, minted at registration and echoed
back at auth) was surfaced and confirmed with the user before implementing — resolved by
keeping the port's `auth_code` semantically opaque rather than committing to either reading
(see `provisioning_port.py`'s module docstring for both sources verbatim). On successful
authentication, `TerminalAuthenticationHandler` binds a `DeviceSession` via Phase 9.2's
`DeviceSessionManager.create()` (in `AUTHENTICATED` state); it deliberately does **not** call
`touch()` — promotion to `ONLINE` is reserved for a future Heartbeat/Location handler, per the
Phase 9.2-established state-machine reading, reconfirmed with the user for this phase.
Duplicate/repeated authentication needed no new logic — Phase 9.2's `create()` already
implements ADR-808-8 supersede (different connection) and safe idempotent replace (same
connection). Rejection/failure follow JT808 Technical Design §4's "reject + audit + close":
the dispatcher sends the response, then closes the connection (`HandlerResult.
close_connection_after`, a minimal Phase 9.4 dispatcher addition). Verified with 32 new unit
and full-stack integration tests (registration/auth encoding, handler behavior against a fake
provisioning port, real TCP clients against a live `Jt808Server`) plus a manual verification
script covering Register -> Authenticate -> Heartbeat-ready state, ADR-808-8 supersede, and
clean shutdown with zero leaked tasks.

**Phase 9.6 (Position Pipeline): implemented.** `src/handlers/location_handler.py`
(`LocationHandler`, `0x0200`) and `bulk_location_handler.py` (`BulkLocationHandler`, `0x0704`) —
the integration point between this service and the completed Tracking bounded context. Parse
the position body (`handlers/position_body.py`: JT/T 808-2013 §8.18 Table 23's fixed 28-byte
layout — alarm flags, status bits, hemisphere-signed lat/lng, altitude, speed unit conversion
1/10 km/h → whole km/h, heading, BCD GMT+8 time → UTC; `handlers/bulk_position_body.py`: §8.49
Table 76/77's item-count-driven batch format, each item sharing `0x0200`'s body format),
resolve the reporting terminal's `device_id`/`vehicle_id`/`organization_id` from its already-
bound `DeviceSession` (Phase 9.2/9.5), and publish one `DevicePositionReported` event per
position via the injected `EventPublisher` port (`events/publisher_port.py`) — `is_backfill=
False` for `0x0200`, `True` for every item in a `0x0704` batch (Technical Design §10's uniform
backfill classification for the whole message, not a per-item split on the primary spec's
`position_data_type` byte — see `bulk_position_body.py`'s module docstring). Batch items publish
sequentially (`await`ed in turn, never `asyncio.gather`) to preserve wire order.

**Flagged and resolved before implementing:** the task's own literal wording ("Position handlers
must communicate only through `TrackingApplicationService`") directly conflicted with every
approved architecture document (`.claude/rules/architecture.md` #3, `.claude/rules/jt808.md` #1,
JT808 Technical Design, Backend LLD §10.3, `docs/architecture/adr/0001-*`), which unanimously
require the device plane to reach the business plane only via published domain events over a
broker, never a synchronous in-process call. Confirmed with the user in favor of the approved
architecture: **neither handler imports `tracking` or calls `TrackingApplicationService`** —
they publish `DevicePositionReported` (`events/device_position_reported.py`, field-shape-
identical to `RecordVehiclePositionCommand`/`RecordBackfillPositionCommand` by design) and stop.
Geofence evaluation is consequently **not** triggered by this phase either — Tracking's own
`evaluate_geofence` isn't even auto-invoked by its own `record_vehicle_position`; JT808 Technical
Design §21.2 places persist-then-evaluate inside a not-yet-built Business API-side consumer of
this event, not inside JT808. `trip_id` is always `None` (§10: no Redis-backed active-trip
read-model exists yet — documented as the correct fallback, not a bug). No real broker/outbox
exists either (none approved anywhere in this repo yet); `event_publisher` defaults to
`LoggingEventPublisher`, a structured-log-only stand-in, mirroring `NullDeviceProvisioningPort`'s
"framework only, no crash" stance from Phase 9.5. **Authenticated session required**: a `0x0200`/
`0x0704` from a terminal with no bound `DeviceSession` (or one missing any of the three resolved
identity fields) is logged at WARNING (audited) and dropped, without closing the connection. No
wire response is sent for either message — JT808 Technical Design §8's Handler table documents
no `0x8001` ack for either, and the primary spec's only response mention (per-alarm-bit,
optional) is notification/business-response territory this phase's scope excludes. Verified with
64 new unit and full-stack integration tests (position/batch body parsing incl. hemisphere signs,
unit conversion, malformed/truncated rejection; handler-level tests against a recording publisher
fake covering the task's full verification list; real-TCP integration tests) plus a manual
verification script covering authenticate → single position → batch backfill → malformed packet
→ unauthenticated drop → clean shutdown with zero leaked tasks.

**Open item flagged, not resolved this phase (kept in scope discipline):** Phase 9.5's own
docstring anticipated "a future Heartbeat/Location handler" triggering the `AUTHENTICATED ->
ONLINE` transition (`DeviceSessionManager.touch()`), but this phase's task instructions list
neither "device online transition" nor a `touch()` call among what to implement — `LocationHandler`
therefore does not call `touch()`, and nothing in this codebase yet does. A future phase should
decide explicitly whether `LocationHandler` (live only, never `BulkLocationHandler` — backfilled
data must never drive live/online state, `.claude/rules/jt808.md` #3) is the right trigger, or
whether that stays exclusively a Heartbeat handler's job.

**Not yet implemented** (see `src/handlers/`, `src/commands/`, `src/events/`, `store/` above):
message-specific body field decoding and the vendor Anti-Corruption Layer for the remaining 4
message IDs, real business logic for heartbeat/alarm/command-ack/logout, a concrete
`DeviceProvisioningPort` implementation (real credential/device-lookup logic), a real outbox +
broker `EventPublisher` implementation, the `AUTHENTICATED -> ONLINE` transition trigger (open
item above), the Redis-backed active-trip read-model `trip_id` resolution depends on, alarm
processing beyond raw `alarm_flags` passthrough, Redis-backed session state, cross-shard command
routing, and business-initiated command downlink (§12 — distinct from this phase's protocol-level
automatic acks).
