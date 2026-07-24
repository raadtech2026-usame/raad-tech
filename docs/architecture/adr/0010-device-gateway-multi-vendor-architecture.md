# ADR-0010: Device Gateway — Multi-Vendor Architecture and Redis Integration

## Status
Accepted. Implemented and verified. Extends ADR-0009 (which established that the procured
hardware needs its own protocol adapter, not literal JT/T 808) with the structural and
infrastructure decisions that followed once a second vendor's adapter existed side by side with
the original JT/T 808 code in the same deployable: renaming the deployable itself, organizing
every protocol under a common `vendors/<name>/` layout behind a shared interface, and wiring a
real Redis-backed event bus and device registry in place of the interim in-memory stand-ins
ADR-0009 explicitly deferred.

## Context
After ADR-0009, `services/jt808/` contained two structurally equivalent but independently-run
protocol stacks — the original JT/T 808-2013 implementation and the new LSZ MDVR adapter — plus a
growing amount of genuinely shared, protocol-agnostic code (`connection/`, `session/`, `events/`).
The deployable's own name ("jt808") no longer described what it did, and nothing enforced that a
third vendor (a real possibility — this platform's actual fleet is not guaranteed to stay
single-vendor) would be added the same way the second one was, rather than as a one-off,
differently-shaped addition.

