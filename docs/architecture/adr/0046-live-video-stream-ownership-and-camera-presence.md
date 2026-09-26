# ADR-0046: Live Video Stream Ownership, Camera Presence and Main→Sub Fallback

## Status

**Accepted** (2026-09-26, user directive "comprehensive live video / MDVR architecture fix",
following the read-only production investigations of 2026-09-23 and 2026-09-25).

Amends ADR-0024 §5 (who signals the device), ADR-0036 (intercom stop semantics on a shared channel)
and ADR-0043 (how a stream-type change reaches the terminal). Those ADRs are not edited; a reader
following them forward lands here.

## Context

Production evidence (terminal `00000000014482607571`, relay/gateway logs and the `video_sessions`
table, 2026-09-18 → 2026-09-25):

1. **One software session per viewer owned a device-level resource.** Every `POST /video/live`
   produced its own `0x9101` and, on teardown, its own `0x9102`. A JT/T 1078 terminal keeps one
   live transmission per logical channel and `0x9102` carries only the channel, no session
   identity. The relay correlated an incoming media connection by SIM + channel and took the first
   matching session. When two users watched the same channel, the second session never received a
   connection, failed on `ingest_timeout`, and its `0x9102` closed the channel under the first
   user: 26 cross-user same-channel overlaps in 30 days, e.g. 2026-09-23 18:08:37.
2. **Two unordered publishers.** The Business API published `0x9101` after the relay RPC
   returned; the relay published `0x9102`. On every focus change the old session's stop reached
   the device *after* the new session's start (e.g. 2026-09-25 18:10:40.041 start ch3,
   18:10:40.343 stop ch3).
3. **Stopping live video closed the intercom.** Live teardown sent `0x9102` control 0 with close
   type 0, which the supplier specification (Table 6.4) defines as "close all audio and video of
   this channel". On 2026-09-25 18:11:56 a channel-1 live stop was acknowledged at .320 and the
   running channel-1 intercom's connection closed at .312–.313 (`ingest_disconnected`).
4. **The relay forwarded undecodable data.** A viewer joining mid-GOP received P-frames before any
   keyframe, and backpressure dropped single chunks (drop-oldest, 32 chunks ≈ 1 s of main stream),
   so a burst after a device-side gap corrupted H.264 until the next keyframe (614 dropped chunks on
   ch3 main, 2026-09-25 18:17–18:19).
5. **RAAD treated every reported channel as a camera.** Cameras are created for `1..N` from
   `0x1003`. The terminal has cameras on ch1 and ch3 only; ch2/ch4 stream a "no video" picture, so
   the wall requested, displayed and paid cellular data for two non-existent cameras.
6. **The main stream is fragile on this uplink** (ch1/ch3 main 1.6–2.3 Mbps; device-side lateness
   of 4–29 s and device-skipped keyframes on the cameras actually connected), while the sub stream
   (352×288 Baseline, 70–140 kbps) stays close to real time.

The supplier specification states the platform should validate "terminal online state, logical
channel, encoding capability, network reachability and service port" before requesting media, and
that "the terminal keeps the session state of one logical channel traceable" (§6 preamble).

## Decision

### 1. Camera presence comes from the terminal's own video-signal-loss report

`0x0200` additional-information item `0x15` ("视频信号丢失报警状态", Table 5.11) is a DWORD whose
bit *n−1* is set when logical channel *n* has lost its video signal. Captured from this terminal on
2026-09-19: `0x15 = 0x0000000A` on every report, i.e. ch2 and ch4 have no signal, ch1 and ch3 do.

- `device-gateway` decodes the additional-information item list and publishes
  `DeviceVideoSignalStatusReported` (loss mask, occlusion mask `0x16`) when the mask changes, on the
  first report of a connection, and at most every 5 minutes otherwise.
- `fleet_device` stores the latest report per device in Redis (`CameraSignalStatePort`, the
  ADR-0044 §2 pattern for device-reported, volatile state shared by worker and API), kept for 30 days: the
  last report stays the answer across outages and the first report after a reconnect corrects it
  (amended 2026-09-26 after a 30-minute TTL showed all four channels as `unknown` when the terminal
  came back from a long outage). **No schema change.**
- Every `CameraDTO` carries `video_signal`: `present`, `absent` or `unknown` (no report yet, or
  none for 30 days). The web view re-checks every 10 s while any camera is `unknown`. `unknown` behaves exactly as before this ADR.
- `POST /video/live` refuses a camera whose signal is `absent` (409 `CAMERA_NOT_CONNECTED`) before
  any relay or device call, so hiding a tile is never the only protection. Intercom and playback
  are not gated: audio does not depend on the video input, and recordings predate the loss.
- The terminal cannot distinguish "never installed" from "cable cut"; both are shown as
  "Camera not connected". A camera connected later clears its bit on the next `0x0200` (≈20 s) and
  appears without any code or configuration change.

### 2. The relay owns device streams; sessions are viewers

- A **device stream** is keyed by `(terminal, logical channel, kind)`, kind ∈ {`live`, `intercom`},
  and owned by the relay. Playback streams are exclusive to their session (a playback window is not
  shareable).
