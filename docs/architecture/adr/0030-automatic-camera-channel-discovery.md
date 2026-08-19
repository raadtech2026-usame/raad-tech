# ADR-0030: Automatic Camera/Channel Discovery

## Status

**Accepted** (direct user decision, 2026-08-18, following the read-only bench-test diagnostic
that traced "No camera channels configured" to two real gaps: no code path from a discovered
channel list to a `Camera` row, and no HTTP route to register one manually either). Three
genuinely blocking design forks were resolved via `AskUserQuestion` before implementing (all
"(Recommended)" options accepted) — see Decision §1/§2/§3 below for exactly what was decided and
why. Implemented same session, verified against the physical `LSZ-C5804DG-Q-F` bench unit
(`terminal_id=00000000014482607571`).

## Context

The bench-test diagnostic immediately preceding this ADR (read-only, no code changes) established:
JT808 registration/heartbeat/GPS is fully working end to end for the test device; `cameras` has
zero rows; `RegisterCameraCommand` exists at the application layer with no HTTP route; no event
subscriber turns device-reported channel data into a `Camera` row; `services/jt1078` (the media
relay) was never started; and `RAAD_DEVICE_PLANE__JT1078_SIGNALING_URL` was unset everywhere,
so `VideoProviderPort` never binds regardless of the other two gaps.

