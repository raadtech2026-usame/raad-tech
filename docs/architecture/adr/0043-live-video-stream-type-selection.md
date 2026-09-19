# ADR-0043: Live Video Stream Type Selection (Sub Stream for the Multi-Camera Grid)

## Status

**Accepted** (2026-09-19, user directive following the 2026-09-18 production forensic check of
terminal `00000000014482607571` on a Somtel SIM).

## Context

`Jt1078RelayAdapter.start_live` has always sent `0x9101` with stream type `0` (main stream), for
every live session. The Live Tracking video wall opens one live session per camera, so a
four-camera MDVR streamed four full-resolution main streams at once over a single 4G uplink.

Production evidence from 2026-09-18 (relay logs and container counters, read-only):

- The relay received about 442 MB during roughly 376 s of four-camera viewing: about 9.4 Mbps of
  sustained uplink from one bus.
- Channels 1 and 3 repeatedly arrived 2–10.6 s behind their own device timestamps, with holes of
  3–8.2 s where the terminal sent no frames and bursts of back-to-back I-frames 40 ms apart. At the
  same instants channels 2 and 4 never exceeded 0.4 s. The relay's socket queues were empty, and it
  retransmitted 5 of 342k segments: the delay built up on the terminal's side of the uplink.
- The player's frozen-picture detector (3 s) turned those holes into "No signal" on channel 3.

JT/T 1078 terminals encode every channel twice: a main stream (recording quality) and a sub stream
(low bitrate, intended for remote preview). Table 6.2 of the supplier specification
(`mdvrdocs/MDVR-808-1078-spec.pdf`) carries the choice as the `0x9101` stream-type byte.

## Decision

1. `POST /video/live` accepts an optional `stream_type`, `"main"` or `"sub"`, defaulting to
   `"main"`. The documented `{device_id, camera_id}` body and its behavior are unchanged, so the
   mobile app and any other existing caller are unaffected. The API never exposes the protocol
   integer; `Jt1078RelayAdapter` alone maps `main`→`0`, `sub`→`1`.
2. `LiveStreamType` lives beside `VideoProviderPort` (`video/application/ports.py`) and is threaded
   `RequestLiveVideoRequest` → `RequestLiveVideoCommand` → `VideoProviderPort.start_live`, the
   same narrow, additive port widening `terminal_id`/`channel_no`/`audio_codec` already used. It is
   a request-time choice and is not persisted on `VideoSession`.
3. The web video wall requests `sub` for every tile in the grid and for focus-mode thumbnails, and
   `main` for the focused camera and for a vehicle with a single camera. Changing focus restarts
   only the tile whose stream type changed. The single-camera `/org/video` page and intercom keep
   `main`. Playback is unchanged.

## Consequences

- A four-camera wall costs the uplink four sub streams instead of four main streams, which is what
  the sub stream exists for; a camera needs the uplink for its main stream only while it is focused.
- Focusing or unfocusing a camera restarts that one session, so its tile shows "Connecting" for the
  normal session start-up time (1.5–4.7 s measured on 2026-09-18). The rest of the wall is untouched.
- The sub stream's resolution and bitrate are terminal configuration, not RAAD configuration. A
  terminal whose sub stream is disabled answers `0x9101` with a failure for `stream_type=1`; that
  surfaces as a failed session exactly like any other refused request, and is fixed on the MDVR.
- Switching an existing session between streams with `0x9102` control 1 was considered and not
  chosen: it needs a new API route and a relay/player path for a mid-stream resolution change
  (a new AVC sequence header), none of which exists; a restart reuses the tested start path.
