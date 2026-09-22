# ADR-0044: MDVR Recording Playback — Search, Start, Control (the MDVR stays the archive)

## Status

**Accepted** (2026-09-22, user directive following the 2026-09-22 playback investigation:
"Playback video should NOT be uploaded to or permanently stored on the RAAD VPS").

## Context

Operators need to watch video the MDVR already recorded on its own SD/HDD. The obvious
implementation — have the terminal upload files to the platform and serve them — is explicitly
rejected by the product requirement above, and it would also make the VPS a video archive, which
`.claude/rules/jt1078.md` #2 ("RAAD is not a video archive") already forbids for live media.

JT/T 1078 supports exactly the wanted shape: the terminal *streams* a recording over the same
extended-RTP media channel live video uses, on demand, from its own storage. The device-plane
already implements every message this needs (`services/device-gateway/src/vendors/jt808/commands/
video_signaling.py`, built for ADR-0024/0025 and never exercised above the gateway):

| Message | Direction | Purpose |
|---|---|---|
| `0x9205` | platform → terminal | query the recording list for a channel and time window |
| `0x1205` | terminal → platform | the matching segments (channel, start, end, alarm flag, type, size) |
| `0x9201` | platform → terminal | start streaming a recording to an address/port |
| `0x9202` | platform → terminal | control it: pause, resume, stop, fast-forward, seek |

The relay already accepts a `PLAYBACK` session (`session_request_server._create_playback_session`),
correlates the device's media connection to it exactly as for live, and on teardown already sends
`0x9202` control 2 (`SessionManager._signal_device_stop`). `POST /video/playback` (`0x9201`) has
existed since ADR-0024 and is unchanged by this ADR.

**What was missing is the two ends: finding out what recordings exist, and controlling playback
once it runs.** Neither has a transport problem — both are ordinary JT/T 808 commands — but the
*search* has a shape problem: the answer arrives asynchronously, from the device, over the broker,
long after the HTTP request that asked for it has returned.

## Decision

### 1. No recorded video is ever stored on the VPS

Playback media takes the identical path as live: terminal → relay ingest (7910) → in-memory
reassembly and FLV repackaging → the existing WS-FLV viewer socket → browser. Nothing is written
to disk, and the JT/T 808 file-upload command (`0x9206`, which *would* copy files to a server) is
deliberately not implemented. The only buffering is what live already has: one frame being
repackaged plus the bounded per-viewer send queue, discarded when the session ends.

### 2. Recording search is asynchronous, with a short-lived result cache — not a new table

`POST /video/recordings/search` mints a `search_id`, publishes the `0x9205` request with that id as
its correlation id, and returns `202 {search_id, status: "pending"}`. The terminal's `0x1205`
reply reaches the backend as the gateway's existing `DeviceResourceListReported` event; a new
processor stores the segments under that `search_id`. `GET /video/recordings/search/{search_id}`
returns `{status: "pending" | "ready", segments}`.

The result lives in **Redis with a 15-minute TTL** (`RecordingSearchResultPort`), not in
PostgreSQL. A recording list is a *momentary fact about the device's own storage*, not a RAAD
record: persisting it would create a second, immediately-stale copy of the MDVR's archive index
and invite exactly the "VPS becomes the archive" outcome this ADR exists to prevent. No migration,
no schema change. A search whose result has expired is simply searched again.

Redis is a hard dependency for search only. Without it the port is unbound and the route fails
loudly (`NotImplementedError` → 500), the same "fail loudly, don't fake it" posture
`VideoProviderPort` itself has — never a silently empty recording list.

### 3. Tenancy is re-checked on read, not inherited from the search id

The cached entry carries the `organization_id` and `device_id` it was created for.
`GET .../search/{search_id}` compares the caller's own scope against that stored value and answers
`404` (never `403`) on a mismatch, matching this codebase's established cross-tenant
probing-avoidance convention. A `search_id` alone is therefore not a capability.

### 4. Playback control is one route, mapping to `0x9202`

`POST /video/sessions/{id}/playback-control` with `action` ∈ `pause | resume | fast_forward |
keyframe_reverse | seek | keyframe_only`, plus `speed` (1–5 → 1/2/4/8/16×) and `position` where the
action needs them. Stopping keeps using the existing, purpose-agnostic
`POST /video/sessions/{id}/stop`; there is deliberately no second way to stop a session.

### 5. Permissions reuse `video.playback.start`; D5 is unchanged

Searching a device's recordings and controlling a playback session are the same capability as
starting playback, so both reuse the existing, already-granted `video.playback.start` permission,
and both call `enforce_d5(purpose="playback")` exactly as `POST /video/playback` does. This
deliberately avoids inventing a permission string no migration grants — the "a permission string
is not a grant" lesson this repository already paid for once (ADR-0040's unreachable Reports).
Parent access continues to depend on that parent's own `has_video_playback_access` grant plus
child/device ownership, unchanged from ADR-0026.

### 6. Bounds

Concurrent playback sessions are bounded by the relay's existing global and per-organization
session ceilings (ADR-0026 §8) — playback sessions are ordinary sessions there. Stuck viewers are
disconnected by the 2026-09-22 stuck-viewer policy, which applies to playback exactly as to live,
so an abandoned playback tab stops costing the device's uplink.

## Consequences

- The MDVR remains the system of record for recorded video. RAAD is control plane plus relay.
- A search costs one `0x9205`/`0x1205` round trip over the cellular link; results are cached for
  15 minutes so paging through them re-reads Redis, not the device.
- Playback bandwidth equals live for the same stream type (~0.16 Mbps sub, ~1.5 Mbps main).
- The device plane needs **no change at all** — every message was already implemented and tested.
- Seek/fast-forward availability is firmware-dependent: the terminal answers `0x9202` with an
  ordinary `0x0001` result, and a refusal surfaces as a failed command, not as a RAAD error.
- Untested against hardware at the time of writing: the MDVR has been offline since 2026-09-20 and
  reports storage faults on 3 of its units, so whether this unit has recordings at all is unknown.
  Every layer below is covered by unit tests against fakes; none of it is hardware-verified yet.
