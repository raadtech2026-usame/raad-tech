# ADR-0036: Two-Way Intercom — Reversal of ADR-0035 and Implementation Design

## Status

**Accepted** (user directive, 2026-09-01: re-verify the ADR-0035 finding now that a real, unrelated
network misconfiguration has been found and fixed, then implement the full feature if the physical
result supports it — same "physical result is the authority" discipline ADR-0035 itself was built
under). Implemented same session.

## Context

Live Video was found completely broken (`docs/PROJECT_STATUS.md` §10, same session): the
JT1078 relay's own `JT1078_RELAY_PUBLIC_INGEST_HOST` (`docker/.env`) had gone stale after this
development machine's network changed (`192.168.10.210`, a different subnet than the machine's
real, current address, `192.168.100.63`) — every `0x9101` this deployment sent told the device to
stream to an address it could never reach. Fixed by correcting the `.env` value and recreating the
`jt1078-relay` container; Live Video was live-verified working, all 4 channels, immediately after.

**This is the same `server_ip` field ADR-0035's own bench test relied on.** Since intercom
(`0x9101 data_type=2`) uses the identical signaling path as live video, the corrected network path
was re-tested against intercom specifically, before writing any new code, per the user's own
explicit instruction not to assume and to prove the result with real decoded media, not an inferred
lifecycle event.