- A **session** (the Business API's `VideoSession`, with its own single-use viewer token) attaches
  to a device stream. Viewers of all sessions of one stream share one ingest connection and one
  broadcast hub; each viewer keeps its own FLV muxer and send queue.
- `0x9101` is sent only when a stream starts. `0x9102` is sent only when the stream stops, which
  happens when its **last** session has been gone for `stream_linger_seconds` (default 5 s, so a
  focus swap or a reconnect reuses the running stream), or when the device stops delivering
  (ingest timeout, stall, disconnect) — in which case every attached session ends with that reason.
- Ending one session (explicit stop, viewer idle) detaches it and closes only its own viewers.
- One live stream per channel: the terminal's stream-type byte selects main *or* sub. The stream
  runs **main if any attached session wants main, otherwise sub**. An upgrade restarts the stream
  immediately; a downgrade waits `stream_linger_seconds`. A viewer that falls back to sub therefore
  never downgrades another viewer who still wants main. Whether this terminal can transmit main and
  sub of one channel simultaneously is unverified; this design does not depend on it.

### 3. One ordered command path, stamped with a generation

- The relay publishes **every** device command for live, intercom and playback (`0x9101`, `0x9102`,
  `0x9201`, `0x9202` stop) through one FIFO queue drained by a single task, onto the existing
  `Jt1078SignalCommandRequested` broker contract. `device-gateway` forwards that stream in order on
  the terminal's single JT/T 808 connection, so the terminal sees commands in the order the relay
  decided them. The Business API no longer publishes starts (it still publishes recording search
  and playback control, which never race a stop).
- Each stream start increments the stream's **generation**. A stop is issued for exactly the
  generation it tears down and is always queued *before* the next generation's start, so a late stop
  can no longer arrive after a newer start. A restart (stream-type change) is stop(g) → start(g+1)
  with the viewers left attached; their muxers resynchronise on the next keyframe.
- Compatibility during a rolling deploy: the Business API sends `relay_signals_device: true`; a relay
  without this ADR ignores it and the Business API, seeing no `device_signaled` in the response,
  publishes the start itself as before. A new relay receiving a request without the flag does not
  signal, so no start is ever sent twice.
- Starts on one `(terminal, channel)` are serialised: while one stream of that channel is waiting
  for its media connection (up to 10 s), another stream's start on the same channel waits. The next
  unattributed connection on the channel therefore belongs to exactly one stream. A connection on a
  running stream supersedes that stream's older connection.

### 4. Live video and intercom are independent streams on a shared channel

- Intercom (`0x9101` data type 2) and live A/V (data type 0) are separate device streams with
  separate connections, sessions and hubs.
- Stopping intercom sends `0x9102` control 4 (close intercom) — unchanged.
- Stopping live video while an intercom stream is active on the same channel sends `0x9102`
  control 0 with **close type 2** ("close video only, keep audio", Table 6.4); otherwise close type 0
  as before.

### 5. Keyframe-aware delivery

- `ReassembledFrame.data_type == 0` (JT/T 1078 Table 6.3, "I frame") is the keyframe signal.
- A viewer starts in *awaiting-keyframe*: it receives the FLV header, then the current GOP cached by
  the hub (last keyframe and the frames since, bounded by 2 MB), then live frames. It never receives
  a P-frame without the preceding keyframe.
- A viewer's send queue is bounded by bytes (1.5 MB) and age (2 s). On overflow the queue is
  flushed and the viewer resynchronises on the next keyframe, instead of dropping single chunks.
- A stream restart clears the GOP cache and resynchronises every viewer.
- Stuck-viewer protection (93ded1b) now means "has had data queued and delivered nothing for
  `viewer_stuck_timeout_seconds`". A slow viewer that still drains is resynchronised, never closed.
  Intercom stays exempt.

### 6. Main → sub fallback is per viewer, in the browser

The browser is the only place that can see playback: position, stalls, buffered latency. Each tile
controller that wants main:

- samples health every second after a 10 s warm-up: unhealthy when the picture is frozen or the
  buffered latency exceeds 3 s;
- falls back to sub after 8 unhealthy samples in the last 20, or when a main-stream session ends
  unexpectedly after recent unhealthy samples, which covers a relay stuck-viewer close;
- holds sub for 2 minutes, then probes main; a probe that degrades within 60 s doubles the hold
  (cap 30 minutes); 5 healthy minutes on main reset it;
- labels the tile "SD" while fallen back.

The relay's 30 s stuck-viewer close remains the backstop for a browser that stops reading
entirely; the browser falls back well before it fires.

## Consequences

- Two users on one channel share one device stream: the device sends one copy, and neither user can
  stop the other's video.
- A focus swap costs one restart of one stream (stop then start, in order) instead of two unordered
  session teardowns and starts.
- Channels without a camera cost no requests and no uplink.
- Viewers join at a keyframe; a slow viewer skips to the next GOP instead of receiving corrupt video.
- The relay now decides when the device starts streaming, so a relay outage also prevents starts
  (it already prevented viewing).

## Amendments after the production audit (2026-09-26)

- **Offline terminal fails fast.** When the device-gateway cannot deliver a start because the
  terminal has no connection it publishes `DeviceCommandResult(reason="device_offline")`; the relay
  now consumes it (`session/command_result_consumer.py`, consumer group
  `jt1078-relay-command-results`) and fails that stream's sessions at once with `device_offline`,
  sending no stop. Previously it waited the 30 s ingest timeout. The gateway logs such a command as
  `video_signal_command_not_delivered`, not `..._forwarded`.
- **Recovery never strands a tile.** A tile that has used its automatic reconnect attempts offers
  Retry; a manual start restores the budget.
- **A session is controlled by its requester.** Stop and playback control return 404 to any other
  user (the system actor excepted), since the route's tenant/D5 checks admit the whole organization.
- **Camera report kept 30 days; a joining session is activated only on delivered media** (see §1 and
  the activation note in `session_manager.create_session`).

## Not verified here

- Terminal behaviour for `0x9102` close type 2 on this firmware (specification-defined, not
  bench-tested).
- Browser handling of a mid-session resolution change after a stream restart with an existing viewer
  (mpegts.js receives a new AVC sequence header).
- The relationship between the 0x15 mask and a camera that has video but a failed sensor.
- The device's own main-stream resolution/bitrate/GOP settings (terminal offline during this work).
