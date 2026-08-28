# ADR-0033: Terminal Audio Capability Capture

## Status

**Accepted** (user directive, 2026-08-27: bench-test-first, then implement audio support and lay
future-ready groundwork for intercom, without assuming a specific codec or inventing hardware
capabilities). Implemented same session; **physically verified against the real bench MDVR the
same day** — see Verification below.

**Physical-hardware-confirmed vs. protocol-supported-but-unverified — a distinction this ADR
keeps explicit, not blurred:** the real `LSZ-C5804DG-Q-F` bench unit has now *confirmed*, live,
its own audio capability report and its 4-channel video/audio capacity (Verification, below).
**DMS, ADAS, and intercom remain protocol-supported-but-hardware-unverified** — nothing in this
ADR exercises them against real hardware, and none is implemented: `supports_audio_output=true`
is a real, physically-confirmed *fact* about this unit, not a working intercom; the taxonomy
values `driver_facing`/`front`/`rear`/`left`/`right` (ADR-0032) remain reserved, unassigned to
any real camera. This ADR does not close that gap and is not represented as doing so anywhere
below.

## Context

`services/device-gateway/src/vendors/jt808/commands/av_attributes.py`'s `parse_av_attributes_
report` already parses the terminal's full `0x1003` reply body (`mdvrdocs/MDVR-808-1078-spec.pdf`
§6.1.2 Table 6.1, ADR-0030) into `AvAttributesReport` — nine fields, including
`input_audio_codec`/`input_audio_channels`/`input_audio_sample_rate`/`input_audio_sample_bits`/
`audio_frame_length`/`supports_audio_output`/`video_codec`. ADR-0030's own
`DeviceAvAttributesReported` event, published from that parsed report, was a deliberate narrower
projection carrying only `max_video_channels`/`max_audio_channels` — correct when written ("no
approved use-case reads those yet"), but it meant the terminal's real audio capability was parsed
once and then discarded on every device, forever: confirmed live, 2026-08-27, that the bench
terminal's own `av_attributes_requested_at` was already set from a 2026-08-19 exchange, but no
trace of its audio fields survived anywhere past `av_attributes_handler.py`.

The user's own instruction for this phase is explicit on two points this ADR must not violate:
**do not assume AAC** (or any other specific codec) and **do not invent hardware capabilities**.
Table 6.1's own codec/sample-rate/sample-bit fields are single-byte enum codes (Table 6.21 in the
same spec defines the code space) — no approved document in this repository maps every one of
those codes to a human-readable name, so this ADR records them as opaque wire values, exactly as
reported, never decoded or assumed.

## Decision

### 1. `AudioCapability` — a frozen value object recording the wire report verbatim

Seven raw fields (`codec`, `channels`, `sample_rate`, `sample_bits`, `frame_length`,
`supports_output`, `video_codec`), all-or-nothing: a `Device` either has no `AudioCapability` yet
(no real `0x1003` report received) or one fully populated from a single real report — never
partially populated, never merged field-by-field across two reports. **Device-level, not
camera-level** — `0x1003` reports `max_audio_channels` independently of `max_video_channels`;
this codebase does not assume a 1:1 audio-to-video-channel mapping, and this ADR does not
introduce one.

### 2. `Device.record_audio_capability` — a wire fact, not a business decision

Mirrors `record_av_attributes_requested`'s established shape exactly: no lifecycle-state check,
no domain event recorded, no `updated_at` bump — a durable record of what device-gateway already
observed on the wire, not a state transition this aggregate is deciding. Always overwrites
outright (never merges) — the terminal's own most recent report is always the current truth,
e.g. after a firmware update changes its reported capability.

### 3. Event widened end-to-end: `DeviceAvAttributesReported` now carries the full report

`services/device-gateway`'s `DeviceAvAttributesReported` dataclass gains all seven audio/video
fields (previously `max_video_channels`/`max_audio_channels` only); `publisher_port.
LoggingEventPublisher` and `redis_event_publisher._fields_for` are both updated so the widened
event doesn't hit the existing `TypeError` fallthrough or vanish silently — the exact two failure
modes ADR-0030's own Consequences section already names as the risk of forgetting this step.
`av_attributes_handler.py`'s own `av_attributes_reported` log line is raised from `DEBUG` to
`INFO` (was invisible at this deployment's default log level, compounding the original
field-discard bug — this fires once per device's lifetime, ADR-0030's own idempotency guard, the
same significance level as `authentication_succeeded`).

### 4. Backend: a new, independent processing branch on the existing `0x1003` subscriber

`DeviceAvAttributesReportedProcessor` (already the ADR-0030 camera-discovery consumer) gains a
second, independent branch: when every one of the seven audio fields is present in the event
payload (checked with `is not None`, never truthiness — `0` is a valid codec/sample/byte value
and `False` is a valid `supports_audio_output`), it builds an `AudioCapability` and calls the new
`DeviceApplicationService.record_audio_capability` (mirroring `record_auth_key_hash`'s identical
no-op-on-unknown-device shape) through a new `RecordAudioCapabilityCommand`. This is additive to,
not a replacement of, the existing camera-registration loop in the same processor — a replayed or
partial report still registers cameras correctly even if (hypothetically) the audio branch were
ever skipped.

### 5. Persistence: seven new nullable columns on `devices`, purely additive

`audio_codec`, `audio_channels`, `audio_sample_rate`, `audio_sample_bits`, `audio_frame_length`,
`supports_audio_output`, `video_codec` (migration `3aef3f7c7bb1`). `infra/mappers.py`'s
`device_to_model`/`model_to_device` round-trip `AudioCapability` as one unit — all seven columns
are set together or left `NULL` together, matching the value object's own invariant.
**Not exposed on `DeviceDTO` this phase** — the same posture `av_attributes_requested_at` already
has (internal/telemetry field, no HTTP route surfaces it yet); adding API surface for it without
an approved consumer would be scope this ADR doesn't need.

## What this ADR does not do — future-ready, not physically verified

- **Does not build an intercom / two-way audio feature.** `supports_output` is captured because
  it is a real field the terminal already reports — knowing whether a given unit's hardware
  supports outbound audio is the prerequisite fact any future PA/intercom command would need, but
  no downlink audio command, no new JT808 message, and no streaming path is added here. This is
  disclosed groundwork, not a claim that intercom works.
- **Does not decode `codec`/`video_codec` to a name.** Table 6.21's 28-entry codec enum is not
  mapped anywhere in this codebase; every consumer of `AudioCapability` sees the raw wire byte.
  **Does not assume AAC or any other specific codec** — per the user's explicit instruction.
- **Does not touch JT1078 media repackaging.** `services/jt1078`'s FLV muxer / audio track
  handling (if any is added later) is a separate, future capability — this ADR only makes the
  terminal's *reported* capability visible to the backend; it does not change how (or whether)
  audio is currently repackaged or delivered to a viewer.
- **Does not add an HTTP route or surface `audio_capability` on `DeviceDTO`.**

## Consequences

- **Two new columns of information now survive**, where before they were parsed and immediately
  discarded: this closes a real, confirmed information-loss bug (the bench terminal's own
  2026-08-19 exchange left no trace), not merely an unimplemented feature.
- **`DeviceAvAttributesReported`'s wire shape changes** (device-gateway → backend) — both known
  producers (`LoggingEventPublisher`, `RedisEventPublisher`) are updated in the same change,
  mirroring the exact "all three call sites, not just the one that crashes first" lesson
  ADR-0030's own Consequences section already recorded for this same event.
- **No behavior change for camera discovery** — the audio-capture branch is additive; a device
  with a partial or malformed audio segment (should the wire report ever be malformed) simply
  skips audio capture for that report while camera registration proceeds unaffected.

## Verification

- Device-gateway: `tests/test_av_attributes.py`, `tests/test_av_attributes_handler.py` — both
  pass unchanged against the widened event (the underlying `AvAttributesReport` parsing was
  already complete pre-ADR-0030; this ADR only widens what's published from it). Full
  device-gateway suite: 431 passed.
- Backend: `tests/unit/test_fleet_device_domain.py` (`record_audio_capability` sets verbatim,
  overwrites rather than merges, emits no domain event, does not bump `updated_at`, works
  regardless of lifecycle state), `tests/unit/test_fleet_device_application.py`
  (`RecordAudioCapabilityTests` — persists and commits, no-ops for an unknown device),
  `tests/unit/test_fleet_device_subscribers.py`
  (`DeviceAvAttributesReportedProcessorAudioCaptureTests` — full-payload capture, `0`/`False`
  fields are not treated as missing, a missing audio field skips only audio capture, not the
  pre-existing camera-discovery loop).
- Full backend `tests/unit` + `tests/architecture`: 1458 passed, 15 subtests passed.
- Full backend `tests/integration` (real PostgreSQL, migration `3aef3f7c7bb1` applied): the
  `fleet_device` device round-trip suite (previously failing with `UndefinedColumnError:
  column "audio_codec" of relation "devices" does not exist` before this migration was written
  and applied) now passes in full.
- **Physically verified against the real `LSZ-C5804DG-Q-F` bench unit, 2026-08-27**
  (`terminal_id=00000000014482607571`), after this session's own device-gateway/worker rebuild
  put this ADR's code live: real JT808 registration (`0x0100`, result `success`) →
  authentication (`0x0102`, `authentication_succeeded`) → `device_online` → the
  `av_attributes_requested_at` guard (reset to `NULL` for this test) correctly re-triggered a
  fresh `0x9003` query → a real `0x1003` reply, captured with these exact wire values:

  | Field | Value |
  |---|---|
  | `max_video_channels` | 4 |
  | `max_audio_channels` | 4 |
  | `input_audio_codec` | 6 *(raw wire byte, not decoded — see Context)* |
  | `input_audio_channels` | 1 |
  | `input_audio_sample_rate` | 0 *(raw byte, not decoded)* |
  | `input_audio_sample_bits` | 1 |
  | `audio_frame_length` | 320 |
  | `supports_audio_output` | `true` |
  | `video_codec` | 98 *(raw wire byte, not decoded)* |

  Persisted correctly and idempotently: all seven `devices.audio_*`/`video_codec` columns now
  hold these exact values (`updated_at` advanced to the write), and the same `0x1003` reply's
  channel count (`max_video_channels=4`) was processed against the 4 `Camera` rows already
  created on 2026-08-19 — each logged `camera_channel_already_registered` and was **not**
  duplicated, confirming `register_camera`'s idempotency invariant holds identically for a
  live re-query, not just a synthetic/replayed one.

  **One operational note, not a hardware-capability finding:** the *first* automatic query this
  session (published `2026-08-27T20:32:43Z`, immediately after the guard reset) received no
  `0x1003` reply in the following ~49 minutes, despite the device staying continuously
  connected and sending GPS/heartbeat traffic throughout that window. A manual re-publish of the
  identical `query_av_attributes` request (`2026-08-27T21:32:40Z`) received a real reply in
  **~19ms** — as fast as the two genuine round-trips this same device already completed on
  2026-08-19. Device-gateway logged no error on either attempt (`RedisVideoSignalingConsumer.
  run_forever`'s own exception-catching wrapper, which does log at ERROR on any real failure,
  never fired), so the most likely explanation is a single dropped/unanswered application-layer
  message on the device side — not a protocol, implementation, or hardware-capability gap. This
  ADR's own code is not implicated: the identical request succeeded on retry with no code change
  in between.

## References

- `mdvrdocs/MDVR-808-1078-spec.pdf` §6.1.2 Table 6.1 (the `0x1003` body), Table 6.21 (codec enum
  space, deliberately not decoded here).
- `docs/architecture/adr/0030-automatic-camera-channel-discovery.md` — the original `0x9003`/
  `0x1003` implementation and `DeviceAvAttributesReported`'s own prior narrower-projection
  rationale, widened by this ADR; also the source of the "update every publisher, not just the
  one that crashes first" lesson this ADR follows.
- `services/device-gateway/src/vendors/jt808/commands/av_attributes.py` (pre-existing full parse,
  unchanged), `handlers/av_attributes_handler.py`, `src/events/device_av_attributes_reported.py`,
  `src/events/publisher_port.py`, `src/events/redis_event_publisher.py`.
- `backend/raad/modules/fleet_device/domain/value_objects.py` (`AudioCapability`),
  `domain/entities.py` (`Device.record_audio_capability`), `application/commands.py`/
  `services.py` (`RecordAudioCapabilityCommand`), `events/subscribers.py`
  (`DeviceAvAttributesReportedProcessor`), `infra/models.py`, `infra/mappers.py`.
- `backend/migrations/versions/20260827_1530_3aef3f7c7bb1_fleet_device_audio_capability.py`.
