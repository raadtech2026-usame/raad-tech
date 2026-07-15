# JT808 TCP Server

Terminates persistent TCP connections from bus terminals, parses JT/T 808 messages, maintains device
sessions, normalizes telemetry into domain events, and relays platform commands down to devices.
Independently deployable — the Business API never opens a device socket.

Source of truth: `docs/business/RAAD_Phase3.4_JT808_Technical_Design_v1.md` and
`docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §5.1.

**Language/runtime: Python (asyncio)**, confirmed with the user for Phase 9.1 (no approved
document names one — see git history for the confirmation). `pyproject.toml` declares zero
third-party dependencies; the transport layer uses only the standard library.

## Structure (logical components — see `.claude/rules/jt808.md`)

```
src/
├── connection/   # TCP Acceptor / Connection Manager               [Phase 9.1: implemented]
├── protocol/     # Packet Parser / Framer + vendor Anti-Corruption Layer
│                 #   - frame boundary detection (0x7e)              [Phase 9.1: implemented]
│                 #   - unescape/checksum/field parsing               [not yet implemented]
├── dispatcher/   # Packet Dispatcher — routes by message_id to handlers  [not yet implemented]
├── handlers/     # Message Handlers: register, auth, heartbeat, location,
│                 # bulk/backfill location, alarm, command-ack       [not yet implemented]
├── session/      # Session Manager
│                 #   - transport-level ConnectionSession (this phase's scope)
│                 #     [Phase 9.1: implemented, in-memory only]
│                 #   - full device_id -> vehicle_id/org_id/auth_state shape [not yet implemented]
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

**Not yet implemented** (see `src/dispatcher/`, `src/handlers/`, `src/commands/`,
`src/events/`, `store/` above): JT808 packet parsing (unescape/checksum/field decode),
message handlers (register/auth/heartbeat/location/alarm/command-ack), device identity/auth,
GPS position processing, alarm processing, Redis-backed session state, domain event
publishing, and command downlink.
