# Device Gateway

The single entry point for every GPS/MDVR device-plane vendor integration — renamed from
`services/jt808/` once it grew a second vendor's protocol adapter alongside the original JT/T 808
code (ADR-0010: `docs/architecture/adr/0010-device-gateway-multi-vendor-architecture.md`).
Terminates persistent TCP connections from bus terminals, parses whichever vendor protocol that
connection actually speaks, maintains device sessions, and normalizes telemetry into domain
events the Business API consumes — never the reverse; the Business API never opens a device
socket (`.claude/rules/architecture.md` #2).

Source of truth: `docs/business/RAAD_Phase3.4_JT808_Technical_Design_v1.md`,
`docs/business/RAAD_Phase2_Enterprise_Architecture_v1_2.md` §5.1, `docs/vendor/
HARDWARE_ANALYSIS.md`/`HARDWARE_INTEGRATION_PLAN.md` (the actually-procured hardware), and
`docs/architecture/adr/0009-mdvr-vendor-protocol-device-plane.md`/`0010-device-gateway-multi-
vendor-architecture.md` (the resulting architecture decisions).

**Language/runtime: Python (asyncio).** `pyproject.toml` now declares one dependency, `redis>=5.0`
(device-gateway Redis integration, approved — see that file's own comment for exactly what it
backs); everything else remains standard library only.

## Structure

```
src/
├── adapter.py     # DeviceProtocolAdapter — the common interface every vendor implements
│                  # (name, start, stop, bound_port, session_count, device_session_count)
├── gateway.py     # DeviceGateway — the actual process entrypoint. Starts every configured
│                  # adapter under one shared signal handler; wires the shared EventPublisher/
│                  # device-registry projection when a broker is configured (Redis integration)
├── broker_config.py  # DEVICE_GATEWAY_BROKER_URL — this deployable's own, independent broker
│                  # setting (mirrors ADR-0008's broker.url/redis.url independence)
├── connection/    # TCP Acceptor / Connection Manager — vendor-agnostic; each vendor injects
│                  # its own frame_buffer/frame_buffer_factory (no more hardcoded JT/T 808
│                  # default — ADR-0010's fix for a real latent bug, see that ADR's own §5)
├── session/       # DeviceSession/DeviceSessionRegistry/DeviceSessionManager — vendor-agnostic,
│                  # in-memory by default; RedisDeviceSessionRegistry (Redis integration) is a
│                  # real, tested, standalone Redis-backed alternative, not yet wired in as the
│                  # default (see its own module docstring for exactly why and what wiring it in
│                  # would additionally require)
├── events/        # DevicePositionReported/DeviceOnline/DeviceOffline/DeviceAlarmRaised (all
│                  # real dataclasses) + EventPublisher port. LoggingEventPublisher (default,
│                  # no broker configured) and RedisEventPublisher (Redis integration — publishes
│                  # onto the same raad:events Redis Stream, ADR-0008, the Business API's own
│                  # tracking.events.subscribers.DevicePositionReportedProcessor already reads)
├── registry/      # DeviceRegistryProjection (read-model of fleet_device devices) +
│                  # RedisDeviceRegistryConsumer (keeps it current off raad:events) — Redis
│                  # integration; backs the real, non-interim LSZ provisioning port
└── vendors/
    ├── jt808/      # JT/T 808-2013 — real, tested (Phases 9.1-9.6 below). Dormant: not the
    │               # currently-integrated hardware (docs/vendor/HARDWARE_ANALYSIS.md §2), kept
    │               # for a possible future genuinely-compliant vendor.
    ├── lsz/        # Shenzhen Tianyou "LSZ" MDVR — the actually-procured hardware's real
    │               # proprietary protocol (ADR-0009). Implemented: registration/heartbeat/
    │               # position (B1/B2 below). Not implemented: the media-channel protocol
    │               # (live video/file transfer/firmware upgrade — roadmap track B3).
    ├── teltonika/  # Structural placeholder only — no hardware procured, no vendor docs, no
    ├── queclink/   # code invented ahead of either (see each package's own __init__.py).
    └── ruptela/
scripts/
└── verify_redis_e2e.py  # ADR-0012: real LSZ device -> real Redis -> real backend decode,
                          # against a genuinely reachable redis-server (no fake client) — the
                          # committed, reusable version of ADR-0010 §6's one-off check
```

## Local dev environment (ADR-0012)

`.env.example` documents `DEVICE_GATEWAY_BROKER_URL` — this deployable has no dotenv loader
(`broker_config.py` reads bare `os.environ`), so export it into your shell rather than expecting
a `.env` file to be picked up automatically. Bring up Redis via `docker/docker-compose.yml`
(`redis` service, `docker compose -f docker/docker-compose.yml up -d`), then:

```bash
export DEVICE_GATEWAY_BROKER_URL=redis://localhost:6379/0
python scripts/verify_redis_e2e.py
```

A clean `PASS` proves this deployable's `RedisEventPublisher` output is decodable by the real
Business API `raad.core.events.redis_streams._fields_to_event` and
`tracking.events.subscribers.DevicePositionReportedProcessor`, over an actually-reachable Redis —
not just against the fake client every other test in this repo already uses. See ADR-0012 for
what this script does and does not verify, and for this environment's own current status (no
Docker/WSL/native Redis reachable here, confirmed — the script fails cleanly at its Redis PING
step rather than silently skipping).

