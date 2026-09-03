/**
 * G.711 A-law encode: 16-bit linear PCM -> 8-bit A-law bytes (ADR-0036, intercom uplink).
 *
 * The confirmed device codec for this hardware is G.711A (ADR-0033's own live `0x1003` report,
 * `input_audio_codec=6`) — encoding the operator's mic audio to this exact codec client-side
 * avoids a second server-side transcode process purely for the uplink direction (ADR-0036 §5),
 * keeping round-trip latency for a live conversation lower than a server-side `ffmpeg` hop would.
 *
 * **The standard ITU-T G.711 A-law reference algorithm** (the canonical Sun Microsystems
 * `g711.c` `linear2alaw`, the same public-domain algorithm underlying FFmpeg/SoX/Asterisk's own
 * G.711 codecs — not invented here), the exact encode-side counterpart of this repository's own
 * existing *decoder* (`services/jt1078/src/codec/g711a.py`'s `_alaw_byte_to_linear16`, which XORs
 * the received byte with `0x55` before segment/mantissa extraction — this encoder's own `mask`
 * XOR step produces bytes in exactly that convention).
 */

const SEG_AEND = [0x1f, 0x3f, 0x7f, 0xff, 0x1ff, 0x3ff, 0x7ff, 0xfff];

function search(value: number, table: number[]): number {
  for (let i = 0; i < table.length; i++) {
    if (value <= table[i]) return i;
  }
  return table.length;
}

/** One signed 16-bit linear PCM sample -> one A-law byte. */
export function linearToALawByte(sampleIn: number): number {
  let pcmVal = Math.max(-32768, Math.min(32767, Math.trunc(sampleIn))) >> 3;
  let mask: number;
  if (pcmVal >= 0) {
    mask = 0xd5;
  } else {
    mask = 0x55;
    pcmVal = -pcmVal - 1;
  }

  const seg = search(pcmVal, SEG_AEND);
  if (seg >= 8) {
    return 0x7f ^ mask;
  }
  let aVal = seg << 4;
  aVal |= seg < 2 ? (pcmVal >> 1) & 0x0f : (pcmVal >> seg) & 0x0f;
  return aVal ^ mask;
}

/**
 * Encodes a `Float32Array` of samples in `[-1, 1]` (the shape Web Audio's `AudioWorklet`/
 * `ScriptProcessorNode` produce) to G.711A bytes, one byte per input sample — the caller is
 * responsible for having already resampled to the device's own confirmed rate (8kHz mono,
 * ADR-0033) before calling this; this function performs no resampling of its own.
 */
export function encodeFloat32ToALaw(samples: Float32Array): Uint8Array {
  const out = new Uint8Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    const pcm16 = Math.round(clamped * 32767);
    out[i] = linearToALawByte(pcm16);
  }
  return out;
}

/**
 * Linear-interpolation resample (mirrors `services/jt1078/src/codec/g711a.py`'s own
 * `resample_linear_pcm16` in spirit, applied to `Float32Array` samples instead) — needed because
 * `AudioContext`'s own `sampleRate` option is not honored by every browser (Chrome/Edge accept an
 * explicit rate; others may silently ignore it), so the capture pipeline cannot assume it always
 * gets exactly 8000Hz frames straight from the browser and must be able to convert whatever it
 * actually receives. A no-op (returns the input unchanged) when `fromHz === toHz`.
 */
export function resampleFloat32Linear(
  input: Float32Array,
  fromHz: number,
  toHz: number,
): Float32Array {
  if (fromHz === toHz || input.length === 0) return input;
  const outLength = Math.max(1, Math.round((input.length * toHz) / fromHz));
  const out = new Float32Array(outLength);

  // **Downsampling averages its whole source window instead of point-sampling (2026-09-03).**
  // Picking one input sample per output sample is a decimator with no low-pass ahead of it, so
  // every frequency above 4kHz folds back into the 8kHz band as aliasing distortion. That was
  // latent while the capture `AudioContext` was pinned to 8kHz (a 1:1 no-op path), but became
  // live the moment `useIntercomController` switched to the browser's native rate to fix silent
  // capture — a 48kHz mic is a 6:1 decimation, exactly where aliasing is worst and speech
  // intelligibility suffers most. A box average over each output sample's own source window is
  // a genuine (if simple) anti-aliasing filter, costs one add per input sample, and needs no
  // new dependency. Upsampling keeps the linear interpolation below, which is already correct
  // for that direction.
  if (fromHz > toHz) {
    const ratio = fromHz / toHz;
    for (let i = 0; i < outLength; i++) {
      const start = Math.min(input.length - 1, Math.floor(i * ratio));
      const end = Math.min(input.length, Math.max(start + 1, Math.floor((i + 1) * ratio)));
      let sum = 0;
      for (let j = start; j < end; j++) sum += input[j];
      out[i] = sum / (end - start);
    }
    return out;
  }

  const step = (input.length - 1) / Math.max(1, outLength - 1);
  for (let i = 0; i < outLength; i++) {
    const srcPos = i * step;
    const srcIndex = Math.floor(srcPos);
    const frac = srcPos - srcIndex;
    const a = input[srcIndex];
    const b = input[Math.min(srcIndex + 1, input.length - 1)];
    out[i] = a + (b - a) * frac;
  }
  return out;
}

