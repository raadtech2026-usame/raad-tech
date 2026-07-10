# JT808 TCP Server

Terminates persistent TCP connections from bus terminals, parses JT/T 808 messages, maintains device
sessions, normalizes telemetry into domain events, and relays platform commands down to devices.
Independently deployable — the Business API never opens a device socket.

Source of truth: `docs/business/RAAD_Phase3.4_JT808_Technical_Design_v1.md` and
`docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §5.1.

**Language/runtime for this service is not yet decided by approved documentation.** Do not assume a
stack; confirm before scaffolding build tooling.

## Structure (logical components — see `.claude/rules/jt808.md`)

```
src/
├── connection/   # TCP Acceptor / Connection Manager
├── protocol/     # Packet Parser / Framer + vendor Anti-Corruption Layer
├── dispatcher/   # Packet Dispatcher — routes by message_id to handlers
├── handlers/     # Message Handlers: register, auth, heartbeat, location,
│                 # bulk/backfill location, alarm, command-ack
├── session/      # Session Manager (device_id -> vehicle_id, org_id, last_seen, auth_state)
├── commands/     # Command Executor — downlink (real-time A/V request, playback, config, text)
└── events/       # Event Publisher — local outbox -> event bus
store/            # Local persistent store: outbox, device_session, raw_frame_audit, command_log
```

## Key rule

JT808 never writes Business API tables directly — it only publishes domain events
(`DevicePositionReported`, `DeviceOnline`, `DeviceOffline`, `DeviceAlarmRaised`, command-result
events) consumed by the Business API. See `.claude/rules/jt808.md`.

## Status

Structural scaffold only. No connection handling, parsing, or message logic is implemented yet.