## Key rule

This deployable never writes Business API tables directly — it only publishes domain events
(`DevicePositionReported`, `DeviceOnline`, `DeviceOffline`, `DeviceAlarmRaised`, command-result
events) consumed by the Business API. See `.claude/rules/jt808.md`.

## Status — device-gateway architecture (ADR-0010)

**`DeviceProtocolAdapter`/`DeviceGateway`: implemented.** Both `vendors.jt808.server.Jt808Server`
and `vendors.lsz.server.MdvrServer` implement the common interface; `DeviceGateway` starts/stops
both under one shared signal handler and injects one shared `EventPublisher` into each. Adding a
new vendor means implementing this interface under a new `vendors/<name>/` package — no change to
`gateway.py`'s own orchestration logic.

**Redis integration: implemented.** `RedisEventPublisher` publishes all four event types onto the
shared `raad:events` Redis Stream, wire-compatible with the Business API's own consumer (verified
with a one-off cross-deployable decode-and-process check, not a permanent test — see ADR-0010 §6
for why this stays a documented contract rather than shared code). `DeviceRegistryProjection` +
`RedisDeviceRegistryConsumer` keep a read-model of `fleet_device` devices current off the same
stream, backing `vendors.lsz.handlers.provisioning_port.ProjectionBackedMdvrProvisioningPort` —
the real, non-interim LSZ device allow-list, replacing `InMemoryMdvrDeviceProvisioningPort` as
`DeviceGateway`'s actual default whenever `DEVICE_GATEWAY_BROKER_URL` (or an injected
`redis_client`) is configured. Without one, every adapter falls back to exactly its pre-Redis
default (`LoggingEventPublisher`, `NullMdvrDeviceProvisioningPort`) — nothing about the
unconfigured path changed.