The user explicitly declined a one-off manual fix for the current test device ("Do NOT register
Camera 1 manually... Do NOT solve the problem by manually creating Camera 1 for the current
device") and asked for the generic product workflow: any JT808/JT1078-compliant MDVR added
through **Add Device** should have its cameras discovered and registered automatically, with no
database/shell intervention, ever.

Per `.claude/rules/workflow.md` #8 ("Never implement business logic without an approved design"),
this ADR was written — and its three open design questions resolved with the user — before any
code was touched.

**A real, load-bearing correction found while investigating, not assumed:** the JT/T1078 message
pair that actually reports channel *count/capability* is **`0x9003`/`0x1003`** ("Query/Upload
Terminal A/V Attributes," `MDVR-808-1078-spec.pdf` §6.1.1/§6.1.2) — **not** `0x9205`/`0x1205`
(`commands/video_signaling.py`'s `QueryResourceList`/`ResourceListReport`), which the prior
diagnostic turn had assumed based on the "resource list" name but which the code's own comment
already correctly scoped as "the terminal's own **recording** resource list" — i.e. browsing
recorded video *files*, not physical channel capability. `0x9003`/`0x1003` was not implemented
anywhere in `device-gateway` before this ADR; this phase adds it as new, spec-verified protocol
code, not a reuse of an existing handler.

## Decision

### 1. Discovery trigger: once per device, on first successful authentication

RAAD automatically sends `0x9003` the first time a device's `DeviceOnline` transition fires with
`av_attributes_requested_at IS NULL` (a new, purely additive `devices` column — the idempotency
guard). A later reconnect for the same device never re-triggers it. This is the literal reading
of "RAAD automatically requests... after registration" from the product workflow, kept
lightweight (no repeated signaling traffic on every reconnect over what may be a constrained
cellular link) — the rejected alternatives were "every reconnect" (continuous but heavier) and
"admin-triggered only" (safest but not automatic, contradicting the requested workflow).

### 2. Channel-to-position mapping: default to `other`, never guess semantics

Every auto-discovered channel becomes a `Camera` with `position=CameraPosition.OTHER`,
`label=f"Channel {n}"`. The vendor spec's own Table 5.31 (a standard commercial/passenger-vehicle
channel convention: channel 1 = driver-facing, 2 = front-of-vehicle, etc.) is **not** hardcoded
as a platform-wide mapping — RAAD does not hold the actual JT/T1078-2016 standard text to confirm
that convention is universal across every future JT/T1078-compliant vendor (Teltonika/Queclink/
Ruptela remain unconfirmed placeholders, ADR-0010), and inventing a semantic mapping from one
vendor's own document would risk misclassifying a different vendor's hardware. An Org Admin can
rename/reposition a discovered camera through the ordinary camera-editing surface once one exists
(none does yet — a disclosed, pre-existing gap this ADR does not close).

### 3. JT1078 relay URL: environment variable per environment, no hardcoded localhost in production

`RAAD_DEVICE_PLANE__JT1078_SIGNALING_URL` (already a real, previously-unused settings field —
`core/config/settings.py`'s `DevicePlaneSettings.jt1078_signaling_url`) is read from a new
`JT1078_SIGNALING_URL` Compose variable, defaulting to `ws://localhost:7911` in `docker/.env`/
`.env.example` — matching this repository's own established `dev-only-change-me`-style
placeholder convention (ADR-0022 precedent: secrets/URLs are environment variables, composition-
root only, never hardcoded in application code). **Production must set a real value** (the
relay's actual public URL, e.g. routed through nginx/Coolify's own TLS termination as
`wss://<domain>/...`) — the rejected alternative (routing the relay through the existing gateway
by default) is a larger infrastructure change deferred to a future phase, not attempted here.

### 4. `0x9003`/`0x1003` implementation — new protocol code, mirroring existing patterns exactly

`services/device-gateway/src/vendors/jt808/commands/av_attributes.py` (new): `encode_query_av_
attributes()` (empty body, §6.1.1) and `parse_av_attributes_report()` (the fixed 10-byte §6.1.2
Table 6.1 body). Only `max_video_channels` (byte offset 9, "终端支持的最大视频物理通道数量") is
consumed by the discovery workflow — RAAD derives channel *numbers* itself as `1..N`, matching
the spec's own confirmed "1-based, starting from 1" convention (found directly in the spec text,
not assumed), since the terminal's `0x1003` reply reports only a *count*, never an enumerated
per-channel list.

`handlers/av_attributes_handler.py` (new) mirrors `handlers/resource_list_handler.py`'s exact
shape, with one necessary difference: `0x1003`'s body carries no echoed original-serial-number
field (confirmed by reading Table 6.1 field-by-field — no such field exists, unlike `0x1205`'s
own `original_serial_no`), so correlation uses a new `PendingCommandTracker.
resolve_by_terminal_and_message(terminal_id, message_id)` (matches ignoring `serial_no`) rather
than the standard `resolve()` triple — safe specifically because at most one `0x9003` is ever
outstanding per device (Decision §1).

Publishes `DeviceAvAttributesReported` (new event, `src/events/`) carrying `max_video_channels`/
`max_audio_channels` plus the same identity/correlation fields every event in this deployable's
vocabulary already carries.

### 5. Trigger publish reuses the *existing* `Jt1078SignalCommandRequested` wire contract verbatim

`query_av_attributes` is one more entry in `commands/redis_video_signaling_consumer.py`'s own
`_BUILDERS` dispatch table (`fields={}`, empty body) — the exact same broker event type
(`Jt1078SignalCommandRequested`) `video/infra/adapters.Jt1078RelayAdapter` already publishes for
live-video/playback signaling. **No new consumer, no new wire contract, no new event type on the
request side** — only one new dispatch-table entry, because `0x9003` is architecturally just
another JT/T 1078 A/V-family command sent over the terminal's already-open, already-authenticated
JT808 connection, identical in kind to `0x9101`/`0x9201`/`0x9205`.

### 6. Backend trigger: extends `DeviceConnectivityProcessor`, does not add a second `DeviceOnline` subscriber

`core.events.processor.EventProcessorRegistry` maps exactly one processor per `event_type`
(confirmed by reading it — `register()` overwrites). A second, separately-registered processor
for `"DeviceOnline"` would silently replace `DeviceConnectivityProcessor`, not run alongside it.
`DeviceApplicationService.record_device_seen` is therefore widened (previously always returned
`None`) to also set the `av_attributes_requested_at` guard — in the *same* transaction/commit as
`record_last_seen` — and return the device's own `terminal_id` when this transition should
trigger discovery, `None` otherwise. `DeviceConnectivityProcessor.process` publishes the broker
event only when a `terminal_id` comes back, via `container.try_resolve(BrokerPort)` (fails
silently, logged, when no broker is configured — matching every other optional-broker-dependency
in this codebase's own established posture).

### 7. Camera creation: new `DeviceAvAttributesReportedProcessor`, reusing `register_camera` as-is

A new processor (`fleet_device/events/subscribers.py`, registered for the new
`"DeviceAvAttributesReported"` event_type — a genuinely new subscription, since nothing else
consumes it) calls the *existing*, previously-unreachable `DeviceApplicationService.
register_camera` once per channel `1..max_video_channels`. **Idempotent by construction, not by
a pre-check:** `Device.register_camera`'s own `ux_cameras__device_channel` invariant already
raises `ConflictError` for a channel that exists — a replayed/duplicate `0x1003` report (device-
gateway restart, at-least-once broker delivery) simply finds every channel already registered
and moves on; the processor catches and logs `ConflictError`, nothing else.

## What this ADR does not do

- **Does not build a camera-editing UI or API.** Auto-discovered cameras get a generic
  `position=other`/`label="Channel N"` (Decision §2); renaming/repositioning one after discovery
  has no route today — a real, disclosed, pre-existing gap (`fleet_device/api/routers.py`'s own
  "Camera registration has an application use-case but no approved endpoint" comment), not
  created or closed by this ADR.
- **Does not route the JT1078 relay through nginx/Coolify.** Decision §3's rejected alternative;
  `docker/.env.example`'s dev default is explicitly flagged as unfit for production.
- **Does not re-diff `0x0200`'s own byte layout or add any other new JT/T808/1078 message.**
  Scope is exactly `0x9003`/`0x1003` plus the two backend-side processors named above.
- **Does not change how `POST /video/live`/`/playback` work.** Once a real `Camera` row exists
  (by any means — auto-discovery or, in principle, a future manual route), those routes already
  resolve it generically via `device.cameras` (`_resolve_camera_or_raise`) — no special-casing
  for an auto-discovered vs. hypothetically-manual camera.
- **Does not start `services/jt1078` by default in every environment** — it has no Compose
  `profile` gate (unlike `nginx`'s `gateway` profile), so a plain `docker compose up -d` with no
  service list already includes it; this ADR did not need to change that.

## Consequences

- **New `devices` column**, additive migration `7d3a9c1e5b42` (`av_attributes_requested_at`,
  nullable, no default) — mirrors `is_online`/`last_seen_at`'s own "connectivity/provisioning
  telemetry, not business state" shape exactly.
- **`DeviceApplicationService.record_device_seen`'s return type changes** from always-`None` to
  `str | None` — the one call site (`DeviceConnectivityProcessor`) is updated in the same change;
  no other caller exists (confirmed by search before changing the signature).
- **New Compose variable `JT1078_SIGNALING_URL`**, read into `RAAD_DEVICE_PLANE__
  JT1078_SIGNALING_URL` for `backend`/`migrate`/`worker` (the shared `x-backend-env` anchor).
  Any existing deployment's `docker/.env` that doesn't set it gets the dev-only default — a
  real deployment must set a real value before relying on live video.
- **A genuinely new wire message pair** (`0x9003`/`0x1003`) is now live in `device-gateway`,
  verified against the physical bench unit (see Verification, below) — this is new device-plane
  surface area, not a refactor of existing signaling.

## Verification

- Device-gateway: `tests/test_av_attributes.py` (encode/decode), `tests/test_av_attributes_
  handler.py` (handler correlation/session/publish behavior), `tests/test_pending_commands.py`
  (new `resolve_by_terminal_and_message`), `tests/test_redis_video_signaling_consumer.py`
  (new `query_av_attributes` dispatch-table entry) — 24 tests, all passing in isolation.
- Backend: `tests/unit/test_fleet_device_domain.py` (`record_av_attributes_requested`),
  `tests/unit/test_fleet_device_subscribers.py` (discovery-trigger publish behavior, camera-
  creation loop, idempotent-on-conflict behavior).
- **Live-verified against the physical `LSZ-C5804DG-Q-F` bench unit** (`terminal_id=
  00000000014482607571`, already JT808-registered/online from the prior session's diagnostic) —
  see this session's own verification transcript for the real `0x9003`→`0x1003` exchange and the
  resulting `Camera` rows.

## References

- `mdvrdocs/MDVR-808-1078-spec.pdf` §6.1.1/§6.1.2 Table 6.1 (new: `0x9003`/`0x1003`), §5.3.7
  Table 5.31 (channel-numbering convention consulted, deliberately not hardcoded — Decision §2).
- `docs/architecture/adr/0024-jt1078-video-relay-architecture.md`, `0025-jt808-2019-jt1078-2016-
  native-protocol-compliance.md` — the `Jt1078SignalCommandRequested` wire contract and JT/T1078-
  over-JT808 signaling architecture this ADR's Decision §5 reuses verbatim.
- `docs/architecture/adr/0020-platform-analytics-read-model.md` — `devices.is_online`'s own
  precedent for an additive, nullable, "connectivity telemetry" column shape.
- `docs/architecture/adr/0022-payment-provider-architecture.md` — the "environment variables,
  composition-root only, never hardcoded" precedent Decision §3 follows.
- `services/device-gateway/src/vendors/jt808/commands/av_attributes.py`, `handlers/
  av_attributes_handler.py`, `commands/pending_commands.py`, `commands/redis_video_signaling_
  consumer.py`, `server.py`.
- `backend/raad/modules/fleet_device/domain/entities.py` (`Device.record_av_attributes_
  requested`), `application/services.py` (`record_device_seen`), `events/subscribers.py`
  (`DeviceConnectivityProcessor`, `DeviceAvAttributesReportedProcessor`).
- `docker/docker-compose.yml`, `docker/.env.example` (`JT1078_SIGNALING_URL`).