/**
 * A persistent byte-carry-over chunker (intercom uplink packetization fix, 2026-09-02).
 *
 * **The bug this fixes:** `useIntercomController.ts`'s `ScriptProcessorNode` fires once per
 * `CAPTURE_BUFFER_SIZE` (2048) input samples — a Web Audio API constant, not a wire-framing
 * choice — and the hook used to `encodeFloat32ToALaw` the *entire* 2048-sample callback and
 * `socket.send()` it as one WebSocket message. At 8kHz mono, one G.711A byte = one sample, so
 * that one message was up to 2048 bytes — well past `services/jt1078/src/ingest/
 * extended_rtp.py`'s own `_MAX_BODY_LENGTH = 950` (the JT/T 1078 extended-RTP frame body ceiling,
 * spec-confirmed). `IngestConnectionRegistry.send_audio` → `encode_audio_frame` raised
 * `MalformedExtendedRtpFrameError` on every such message, which propagated out of
 * `ViewerServer._pump_uplink_frames` and closed the uplink WebSocket — browser audio never
 * reached the MDVR speaker (proven, not inferred, by prior bench testing).
 *
 * **The fix:** never send a raw callback's worth of bytes directly. Instead, feed every new
 * batch of encoded bytes into a small persistent carry-over buffer (`state.pending`, owned by
 * the caller so multiple independent uplink streams never share state) and emit exactly
 * `frameSizeBytes`-sized frames as they become available, keeping any leftover remainder
 * buffered for the *next* call — so no sample is ever dropped, a 2048-byte callback safely
 * yields multiple well-formed sub-950-byte frames, and frame boundaries stay stable regardless
 * of exactly how many bytes one `onaudioprocess` callback produces (which varies whenever the
 * browser's own `AudioContext.sampleRate` isn't exactly 8000Hz and `resampleFloat32Linear` above
 * produces a non-round output length).
 *
 * `frameSizeBytes` defaults to 320 — ADR-0033's own confirmed G.711A `audio_frame_length` for
 * this vendor relationship (40ms at 8kHz mono, 1 byte/sample) — chosen so this relay's own
 * *outbound* framing matches the *inbound* frame size the device already sends on the identical
 * codec, not merely "small enough." Every emitted frame here is guaranteed `<=
 * _MAX_BODY_LENGTH` (950) by construction — `frameSizeBytes` would have to be misconfigured to
 * exceed that, which `PENDING_UPLINK_FRAME_BYTES`'s own call site never does.
 */
export interface UplinkFrameChunkerState {
  pending: Uint8Array;
}

export function createUplinkFrameChunkerState(): UplinkFrameChunkerState {
  return { pending: new Uint8Array(0) };
}

/**
 * Appends `newBytes` to `state.pending` and returns every complete `frameSizeBytes`-sized frame
 * now available, oldest first — mutates `state.pending` in place to keep only the leftover
 * remainder (never discarded, always carried into the next call). Returns an empty array (not an
 * error) when fewer than one full frame is buffered yet — the normal, expected case for most
 * calls, since 2048 raw samples (a `ScriptProcessorNode` callback) is `2048 / 320 = 6.4` frames,
 * not a whole number.
 */
export function pushAndDrainFrames(
  state: UplinkFrameChunkerState,
  newBytes: Uint8Array,
  frameSizeBytes: number,
): Uint8Array[] {
  const combined = new Uint8Array(state.pending.length + newBytes.length);
  combined.set(state.pending, 0);
  combined.set(newBytes, state.pending.length);

  const frames: Uint8Array[] = [];
  let offset = 0;
  while (combined.length - offset >= frameSizeBytes) {
    frames.push(combined.slice(offset, offset + frameSizeBytes));
    offset += frameSizeBytes;
  }
  state.pending = combined.slice(offset);
  return frames;
}

/**
 * Flushes whatever partial frame remains in `state.pending` (shorter than `frameSizeBytes`) as
 * one final, undersized-but-valid frame, and resets `state.pending` to empty — called on
 * `stopTalking()`/teardown so the last fraction of a second of speech before the operator
 * releases the Talk button is never silently dropped. Returns `null` (not sent) when nothing is
 * buffered — a normal outcome when the buffer happened to drain exactly evenly.
 */
export function flushPendingFrame(state: UplinkFrameChunkerState): Uint8Array | null {
  if (state.pending.length === 0) return null;
  const remainder = state.pending;
  state.pending = new Uint8Array(0);
  return remainder;
}
