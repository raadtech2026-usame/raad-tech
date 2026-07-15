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
│                 #   - message-specific body field decoding          [not yet implemented]
│                 #   - vendor ACL (dialect normalization)             [not yet implemented]
├── dispatcher/   # Packet Dispatcher — routes by message_id to handlers  [Phase 9.4: implemented]
├── handlers/     # Message Handlers: register, auth, heartbeat, location,
│                 # bulk/backfill location, alarm, command-ack
│                 #   - placeholder (no-op, logs only) for all 8 named message IDs
│                 #     [Phase 9.4: implemented, in src/dispatcher/placeholder_handler.py]
│                 #   - real business logic for each                  [not yet implemented]
├── session/      # Session Manager
│                 #   - transport-level ConnectionSession, keyed by connection_id
│                 #     [Phase 9.1: implemented, in-memory only]
│                 #   - device-level DeviceSession, keyed by terminal_id, bound after auth;
│                 #     duplicate-terminal supersede (ADR-808-8); expiration; online/offline
│                 #     lifecycle (AUTHENTICATED/ONLINE/OFFLINE only - no IDLE/BACKFILLING/
│                 #     REGISTERED, which need packet parsing this phase doesn't have)
│                 #     [Phase 9.2: implemented, in-memory only]
│                 #   - node_id / cross-shard command routing / Redis backing store
│                 #     [not yet implemented]
├── commands/     # Command Executor — downlink (real-time A/V request, playback, config, text)
│                 #                                                  [not yet implemented]
└── events/       # Event Publisher — local outbox -> event bus      [not yet implemented]
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

**Not yet implemented** (see `src/handlers/`, `src/commands/`, `src/events/`, `store/` above):
message-specific body field decoding and the vendor Anti-Corruption Layer, real business logic
for any of the 8 registered message IDs (register/auth/heartbeat/location/alarm/command-ack/
logout/bulk-location), device identity/auth (credential verification itself — Phase 9.2's
`create()` assumes it already happened), GPS position processing, alarm processing,
Redis-backed session state, cross-shard command routing, domain event publishing, and
business-initiated command downlink (§12 — distinct from this phase's protocol-level automatic
acks).
