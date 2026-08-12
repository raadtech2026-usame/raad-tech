# JT1078 Media Relay

On-demand live video and playback relay for bus MDVR cameras. RAAD is not a cloud video archive —
the MDVR remains the system of record; this service relays streams only when live monitoring or
playback is explicitly requested by an Organization Administrator. **Parents never receive live
video** (platform-wide invariant, D5).

Source of truth: `docs/architecture/adr/0024-jt1078-video-relay-architecture.md` (revised by
`docs/architecture/adr/0025-jt808-2019-jt1078-2016-native-protocol-compliance.md` §5), confirmed
against the supplier's own wire spec, `mdvrdocs/MDVR-808-1078-spec.pdf` §6.

**Runtime: Python 3.11+, asyncio, stdlib + `redis>=5.0` only** — see `pyproject.toml`'s own header
comment for the full evidence chain (device-plane sibling of `services/device-gateway`, same
deployment/Redis precedent, same "hand-roll a closed protocol at production quality" track record).
No new dependency was added for the ingest demux, FLV muxer, or the WS-FLV viewer server — all
three are hand-rolled against their own published/derived byte-format specs.

## Structure

```
src/
├── config.py, broker_config.py, logging_setup.py   # env-driven config, mirrors device-gateway
├── relay.py          # Jt1078Relay — the composition root / process entrypoint
├── ingest/           # extended_rtp.py (spec §6.2.1.1 demux), frame_reassembly.py
│                     # (subpackaged-frame reassembly), ingest_server.py (device-facing TCP)
├── session/          # video_session.py + session_manager.py (VSM: lifecycle, viewer count,
│                     # idle teardown, device stop-signal), viewer_token.py (D5 - signed,
│                     # single-use tokens)
├── repackager/       # flv_muxer.py — repackage-never-transcode FLV container muxing
├── viewer/           # websocket_server.py (hand-rolled RFC 6455), broadcast_hub.py
│                     # (per-viewer FLV timeline fan-out), viewer_server.py (token-gated entry)
└── events/           # session_events.py + publisher_port.py + redis_session_event_publisher.py
```

## Key rules

- Authorization happens in the Business API **before** any signaling — the Parent role has no code
  path that can allocate a media session or receive a stream token. This relay itself performs
  **no RBAC and no user authentication of its own** — it trusts exactly one thing, a short-lived
  signed single-use viewer token the Business API would mint (`session/viewer_token.py`).
- This service persists **no video, anywhere, under any code path** — no disk write, no Postgres
  write, no Redis write of media bytes. Only ephemeral session/viewer-token state lives in Redis
  (when configured); control metadata (`video_sessions`) lives in the Business API's own database.
- Signaling to the physical device is **native JT/T 1078 over the same JT/T 808 connection**
  `services/device-gateway` already holds (ADR-0025 §5) — this service never signals the device
  directly; it only receives the resulting media stream on its own ingest port, and coordinates
  start/stop with `device-gateway` over the shared Redis broker (`raad:events`).

See `.claude/rules/jt1078.md` and `.claude/rules/security.md`.

## Status

**Implemented and unit/integration-tested (no hardware), per the JT1078 implementation phase
(2026-08-11):**

- JT/T 1078 extended-RTP ingest demux + subpackaged-frame reassembly — spec-verified byte layouts.
- Session lifecycle (VSM): create → active → ended/failed, viewer-count tracking, idle-timeout
  and ingest-timeout sweeps, device stop-signal publish.
- Signed, single-use, session-scoped viewer tokens (HMAC-SHA256; in-memory or Redis-backed
  single-use guard).
- FLV container muxing (repackage-only) — video/audio tags, PreviousTagSize framing.
- Minimal hand-rolled WS server (RFC 6455 handshake + binary frames) for WS-FLV live delivery,
  token-gated, no RBAC of its own.
- Full ingest → repackage → viewer path proven end to end over real loopback sockets with
  synthetic extended-RTP frames.
- Redis-backed session-event publishing (`VideoSessionActivated`/`Ended`/`Failed`) and the
  device stop-signal (`Jt1078SignalCommandRequested`, consumed by `device-gateway`'s
  `RedisVideoSignalingConsumer`) on the shared `raad:events` stream.

**Explicitly not built this phase — see the implementation report for the full reasoning:**

- No Business-API-facing control endpoint (HTTP or otherwise) for actually requesting a session —
  session creation is a plain Python API (`Jt1078Relay.create_live_session`/
  `create_playback_session`) a future `VideoProviderPort` adapter would call; the transport
  between the Business API and this relay is not specified by any approved document yet.
- AVC/HEVC sequence-header (SPS/PPS → `AVCDecoderConfigurationRecord`) delivery — the muxer
  exposes the seam (`build_avc_sequence_header_tag`) but does not populate it from a real device's
  own parameter sets, which this environment has no hardware to observe.
- HLS (the playback transport ADR-0024 §14 also names) — live/WS-FLV only this phase.
- Never live-device-tested — every piece above is verified against the supplier's own written
  specification and synthetic byte fixtures, not a real `LSZ-C5804DG-Q-F` unit.
