# ADR-0035: Two-Way Intercom — Real Bench Result and Scope Decision

## Status

**Accepted** (user directive, 2026-08-28: "IMPLEMENT TWO-WAY INTERCOM END-TO-END... FIRST:
perform a real bench test... Use the physical result as the authority... If it fails, document
the exact response and implement only the protocol/software groundwork that is safe and
justified; do not create a fake workaround"). This ADR records that bench test and the resulting,
narrowed scope decision — not the full feature build the initial request described, because the
physical result did not support it (see Decision below).

## Context

The user asked for a complete two-way intercom feature (dedicated permission, D5 authorization,
audit, browser push-to-talk, bidirectional audio relay, session states, full tests) — but gated
implementation on a real bench test against the physical bench MDVR (`LSZ-C5804DG-Q-F`, terminal
`00000000014482607571`, firmware `TTY3521DV200-A251110`), explicitly forbidding assuming the
documented JT/T 808 two-way-intercom message (`0x9101` with `data_type=2`) actually works on this
firmware.

**The wire protocol already generically supports this** — no new protocol code was needed to run
the test. `services/device-gateway/src/vendors/jt808/commands/video_signaling.py`'s
`LiveVideoRequest.data_type` (Table 6.2) already documents value `2` as "two-way intercom" and
`LiveVideoControl.control` (Table 6.4) already documents value `4` as "close intercom" — both
built during the JT1078 video-signaling phase (ADR-0024/0025) as a generic, complete encoding of
every value the spec's own tables define, not something scoped down to only the values live video
happened to use. The **only** hardcoded value found anywhere in this call path is one line in
`backend/raad/modules/video/infra/adapters.py` (`Jt1078RelayAdapter.start_live`):
`"data_type": 0,  # 0 = A/V, spec Table 6.2` — the literal thing the user's own instruction #4
("pass data_type=2 instead of hard-coded 0") refers to.

## The bench test

Five independent, real attempts were run against the live, connected physical unit, each firing
an actual `0x9101` (`data_type=2`) over the device's real, already-authenticated JT/T 808
connection — via the same production wire mechanism live video already uses (a
`Jt1078SignalCommandRequested` event published onto the real `raad:events` broker stream,
consumed by the real, unmodified `RedisVideoSignalingConsumer` → `CommandSender` → the device's
live TCP connection). No simulation, no synthetic fixture — every attempt below is a real frame
sent to and received from the physical MDVR.

| # | Relay-side session pre-created? | Transport offered | `0x0001` ack received? | Result | Device attempted a media (ingest) connection? |
|---|---|---|---|---|---|
| 1 | No | TCP only | Yes, ~3s | `result: 0` (success) | **Yes** — TCP connect ~150ms after the ack, but rejected by the relay as `unsolicited_ingest_connection_rejected` (no session existed to match it against — a real software gap in *this test's own setup*, not a device/firmware defect; fixed for attempts 2–5 by creating the relay-side session first, matching the real production call order) |
| 2 | Yes | TCP only | Yes, ~7s | `result: 0` (success) | No — zero connection attempts observed in the following 15+ seconds |
| 3 | Yes | TCP only | **No ack at all** | — | No |
| 4 | Yes | TCP only | Yes, ~1s | `result: 0` (success) | No — zero connection attempts observed in the following 14+ seconds (tight, continuous polling) |
| 5 | Yes | **TCP and UDP** (both ports offered in the same `0x9101`) | **No ack at all** | — | No — checked both the relay's TCP ingest log *and* a raw UDP socket bound directly on the host's real network interface at port 7910 for the full 30s window; nothing arrived on either transport |

**Exact protocol messages observed, every attempt:** `0x9101` (real-time A/V transmission
request, `data_type=2`) sent on the device's live connection; the terminal's own `0x0001`
(terminal general response) echoing `original_message_id=0x9101` with `result=0` (3 of 5
attempts) or no response at all (2 of 5 attempts) within the observation window. `0x9102`
(`control=4`, close intercom) was sent to close out attempt 2 and was acknowledged twice —
once from this ADR's own explicit close and once more from the relay's own `SessionManager.
end_session`-triggered device stop-signal (ADR-0024 §5 point 4) — both `result: 0`, proving the
close path itself is handled cleanly and idempotently by the firmware. **`0x9105` (live status
notify) was never sent by this relay in any attempt** (nothing to report packet loss on, since no
media ever flowed) **and the device never sent one either.** No extended-RTP audio frames (or any
other traffic) reached the relay's ingest server in any of the five attempts — the single
`unsolicited_ingest_connection_rejected` log line in attempt 1 is a bare TCP SYN/connect, not a
frame; the connection was rejected before any payload could be read.

**Device health after testing:** confirmed still connected, authenticated, and sending normal
heartbeat/GPS traffic on its original connection throughout and after all five attempts — the
bench unit was not destabilized by this test.

## Real bench result

**Inconsistent, unreliable — not a clean accept, not a clean protocol-level reject.** The
firmware's JT/T 808 dispatcher genuinely parses and understands `0x9101 data_type=2` (it replies
`result: 0`, "success," in 3 of 5 attempts — a real, repeated, non-accidental signal that this
message is recognized and not rejected as unsupported). But **in zero of five attempts did any
actual two-way-intercom media — a device-initiated connection carrying real audio, in either
direction — ever establish.** The one real device-initiated connection attempt observed (attempt
1) happened by coincidence of timing before this test's own relay-side session existed, and was
never reproduced in four further attempts run with the correct session pre-created, the exact
same wire request, waited on for up to 30 seconds, and checked over both TCP and UDP.

This does not read as "the feature doesn't exist" (attempt 1's real connect attempt rules that
out) — it reads as **unreliable session establishment on this specific firmware build**, for
reasons this bench test cannot isolate further (no access to the vendor's own firmware
diagnostics; possibilities include an internal per-channel cooldown/state-machine quirk after the
first attempt, a firmware bug in repeated `0x9101 data_type=2` handling, or a race this test's own
send timing didn't reliably win). Per `.claude/rules/security.md`/`.claude/rules/workflow.md`'s
own "don't assume, use the physical result as authority" discipline, this ADR does not guess which.

## Decision

**Treat this as the "if it fails" branch of the original instruction.** A real device-initiated
audio media connection was never observed to complete even once, so there is no verified
end-to-end two-way-intercom capability to build a production feature on top of — doing so anyway
would mean shipping permission checks, D5 authorization, audit logging, browser push-to-talk UI,
and session-state machinery for a media path that has never once carried a real audio frame in
five independent, careful attempts. That is exactly the "fake workaround" the original instruction
explicitly forbade, so **none of the following are implemented by this ADR**: a dedicated
intercom permission, D5/tenant-scope authorization for intercom specifically, intercom-specific
audit hooks, browser microphone capture or push-to-talk UI, browser→relay→MDVR uplink audio,
MDVR→relay→browser return audio, intercom session states, concurrency protection, or any test
suite that would assert an intercom session actually works.

**No code change is made to the one hardcoded `data_type: 0` line either**, a narrower call than
the instruction's own "if it fails... implement only the protocol/software groundwork that is
safe and justified" might suggest is available. Reasoning: the wire-level encoding *already*
supports every `data_type`/`control` value the spec defines (`video_signaling.py`, unchanged,
predates this ADR) — there is no missing protocol groundwork to add. The only remaining candidate
change is widening `Jt1078RelayAdapter.start_live`'s signature to accept a `data_type` parameter
nobody would ever call with anything but its default — code that exists solely for a capability
this bench test could not verify is exactly the "design for a hypothetical future requirement"
this codebase's own engineering discipline avoids (`CLAUDE.md`: "Don't add features... beyond what
the task requires... Don't design for hypothetical future requirements"). Leaving the line
hardcoded is therefore the more honest state: it correctly reflects that this deployable has no
real, working intercom call path today, and it costs nothing to widen later, in the same commit
that would actually wire a verified capability to it.

## What this ADR does not do

- Does not implement any part of the intercom feature itself (see Decision above for the full
  list).
- Does not modify `video_signaling.py`, `redis_video_signaling_consumer.py`, `command_sender.py`,
  or any other already-generic protocol-layer code — all of it already correctly handles
  `data_type=2`/`control=4` and needed no change to run this bench test.
- Does not claim, anywhere, that two-way intercom is a working RAAD capability. `PROJECT_STATUS.md`
  §10 (Known Issues) is updated to record this finding as open, not silently dropped.
- Does not rule out revisiting this feature — see Consequences below for what would justify
  reopening it.

## Physical hardware facts confirmed or reconfirmed during this session

- MDVR audio capability (ADR-0033, reconfirmed unchanged by this test): codec 6 (G.711A), mono,
  8kHz, 320-byte/40ms frames, `supports_audio_output=true`.
- Current bench unit carries an ADAS camera and an ordinary cabin camera; **no DMS camera is
  installed** — unchanged, not re-tested by this ADR (no DMS-relevant message was sent).
- Camera microphones are not assumed present — the supplier has confirmed the purchased cameras
  carry no audio functionality; the MDVR's own dedicated intercom microphone/speaker path (not
  any camera) is the hardware this test targeted, per the user's own explicit framing.
- **New finding, this session:** the firmware's `0x9101 data_type=2` / `0x9102 control=4` handling
  is real (not absent — one genuine device-initiated connection attempt was observed) but
  unreliable across repeated attempts (4 of 5 further tries surfaced no real media connection
  attempt at all, over either TCP or UDP).

## Consequences

- **Two-way intercom remains unimplemented in RAAD**, tracked as an open, disclosed gap
  (`PROJECT_STATUS.md` §10), not a silently-abandoned request.
- **Revisiting this feature is justified by any of:** a firmware update from the supplier
  specifically addressing repeated/two-way-intercom session establishment, a different bench unit
  or hardware revision showing more reliable behavior, or direct vendor documentation/confirmation
  of the exact preconditions this firmware needs for `0x9101 data_type=2` to reliably open its
  media channel (this test could not determine that from the device's own external behavior
  alone).
- **No regression risk to any working feature.** This ADR changes no code; live video, GPS
  tracking, and the previously-verified G.711A→AAC audio path (ADR-0034) are untouched — confirmed
  by the device remaining connected, authenticated, and sending normal traffic throughout and
  after this bench test.

## References

- `services/device-gateway/src/vendors/jt808/commands/video_signaling.py` — the already-generic
  `LiveVideoRequest`/`LiveVideoControl` encoding this test exercised unmodified.
- `backend/raad/modules/video/infra/adapters.py` — the one hardcoded `data_type: 0` line this ADR
  deliberately leaves unchanged (see Decision).
- `docs/architecture/adr/0024-jt1078-video-relay-architecture.md`,
  `docs/architecture/adr/0033-terminal-audio-capability-capture.md` — the prior audio/video
  signaling work this bench test reused without modification.
- `.claude/rules/jt808.md`, `.claude/rules/jt1078.md` — the protocol rules this ADR's bench test
  was run under (never assume undocumented device behavior; use physical result as authority).