**`RedisDeviceSessionRegistry`: implemented, not yet wired in as the default.** A real, fully
tested Redis-backed session store (`.claude/rules/jt808.md` #4) — see its own module docstring for
exactly why swapping it in for `DeviceSessionManager`'s in-memory default needs a separate,
mechanical (but wide-reaching) async-interface migration, not undertaken this phase since no
multi-node deployment exists yet to need it.

**Not yet implemented:** a producer for `DeviceAlarmRaised` (the event/publish machinery is ready;
no vendor adapter has a real alarm handler yet — see each vendor's own status below); the
media-channel protocol for any vendor (roadmap track B3); `teltonika`/`queclink`/`ruptela` (no
hardware/docs exist for any of the three).

---

## `vendors/jt808/` — JT/T 808-2013 status

Moved verbatim from this deployable's original top-level `src/` (only import paths changed) —
every phase below was built and verified before the rename/reorganization and is unaffected by it.

**Phase 9.1 (Transport Layer): implemented.** TCP server bootstrap (`server.py`), async
connection accept/read/write loops and lifecycle (shared `connection/`), JT/T 808 frame boundary
detection (`protocol/framing.py`), an in-memory, connection-scoped session registry (shared
`session/`), and idle-timeout infrastructure. Verified with a real TCP server, real socket
clients, and mocked frames (`tests/`).

**Phase 9.2 (Session Management): implemented.** `DeviceSession`/`DeviceSessionRegistry`/
`DeviceSessionManager` (shared `session/`) — terminal-identity-keyed sessions bound after
authentication, duplicate-terminal supersede (ADR-808-8), reconnect, expiration, and
online/offline lifecycle. Verified with real TCP clients wired through the real `Jt808Server`.

**Phase 9.3 (Packet Parser): implemented.** `protocol/escaping.py`/`checksum.py`/`header.py`/
`reassembly.py`/`message.py`/`parser.py` — unescape → verify checksum → parse, per the spec's own
mandated order. Verified against the primary JT/T 808-2013 spec text directly and with real TCP
clients sending hand-framed packets to a live server.

**Phase 9.4 (Message Dispatcher): implemented.** `dispatcher/dispatcher.py`'s `MessageDispatcher`
routes a decoded `InboundMessage` by `message_id` to its registered handler, or to
`UnknownMessageHandler` (a real, wire-encoded `0x8001` "not supported" response). Verified with
real TCP clients through the full stack against a live server.

**Phase 9.5 (Authentication & Registration): implemented.** `handlers/registration_handler.py`/
`authentication_handler.py` — `0x0100 -> 0x8100`, `0x0102 -> 0x8001`. Depend only on an injected
`DeviceProvisioningPort`; defaults to the fail-closed `NullDeviceProvisioningPort` (every
registration/auth rejected until a real port is wired — none exists for this dormant vendor).
Verified with 32 unit/integration tests.

**Phase 9.6 (Position Pipeline): implemented.** `handlers/location_handler.py`/
`bulk_location_handler.py` — `0x0200`/`0x0704`, publishing `DevicePositionReported` via the
injected `EventPublisher`, never calling into `tracking` directly. Verified with 64 unit/
integration tests.

**Open item, still not resolved:** no handler in this stack calls `DeviceSessionManager.touch()`
— real heartbeat business logic (`0x0002`) remains a `PlaceholderMessageHandler` no-op, so
`AUTHENTICATED -> ONLINE` (and therefore `DeviceOnline`) never actually fires for this vendor
today. Left as-is: this vendor is dormant (not the currently-integrated hardware), so building a
real heartbeat handler has no operational value until a genuinely JT/T-808-compliant vendor is
procured.

**Not yet implemented:** message-specific body decoding for the remaining 4 named message IDs,
real business logic for heartbeat/alarm/command-ack/logout, a concrete `DeviceProvisioningPort`
implementation, Redis-backed session state for this vendor specifically (the shared
`RedisDeviceSessionRegistry` exists and could back it once wired in — see the top-level Status
section), and business-initiated command downlink.

---

## `vendors/lsz/` — LSZ MDVR status (roadmap tracks B1/B2/B3)

The actually-procured hardware's real protocol (ADR-0009) — an ASCII/binary vendor protocol,
confirmed unrelated to JT/T 808/1078 (`docs/vendor/HARDWARE_ANALYSIS.md` §2). Folder renamed
`vendors/lsz_mdvr/` → `vendors/lsz/` (ADR-0010) — internal class names keep their `Mdvr` prefix
(naming the hardware category, distinct from `lsz`, the vendor brand the folder is keyed on).

**Signaling protocol (B1/B2): implemented.** `protocol/` — `$$dc...#` ASCII framing/parsing/
encoding, and a GPS D°M′S″-to-decimal-degree Anti-Corruption Layer (`location_status.py`,
cross-validated against real-world Shenzhen coordinates in two independent vendor worked
examples). `dispatcher/` — keyword-keyed (not message-ID-keyed) registry/dispatcher, mirroring
`vendors/jt808/dispatcher/`'s shape. `handlers/` — registration (`V101 -> C100`, binds the
`DeviceSession` directly since this protocol has no separate authentication message), heartbeat
(`V109 -> C501`, promotes `AUTHENTICATED -> ONLINE`, now genuinely publishing `DeviceOnline` — see
below), position (`V114 -> DevicePositionReported`, reusing the shared `events/` unchanged).
`server.py` (`MdvrServer`) — reuses shared `connection/`/`session/` unchanged, implements
`DeviceProtocolAdapter`.

**Device provisioning: real, non-interim implementation now wired (Redis integration).**
`ProjectionBackedMdvrProvisioningPort` resolves a device serial number against the shared
`DeviceRegistryProjection`, itself kept current by `RedisDeviceRegistryConsumer` off
`fleet_device`'s own domain events — replacing `InMemoryMdvrDeviceProvisioningPort` as
`DeviceGateway`'s actual default whenever a broker is configured. Still, deliberately, a
serial-number allow-list only: this vendor's protocol has no cryptographic authentication step at
all (`docs/vendor/HARDWARE_ANALYSIS.md` §11) — the missing assurance is a network-layer
compensating-control gap (`.claude/rules/security.md` #9), not solved by the registry.

**Event publishing: real, non-interim implementation now wired (Redis integration).** Position
reports publish `DevicePositionReported`; the first heartbeat after registration now genuinely
publishes `DeviceOnline` (previously only logged); a dropped/expired/closed connection genuinely
publishes `DeviceOffline` with its close reason — all via the shared `RedisEventPublisher` when a
broker is configured, `LoggingEventPublisher` otherwise. The Business API's own consumer half
(`backend/raad/modules/tracking/events/subscribers.py`'s `DevicePositionReportedProcessor`) needs
no further change and was proven, end to end, against this publisher's actual output.

**Tested:** 323 device-gateway tests total (up from 226 pre-LSZ), covering framing, parsing, GPS
normalization, encoding, each handler in isolation, the dispatcher, `DeviceGateway`'s multi-adapter
wiring (both with and without a broker configured), the Redis-backed event publisher/registry
projection/registry consumer/session registry, and full-stack real-socket integration tests
(register → heartbeat → position, `DeviceOnline`/`DeviceOffline` publish timing, rejection/
unauthenticated-drop paths, and a regression test for a real bug ADR-0010 found and fixed: an
oversized unterminated LSZ frame previously raised uncaught out of the read loop instead of
closing the connection, because `Connection` only caught JT/T 808's own `FrameTooLargeError`
subclass). All pre-existing JT/T 808 tests continue to pass unmodified.

**Not yet implemented:** the media-channel protocol (live video/file transfer/firmware upgrade —
roadmap track B3, `docs/vendor/HARDWARE_ANALYSIS.md` §6/§9); the vendor's own "center-initiated,
unprompted `C501` every 6s" heartbeat behavior (this stack only acknowledges a device's own
`V109`); a producer for `DeviceAlarmRaised` (no RAAD bounded context has a documented home for raw
device-hardware alarms yet, `docs/vendor/HARDWARE_INTEGRATION_PLAN.md` §10); wiring
`RedisDeviceSessionRegistry` as this vendor's actual session store (see top-level Status section).