Separately, ADR-0009's `InMemoryMdvrDeviceProvisioningPort` and `LoggingEventPublisher` were
always explicitly interim (see that ADR's own Consequences section) — real device authorization
needs a live read-model of `fleet_device`'s own devices, and real event delivery needs the events
to actually reach the Business API, not just a log line.

## Decision

### 1. Rename `services/jt808/` → `services/device-gateway/`
The deployable is the single entry point for every device-plane vendor integration, not a
JT/T-808-specific service that happens to also run something else. `git mv` (via a filesystem move
plus `git add` staging, since `git mv` itself hit a transient permission error in this
environment — git's own rename detection still recognized every moved file by content similarity,
confirmed via `git status`) preserved history.

### 2. Reorganize into `src/vendors/<name>/`
- `src/vendors/jt808/` — the original JT/T 808-2013 protocol/dispatcher/handlers/`server.py`,
  moved verbatim (only import paths changed, updated mechanically).
- `src/vendors/lsz/` — the LSZ MDVR adapter, renamed from `vendors/lsz_mdvr/` (folder only —
  internal class names keep their `Mdvr` prefix, since "MDVR" accurately names the hardware
  *category* the vendor's own protocol governs, distinct from `lsz`, the vendor *brand* name the
  folder is keyed on to match its sibling folders; renaming ~15 files' worth of `Mdvr*` class
  names to `Lsz*` for symbolic consistency alone was judged unnecessary churn against this ADR's
  own "refactor only where necessary" instruction).
- `src/vendors/teltonika/`, `src/vendors/queclink/`, `src/vendors/ruptela/` — structural
  placeholders only (a docstring explaining why, no code) reserving each vendor's place in the
  layout. No protocol code is invented for them: no hardware has been procured and no vendor
  documentation exists for any of the three, and this codebase's own established discipline
  (`docs/vendor/HARDWARE_ANALYSIS.md`'s "do not assume undocumented hardware capability") applies
  identically to inventing a whole adapter, not just a field.
- `src/connection/`, `src/session/`, `src/events/` stay at the top level — genuinely
  vendor-agnostic, shared by every adapter.

### 3. `src/adapter.DeviceProtocolAdapter` — the common interface
A minimal ABC (`name`, `start`, `stop`, `bound_port`, `session_count`, `device_session_count`) —
the only shape `src/gateway.py`'s composition root needs across *every* vendor. Both
`Jt808Server` and `MdvrServer` now implement it; adding a new vendor means implementing this ABC,
nothing else. Deliberately excludes `serve_forever()` — each adapter keeps its own for standalone
use, but the multi-adapter gateway owns one shared signal handler instead of letting every adapter
install its own (see `src/adapter.py`'s own docstring for why that would conflict).

### 4. `src/gateway.DeviceGateway` — the actual process entrypoint
Constructs and starts every configured adapter under one shared signal handler, injecting the
*same* `EventPublisher` instance into all of them — the concrete mechanism satisfying "the
Business Plane must never know which protocol or vendor produced the data": every adapter
publishes the identical four event types through the identical port, and nothing downstream can
distinguish their origin.

### 5. One additive, necessary change to previously "pure" shared code
`connection.Connection`/`connection.manager.ConnectionManager` had one remaining hidden dependency
on JT/T 808 specifically: a default frame buffer, and a `FrameTooLargeError` catch that only
recognized JT/T 808's own exception class (a real, latent bug — an oversized, unterminated LSZ
frame would have raised uncaught out of the read loop's background task instead of closing the
connection gracefully, confirmed and fixed with a regression test,
`tests/test_mdvr_server_integration.py::MdvrFrameTooLargeIntegrationTests`). Fixed by:
- Making `frame_buffer`/`frame_buffer_factory` **required** constructor parameters (no more
  vendor-specific default) — every adapter now supplies its own explicitly.
- A new shared `connection.errors.FrameTooLargeError` base class every vendor's own
  "frame too large" exception subclasses, so `Connection`'s read loop catches one type regardless
  of vendor.

### 6. Redis-backed event bus (`events.redis_event_publisher.RedisEventPublisher`)
Publishes onto the **same** `raad:events` Redis Stream (ADR-0008) the Business API's own
`RedisStreamsBrokerPort`/`RedisStreamsBrokerConsumer` already read from and write to — the exact
wire envelope (`_event_to_fields`/`_fields_to_event`'s shape) reproduced field-for-field, verified
by actually decoding a published event with the real backend function and running it through the
real `tracking.events.subscribers.DevicePositionReportedProcessor` (a one-off cross-deployable
sanity check, not a permanent test — permanently importing backend code from this deployable's
own test suite would violate `.claude/rules/architecture.md` #2's "no dependency on `backend/raad`
and vice versa" even inside tests). `DeviceOnline`/`DeviceOffline` are now real, concrete event
dataclasses (previously named throughout the architecture docs and in `on_device_online`/
`on_device_offline` callback names, but never actually constructed) — `DeviceSessionManager.
touch()`/`close()` now `await` these callbacks so a composition root can publish real events, not
just log lines; `DeviceAlarmRaised` is defined for completeness but nothing constructs one yet
(no alarm handler exists in any vendor adapter — a real, separate gap, not fabricated here).

### 7. Broker-driven device registry (`registry.device_registry_projection.
DeviceRegistryProjection` + `registry.redis_device_registry_consumer.RedisDeviceRegistryConsumer`)
A read-model of `fleet_device` devices, kept current by consuming that module's own
`DeviceRegistered`/`DeviceActivated`/`DeviceSuspended`/`DeviceReactivated`/`DeviceRetired`/
`DeviceAssignedToVehicle`/`DeviceUnassignedFromVehicle`/`DeviceReassigned` events off the same
shared stream, in its own consumer group (`device-gateway-registry`) — never a synchronous
cross-service DB read. Backs `vendors.lsz.handlers.provisioning_port.
ProjectionBackedMdvrProvisioningPort`, the real (non-interim) LSZ provisioning port, replacing
`InMemoryMdvrDeviceProvisioningPort` as `DeviceGateway`'s actual default whenever a broker is
configured. A device is "provisionable" only when active *and* assigned to a vehicle — both
required since every position handler needs a resolved `vehicle_id` before publishing anything.

### 8. `session.redis_device_session_registry.RedisDeviceSessionRegistry` — built, not yet wired
A real, fully-tested Redis-backed implementation of the session-registry operations
(`.claude/rules/jt808.md` #4's "session state lives in Redis"). **Deliberately not wired into
`DeviceSessionManager` as a swappable default this phase** — seeĀ Consequences below for the exact
reason and what wiring it in would additionally require.

## Options Considered

### Fully migrate `DeviceSessionManager` to an async-registry interface (rejected for this phase)
Would let `RedisDeviceSessionRegistry` become a true drop-in replacement for the in-memory
registry. Rejected for *this* phase specifically: it requires converting `DeviceSessionRegistry`'s
own methods to `async def` (including replacing `__len__`, which cannot itself be a coroutine),
`DeviceSessionManager.resolve()` becoming async (rippling into every handler in both vendor
stacks, all already-async methods so mechanically safe but wide-reaching), and `session_count`
becoming an async method on both `Jt808Server`/`MdvrServer`. No actual multi-node device-gateway
deployment exists yet to need this — the in-memory registry is already correct (and faster) for
today's single-process deployment. Building `RedisDeviceSessionRegistry` standalone and fully
tested, ready to wire in later, was judged the better-scoped choice than forcing this ripple
through two vendor stacks and their test suites for a capability nothing currently needs.

### A second Redis Streams instance/broker for the device-gateway specifically (rejected)
Rejected for the same reason ADR-0008 rejected a second broker technology generally: `raad:events`
already exists, is already reachable from wherever the Business API's own broker is configured,
and Redis Streams' native consumer-group model already gives this deployable its own independent
read position for free. Standing up a second stream/instance would be new infrastructure for no
benefit over an additional consumer group on the existing one.

## Consequences
- **Every existing test continues to pass unmodified** except where the change under test
  directly required updating (async `touch()`/callback signatures, import path fixes from the
  file moves) — verified by running the full suite after each phase of this refactor, not just at
  the end.
- **`RedisDeviceSessionRegistry` remains unwired** — a real, flagged follow-up: migrating
  `DeviceSessionRegistry`/`DeviceSessionManager` to an async-first interface is real, scoped,
  low-risk work (mechanical `await` insertion at already-async call sites) that should happen
  before any genuine multi-node device-gateway deployment, not before.
- **`DeviceAlarmRaised` has no producer yet** — the event bus is ready for it the moment a real
  alarm handler is built in either vendor stack; building that handler is undesigned business
  logic (which alarm types matter, what severity/action each implies) explicitly out of this
  phase's own scope.
- **Two independently-configured broker settings now exist** (`RAAD_BROKER__URL` for the Business
  API, `DEVICE_GATEWAY_BROKER_URL` for this deployable) that will typically point at the same
  Redis instance in any real deployment — mirroring ADR-0008's own `broker.url`-vs-`redis.url`
  precedent for exactly this reason (independent configurability, usually-coincident values).

## Verification
- `services/device-gateway/tests/test_gateway.py`: both adapters share one `EventPublisher`;
  without a broker configured, every adapter falls back to its pre-existing default unchanged;
  with a fake Redis client injected, `RedisEventPublisher`/`ProjectionBackedMdvrProvisioningPort`/
  the background registry-consumer task all wire in correctly and the consumer task cancels
  cleanly on `stop()`.
- `services/device-gateway/tests/test_redis_event_publisher.py`,
  `test_device_registry_projection.py`, `test_redis_device_registry_consumer.py`,
  `test_projection_backed_provisioning_port.py`, `test_redis_device_session_registry.py`: each new
  component tested standalone against a fake Redis client (no real server reachable in this
  sandbox, the same posture every other Redis-dependent component in this codebase already
  carries).
- `test_mdvr_server_integration.py::MdvrFrameTooLargeIntegrationTests`: regression-proves the
  shared `FrameTooLargeError` fix over a real socket.
- One-off manual cross-deployable check (not a committed test — see Decision §6): a
  `RedisEventPublisher`-published `DevicePositionReported`, decoded with the real backend
  `_fields_to_event` and run through the real `DevicePositionReportedProcessor`, produces a
  correct `RecordVehiclePositionCommand`.
- 323 device-gateway tests and 1077 backend unit tests pass.

## References
- `docs/architecture/adr/0009-mdvr-vendor-protocol-device-plane.md`
- `docs/architecture/adr/0008-redis-streams-event-broker.md`
- `.claude/rules/architecture.md` #2, #3
- `.claude/rules/jt808.md` #1, #4
- `.claude/rules/workflow.md` #1, #2, #10
- `services/device-gateway/src/adapter.py`, `src/gateway.py`, `src/registry/`,
  `src/events/redis_event_publisher.py`, `src/session/redis_device_session_registry.py`
