# ADR-0034: G.711A Audio Transcode to AAC via ffmpeg (JT1078 Relay)

## Status

**Accepted** (user directive, 2026-08-28, chosen via `AskUserQuestion` from two real
alternatives — see Decision below). Implemented same session.

## Context

ADR-0033 captured the bench MDVR's real, confirmed audio codec (G.711A, `input_audio_codec=6`,
Table 6.21). A same-session follow-up (2026-08-28) built `services/jt1078/src/codec/g711a.py` to
decode G.711A to 16-bit linear PCM and tag it as FLV `SoundFormat=3` (Linear PCM) — the only
non-AAC audio format `mpegts.js`'s own FLV demuxer implements. Live-verified against the physical
bench unit at the wire-protocol level (correct tags, correct sample rate/size/channel flags,
correct duration), but real-browser testing then found `MediaSource.addSourceBuffer('audio/mp4;
codecs=ipcm')` throws `NotSupportedError` — Chrome's MSE does not accept raw Linear-PCM-in-MP4 via
`mpegts.js`'s own remux path, and that failure was fatal to the *whole* player, regressing all 4
already-working video channels to `MediaMSEError`. A same-session emergency fix (`_AUDIO_DECODERS`
emptied) restored video-only playback, live-verified, before this ADR was written.

**Browser MSE audio codec reality, established before choosing a path forward:** of the codecs
`mpegts.js`'s own FLV→fMP4 remuxer can produce, only AAC (`audio/mp4; codecs="mp4a.40.2"`) has
reliable, universal support via `MediaSource.isTypeSupported()` across target browsers. MP3-in-
fragmented-MP4 and Linear-PCM-in-MP4 both have inconsistent-to-nonexistent MSE support. This is
the actual constraint driving this ADR, not a preference for AAC as a format.

## Decision

**Transcode G.711A → AAC-LC via an `ffmpeg` subprocess per audio session**, feeding the terminal's
raw G.711A bytes directly into `ffmpeg -f alaw -ar 8000 -ac 1 -i pipe:0 -c:a aac -f adts pipe:1`
(ffmpeg's own native G.711 A-law decoder handles the input format directly — `codec/g711a.py`'s
hand-rolled decode function is not used by this new path, kept as-is as a tested utility for any
future non-ffmpeg need) and re-muxing the resulting ADTS AAC frames into FLV `SoundFormat=10`
audio tags, now backed by a real encoded bitstream instead of the pre-existing bug's fabricated
"44kHz/16-bit/stereo" AAC mislabeling of non-AAC bytes.

**Two options were put to the user via `AskUserQuestion`, both grounded in the actual investigation
above, not invented in the abstract:**
1. **AAC via ffmpeg (chosen).** A new dependency (`ffmpeg`, an `apt` package in the relay's own
   Docker image) and a real, disclosed exception to `.claude/rules/jt1078.md` #5's "repackage,
   never transcode" principle for this one, specific, narrow purpose — audio only, G.711A only,
   because no non-transcoding path produces browser-playable audio at all. Chosen for reliability
   (ffmpeg's AAC encoder is battle-tested at internet scale) and minimal new code (one subprocess-
   pipe wrapper, no new wire protocol, no new frontend code).
2. **Web Audio API side-channel (not chosen).** Zero new dependencies, but a materially larger
   change — a second delivery channel bypassing MSE entirely for audio, a new frontend audio
   player, and new A/V-sync logic — a real architecture addition, not a narrow fix.

**Why this is a disclosed exception, not a silent violation, of the "never transcode" rule:** every
other JT1078 media path in this codebase (H.264 video, and G.711A audio before this ADR) is pure
container repackaging — the exact bytes the device sends are the exact bytes (modulo Annex-B→AVCC
framing) the browser receives. This ADR's own transcode step is narrow and named: it exists
*only* because MSE structurally cannot play G.711A (or its lossless PCM expansion) at all, not
because transcoding is now this relay's general approach to media. Video remains pure repackaging,
completely untouched by this ADR.

## Implementation

- **New `services/jt1078/src/codec/aac_transcoder.py`**: manages one `ffmpeg` subprocess per
  audio-capable session — `asyncio.create_subprocess_exec`, G.711A bytes written to `stdin` as
  they arrive from the device, ADTS-framed AAC read back from `stdout` via a concurrent reader
  task (avoiding the classic pipe-deadlock of writing without draining the other side).
- **New `build_aac_sequence_header_tag`/`_AAC_PACKET_TYPE_SEQUENCE_HEADER` in `flv_muxer.py`**:
  closes a real, separate pre-existing gap this same investigation found — the *original*
  `feed_audio_aac`/`build_aac_raw_tag` never sent an AAC sequence header (`AACPacketType=0`,
  carrying the 2-byte `AudioSpecificConfig`) at all, meaning even genuine AAC content would have
  failed to initialize in a real player. Since this relay itself controls every ffmpeg invocation
  parameter (AAC-LC, mono, a fixed sample rate), `AudioSpecificConfig` is constructed directly
  from those known values, not parsed back out of ADTS — simpler and equally correct.