**The re-test, and why it is trustworthy evidence, not another inference from a session-activation
event (ADR-0035's own stated bar).** A standalone script (outside the repository, never committed)
bypassed the relay entirely — advertised its own raw TCP listener as the `0x9101` destination
instead of the relay's real ingest port — and decoded whatever the physical MDVR sent using this
repository's own, unmodified `services/jt1078/src/ingest/extended_rtp.py`/`frame_reassembly.py`
parser (imported, not reimplemented). With the Live Tracking page's own video viewers confirmed
stopped first (eliminating the channel-collision confound a first, contaminated attempt had
exposed — see below), the physical bench unit (`LSZ-C5804DG-Q-F`, terminal
`00000000014482607571`):

- Opened a real TCP connection to the advertised address within ~1 second of `0x9101` being sent.
- Streamed **2,364 real JT/T1078 extended-RTP frames over 80+ seconds, 100% `data_type=3`
  (audio), 0% video** — proving this is genuinely the audio-only intercom channel, not a
  misattributed ordinary A/V connection.
- Every frame: `body_len=320`, matching ADR-0033's own confirmed `audio_frame_length=320` for
  this exact unit's G.711A capability; correct SIM card number; correct logical channel;
  continuous ~25fps cadence with varying payload bytes consistent with real, live audio.
- Cleanly closed on `0x9102 control=4` (`result: 0`); the device remained connected, authenticated,
  and sending normal heartbeat/GPS traffic throughout and after — not destabilized.
- One honestly-disclosed anomaly: this particular attempt produced **no logged `0x0001` ack** for
  the `0x9101` itself (unlike every other attempt, this session's and ADR-0035's own) — the device
  executed the command and streamed media regardless. Ack presence is evidently decoupled from
  whether the media channel actually opens on this firmware, not a reliable go/no-go signal by
  itself.
- The downlink direction (RAAD → MDVR speaker) was probed with one hand-built, non-speech
  synthetic frame written back down the same socket after 3 real inbound frames — the device did
  not reject or disconnect, but this proves only transport tolerance, not audible playback (no
  physical presence at the vehicle to confirm).

**A first attempt, before the network fix's implication was isolated, produced a false positive**
— documented, not hidden: with the Live Tracking page's own video grid still actively cycling on
the same device, a `VideoSessionActivated` event fired for the intercom test session, but a
timestamp-level scan of the raw broker stream showed the frontend's own concurrent, ordinary
`data_type=0` channel-1 reconnect was what the device actually connected for — mis-attributed to
the intercom session by `session_manager.py`'s own already-documented `terminal_id`+
`logical_channel`-only matching ambiguity (real, pre-existing, same class of bug the module's own
docstring already names for the multi-camera-grid case). This is exactly why this ADR's own
evidence bar requires decoded, channel-collision-free media content, not a lifecycle event alone.

**Conclusion: this reverses ADR-0035's finding.** The most likely explanation is that the same
stale `server_ip` was the root cause of *both* symptoms — Live Video's total failure and
intercom's apparent unreliability — since both signal the device via the identical `0x9101` body
shape. `docs/architecture/adr/0035-two-way-intercom-bench-result.md` is left as the historical
record of that finding (this codebase's own convention: ADRs are not edited after the fact, a
later ADR is where a reader lands for the reversal — the same posture ADR-0025 established for
ADR-0009); `docs/PROJECT_STATUS.md` §10 Known Issue #22 is updated to point here.

## Decision

Implement the full feature, per the user's original request (`docs/architecture/RAAD_
DevicePlane_Architecture_v0_1_draft.md` §6.2's own long-standing, deferred design: "design the
media-plane seam now (session type `intercom`, same token/ceiling/audit machinery), build nothing
until a client surface is approved" — a client surface (this feature's own UI) is now approved).

### 1. `VideoPurpose` widened with `INTERCOM` — additive, mirrors ADR-0032's own precedent exactly

`video_sessions.purpose` is documented (Database Design §7.4) as `ENUM(live,playback)` only.
Widening it to add `intercom` is the identical "widen a native Postgres enum via an additive
migration, flagged in an ADR since no approved document enumerates the new value yet" pattern
ADR-0032 already established for `camera_position` — not a violation of the documented schema, an
extension of it, recorded here rather than silently assumed. `VideoSession.request_intercom` mirrors
`request_live` exactly (no `window_start`/`window_end`, same as LIVE).

### 2. One active intercom session per device, at both layers — a genuinely new invariant

Unlike ordinary video viewing (many simultaneous viewers of the same stream is correct), talking to
a bus is inherently exclusive — two operators must never talk over each other. Enforced twice,
matching this codebase's own tenant-isolation "defense in depth, not just one layer"
(`.claude/rules/security.md` #2's own precedent, applied to a different invariant): the backend's
`VideoApplicationService.request_intercom` rejects (`ConflictError`, 409) if any `REQUESTED`/
`ACTIVE` intercom session already exists for the device before ever calling the relay; the relay's
own `SessionManager.create_session` independently rejects a second concurrent `INTERCOM`-kind
session for the same `terminal_id` (`SessionCapacityExceededError`, mirroring ADR-0026 §8's own
ceiling-rejection shape) — a genuine race between two near-simultaneous requests is only reliably
serialized by the single in-process relay object, so the backend-level check alone is not
sufficient on its own.

### 3. RBAC — Org Admin (+ permitted RAAD staff) only, never Parent

New `video.intercom.start` permission, granted to exactly the same four roles that hold
`video.live.start` today (`founder`, `org_admin`, `regional_manager`, `support_staff`) —
**deliberately not granted to `parent`**, unlike live/playback's own narrow ADR-0026 exception.
The user's own request names "RAAD operator," never a parent-facing capability, and no approved
document (Project Brief §4.8, Phase 2/3.x) names parent intercom as in scope — extending D5's
Parent exception to intercom would be inventing a new authorization surface no design covers,
exactly what `.claude/rules/workflow.md` #8 forbids. `video.sessions.stop` (already held by all
four roles) is reused unchanged for stopping an intercom session — `VideoSession.end()` is already
purpose-agnostic, needing no new stop permission.

`interfaces/http/policy_guards.enforce_d5`/`resolve_d5_decision` need **no signature or logic
change** — called with `purpose="intercom"`, they resolve to `VideoAccessPolicy.evaluate`'s
existing role+scope check unchanged for every non-Parent caller (the same code path Org Admin/RAAD
staff already take for `purpose="live"`), and Parent can never reach the route at all: RBAC
(`require_permission(Permission("video.intercom.start"))`) rejects a Parent caller before D5 is
ever evaluated, since `parent` will never hold this permission. This is the same layered "RBAC =
may attempt, D5 = may succeed" split CR-1/D5 already use elsewhere, not a new mechanism.

### 4. `VideoProviderPort.start_intercom` — a new, narrow port method, not an overload of `start_live`

Mirrors `terminal_id`/`channel_no`/`audio_codec`'s own precedent for "a deliberate, minimal port
evolution, not a breaking redesign" (`application/ports.py`'s own module docstring, itself citing
ADR-0022). Distinct from `start_live` because intercom is bidirectional and returns **two** URLs
(a downlink viewer URL, reusing the existing WS-FLV viewer contract unchanged, and a new uplink
URL) rather than one — folding this into `start_live`'s single-`str`-return shape would either
silently drop the uplink URL or force every ordinary live-video caller to handle a return shape it
never needs. `Jt1078RelayAdapter.start_intercom` is the one, real implementation — it is also the
only call site that ever passes `data_type=2`; the pre-existing, deliberately-still-hardcoded
`"data_type": 0` line in `start_live` (ADR-0035's own explicit decision to leave alone) is
**unchanged** — ordinary live video keeps requesting `data_type=0` exactly as before, so this
feature cannot regress it.

### 5. Uplink transport: WebSocket + client-side G.711A encoding, not WebRTC, not server-side transcode

Matches the "WS + G.711 now, defer WebRTC" recommendation already reasoned through in this
session's own prior investigation report (Section 12/16): the confirmed device codec is G.711A
(ADR-0033); encoding it client-side in the browser (a well-documented, ~30-line ITU-T G.711
companding algorithm, no new dependency) avoids a second per-session `ffmpeg` process purely for
the uplink direction, keeping round-trip latency for a live conversation lower than ADR-0034's own
already-accepted downlink transcode latency (acceptable there because it feeds passive playback,
not a back-and-forth exchange). WebRTC (Opus, a real SFU dependency, echo cancellation) remains the
architecturally superior long-term choice for a lossy mobile network but is not justified spending
now that the actual blocker (device-side reliability) is resolved cheaply with the simpler
transport — revisit only if G.711A's own bandwidth/quality profile proves insufficient in practice.

**Reuses the existing, unmodified viewer WS-FLV connection for the downlink half** (the bus mic's
own audio, already fully working via the ADR-0034 G.711A→AAC pipeline — that pipeline dispatches
on `frame.is_audio` alone, with zero purpose-awareness, so an intercom session's audio frames
already flow through it with no relay change needed for that direction). **A second, new WS
connection carries the uplink half** — a session's viewer token is single-use
(`session/viewer_token.py`), so a second connection needs its own, independently-minted token;
`mint_token`/`verify_token_signature` gain an additive `role: "viewer" | "uplink"` field (old
2-key token payloads default to `"viewer"` on decode, fully backward compatible) rather than
inventing a parallel token scheme. `ViewerServer` branches on the verified role: `"viewer"` is
completely unchanged (broadcast registration, FLV delivery); `"uplink"` skips broadcast
registration entirely and instead reads binary WS frames from the browser, forwarding each
directly to a new `IngestConnectionRegistry` — a small `session_id -> live device ingest socket`
map, populated by `IngestServer` the moment a session's own device connection activates, torn down
when that connection closes — which wraps the raw G.711A bytes into a real JT/T1078 extended-RTP
audio frame (`ingest/extended_rtp.encode_audio_frame`, the tested mirror of the existing decoder)
and writes it down the *same* TCP socket the device is already streaming its own mic audio from,
reusing that device's own reported SIM card number and logical channel.

**Why not a second physical connection for uplink, mirroring the ingest/viewer split.** The device
only ever opens *one* media connection per `0x9101` request — Table 6.2 defines a single "channel"
concept per request, not a send port and a receive port; the bench test's own successful frame
stream and the earlier `0x9102 control=4` closing it cleanly both confirm the relationship is
1:1. Sending audio back down the identical socket the device is already using to send its own is
consistent with a conversational, full-duplex TCP stream — exactly what "two-way" implies — not
an invented second channel no evidence supports.

### 6. Frontend placement and UX

The Intercom control lives in `MultiCameraVideoPanel`'s own header, beside the existing Start/Stop
Live controls (device-level, not per-camera — matching the physical reality that `LSZ-M01` is one
intercom hardware module per vehicle, not one per camera). Defaults to the device's first camera's
`channel_no` as the wire `logical_channel` (the same value the successful bench test used) — a
disclosed simplification, not a claim that intercom is inherently tied to "camera 1" specifically;
no approved document names a distinct intercom-only channel number. Push-to-talk: the microphone
stream is captured once when the session starts (visible "connected" state), but frames are only
ever encoded and sent while the Talk button is actively pressed — matching the requirement to
"clearly show when the operator microphone is transmitting," never a silently-hot mic.

## What this ADR does not do

- Does not extend Parent's D5 exception to intercom — RBAC-excluded, not merely D5-gated, per
  Decision §3.
- Does not implement WebRTC, Opus, or any codec other than G.711A for the uplink.
- Does not add server-side echo cancellation/noise suppression — relies on the browser's own
  `getUserMedia` constraints (`echoCancellation: true` where supported) as a best-effort baseline,
  not a guarantee.
- Does not persist or record intercom audio anywhere — matches `.claude/rules/jt1078.md` #2
  ("RAAD is not a video archive") extended to audio; only control metadata (`video_sessions`) and
  the existing `audit_entries` trail (via the same `VideoSession` domain events every other purpose
  already produces) are persisted.
- Does not add a dedicated reconciliation job for a session stuck open with no relay lifecycle
  event ever arriving — the same disclosed, still-open gap ADR-0024 §16 already names for ordinary
  video, unchanged by this ADR.

## Consequences

- New additive migrations: `video_purpose` enum gains `intercom`; `role_permissions` gains
  `video.intercom.start` for four roles. Both follow this codebase's own established
  upgrade/downgrade round-trip discipline.
- `services/jt1078` gains its first genuine uplink (browser → device) media path — previously this
  relay only ever sent bytes to a browser, never accepted arbitrary bytes from one for forwarding
  toward a device. This is new, real engineering surface, tested accordingly (see Verification).
- `ViewerServer`'s WS connection handling gains a second, explicit branch (viewer vs. uplink role) —
  the existing viewer path's own tests and behavior are unchanged; a new test suite covers the new
  branch.

## Verification

- Backend: unit tests for `VideoSession.request_intercom`, `VideoApplicationService.
  request_intercom` (including the concurrency-conflict rejection), RBAC permission grant.
- Relay: unit tests for `extended_rtp.encode_audio_frame` (round-trips through the existing,
  unmodified decoder), `viewer_token.py`'s widened role field, `SessionManager`'s
  one-intercom-per-terminal rejection and its `control=4` stop-signal branch,
  `IngestConnectionRegistry`, `ViewerServer`'s uplink-role branch.
- Frontend: the G.711A encoder's round-trip fidelity, `IntercomControl`'s state-machine rendering.
- **Live-verified against the physical `LSZ-C5804DG-Q-F` bench unit** — see this session's own
  test transcript folded into `docs/PROJECT_STATUS.md` for the exact evidence (ack/no-ack pattern,
  decoded frame counts, both directions' results).

## References

- `docs/architecture/adr/0035-two-way-intercom-bench-result.md` — the finding this ADR reverses,
  left unedited as the historical record.
- `docs/architecture/adr/0032-camera-role-taxonomy-and-d5-cabin-exclusion-fix.md` — the enum-
  widening precedent this ADR's `VideoPurpose` change mirrors exactly.
- `docs/architecture/adr/0033-terminal-audio-capability-capture.md`,
  `docs/architecture/adr/0034-jt1078-audio-aac-transcode.md` — the confirmed G.711A codec facts and
  the existing downlink audio pipeline this ADR's downlink half reuses unmodified.
- `docs/architecture/adr/0026-parent-video-access-authorization.md` — the D5 chain and per-session
  concurrency-ceiling precedent this ADR's own concurrency check mirrors.
- `docs/architecture/RAAD_DevicePlane_Architecture_v0_1_draft.md` §6.2 — the original, long-deferred
  design proposal this ADR finally implements.
- `services/device-gateway/src/vendors/jt808/commands/video_signaling.py` — the already-generic
  `0x9101`/`0x9102` encoding this ADR's backend adapter is the first real caller of with
  `data_type=2`/`control=4`.