- **`relay.py`**: the prior `_AUDIO_DECODERS` dict (codec → pure decode function) is replaced by
  `_TRANSCODABLE_AUDIO_CODECS = frozenset({6})` plus a per-session `AacTranscoder` process,
  because AAC transcoding is inherently stateful (a live subprocess, not a pure function) — the
  same explicit, evidenced-only dispatch discipline ADR-0033/the original audio fix already
  established still governs which codecs get audio at all; any other codec still gets zero audio
  tags. `SessionManager`'s own `on_session_created`/`on_session_removed` hooks are synchronous, so
  `_on_session_created` spawns the transcoder's `start()` as a tracked fire-and-forget task
  (`_spawn_background`) rather than blocking session creation on ffmpeg's own process-spawn
  latency; a frame arriving before that task finishes is dropped, not queued, until the
  transcoder is ready — video for the same frame is unaffected either way. A missing/broken
  `ffmpeg` binary is caught and logged (`audio_transcoder_start_failed`), never left to vanish
  silently or crash the relay — the session simply stays video-only, exactly like an
  unrecognized codec.
- **FLV audio-tag timestamps derived from a fixed AAC frame duration, not ffmpeg's own output
  timing.** ffmpeg buffers internally and does not preserve a 1:1 relationship between a fed
  G.711A frame's own device-reported timestamp and any particular emitted AAC frame. Since
  AAC-LC's frame size is fixed at 1024 samples (128ms at this transcoder's fixed 8kHz output),
  `_AudioTranscodeSession` instead anchors on the first real audio frame's timestamp and counts
  forward by 128ms per emitted AAC frame — monotonic regardless of ffmpeg's own I/O jitter.
- **`docker/jt1078-relay.Dockerfile`**: adds `ffmpeg` via `apt-get`.

## What this ADR does not do

- Does not change how video is captured, muxed, or delivered in any way.
- Does not transcode anything other than this one, specific, evidenced G.711A case — a device
  reporting a different codec still gets no audio tags until that codec is separately evidenced
  and implemented (`_AUDIO_DECODERS`'s own explicit-dispatch discipline, unchanged).
- Does not attempt HLS, WebRTC, or any other delivery mechanism — WS-FLV via `mpegts.js` remains
  the only viewer path, per ADR-0024 (unchanged, disclosed as still-open for a future phase).
- Does not remove or repurpose `codec/g711a.py` — its decode/resample functions remain correct,
  tested, and available, simply unused by this specific new path.

## Consequences

- **New dependency: `ffmpeg`.** Approved by the user directly (via `AskUserQuestion`, full
  tradeoffs disclosed in the same prompt) — the first genuinely new runtime dependency this
  deployable has ever needed (its own design principle up to now: stdlib + `redis` only).
- **A per-session subprocess adds real resource cost** (one `ffmpeg` process per active audio
  session) — bounded by the same `SessionManager` concurrency ceilings ADR-0026 §8 already
  enforces (global + per-organization), so this does not introduce an unbounded-process risk.
- **`ffmpeg` unavailable/crashing must degrade to video-only, never crash the whole session** —
  the same "optional capability, fail open" posture this codebase already applies to Redis-backed
  hardening layers; audio-transcode failure for one session must never affect that session's own
  video delivery, let alone any other session's.

## Verification

- Unit tests for the ADTS-frame parsing / `AudioSpecificConfig` construction (synthetic ffmpeg-
  shaped output, no real subprocess needed for the pure-parsing logic).
- Full `services/jt1078` suite must pass.
- **Live-verified against the physical `LSZ-C5804DG-Q-F` bench unit and a real browser** (see
  this ADR's own commit for the exact evidence): real AAC audio delivered, `MediaSource`
  accepting `audio/mp4;codecs=mp4a.40.2` without error, video unaffected.

## References

- `docs/architecture/adr/0033-terminal-audio-capability-capture.md` — the real, confirmed
  `input_audio_codec=6` (G.711A) finding this ADR transcodes.
- `.claude/rules/jt1078.md` #5 — the "repackage, never transcode" principle this ADR narrowly,
  disclosedly departs from, for audio only, G.711A only.
- `services/jt1078/src/codec/g711a.py` — the prior, non-transcoding attempt (Linear PCM), kept
  as a tested utility, not used by this new path.
- `services/jt1078/src/repackager/flv_muxer.py` (`build_aac_sequence_header_tag`,
  `_AAC_PACKET_TYPE_SEQUENCE_HEADER`), `src/relay.py` (`_AUDIO_DECODERS`), `src/codec/
  aac_transcoder.py`, `docker/jt1078-relay.Dockerfile`.
