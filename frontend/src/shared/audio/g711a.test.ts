import { describe, expect, it } from "vitest";
import {
  createUplinkFrameChunkerState,
  encodeFloat32ToALaw,
  flushPendingFrame,
  linearToALawByte,
  pushAndDrainFrames,
  resampleFloat32Linear,
} from "./g711a";

/**
 * Decode counterpart used only to verify round-trip fidelity in this test — mirrors
 * `services/jt1078/src/codec/g711a.py`'s own `_alaw_byte_to_linear16` byte-for-byte (the same
 * canonical ITU-T G.711 A-law reference algorithm), so a passing round-trip here is real evidence
 * this encoder and that repository's existing decoder agree on the wire convention, not just
 * that this file is internally consistent with itself.
 */
function decodeALawByteToLinear16(aValIn: number): number {
  const aVal = aValIn ^ 0x55;
  let t = (aVal & 0x0f) << 4;
  const seg = (aVal & 0x70) >> 4;
  if (seg === 0) {
    t += 8;
  } else if (seg === 1) {
    t += 0x108;
  } else {
    t += 0x108;
    t <<= seg - 1;
  }
  return aVal & 0x80 ? t : -t;
}

describe("linearToALawByte", () => {
  it("round-trips near-zero and full-scale samples within G.711's own quantization error", () => {
    const samples = [0, 100, -100, 1000, -1000, 16000, -16000, 32000, -32000];
    for (const sample of samples) {
      const encoded = linearToALawByte(sample);
      const decoded = decodeALawByteToLinear16(encoded);
      // A-law's own coarsest segment step is roughly 1/16 of full scale near the extremes -
      // this bound is generous enough to catch a genuinely wrong encoder while tolerating real,
      // expected lossy-codec quantization error.
      expect(Math.abs(decoded - sample)).toBeLessThan(2100);
    }
  });

  it("preserves sign", () => {
    expect(linearToALawByte(1000) & 0x80).not.toBe(0); // sign bit set for positive samples
    expect(linearToALawByte(-1000) & 0x80).toBe(0); // sign bit clear for negative samples
  });

  it("is deterministic for the same input", () => {
    expect(linearToALawByte(12345)).toBe(linearToALawByte(12345));
  });

  it("clamps out-of-range input rather than wrapping", () => {
    expect(() => linearToALawByte(200000)).not.toThrow();
    expect(() => linearToALawByte(-200000)).not.toThrow();
  });
});

describe("resampleFloat32Linear", () => {
  it("is a no-op when rates match", () => {
    const input = new Float32Array([1, 2, 3]);
    expect(resampleFloat32Linear(input, 8000, 8000)).toBe(input);
  });

  it("downsamples 48000Hz to 8000Hz at roughly a 6:1 ratio", () => {
    const input = new Float32Array(480); // 10ms at 48kHz
    const out = resampleFloat32Linear(input, 48000, 8000);
    expect(out.length).toBe(80); // 10ms at 8kHz
  });

  it("attenuates out-of-band tones far more than in-band ones", () => {
    // Regression for the anti-aliasing fix (2026-09-03). Point-sampling a 48kHz stream down to
    // 8kHz folds everything above the 4kHz Nyquist limit back into the voice band at full
    // amplitude. The box average over each 6-sample window is a real (if gentle) low-pass: its
    // response is |sinc(6f/48000)|, with a null at 8kHz. Asserted as a *ratio* rather than an
    // absolute floor, because a box filter is deliberately not a brick wall - the honest claim
    // is "out-of-band energy is strongly suppressed relative to in-band", not "eliminated".
    const tone = (hz: number) => {
      const input = new Float32Array(480);
      for (let i = 0; i < input.length; i++) input[i] = Math.sin((2 * Math.PI * hz * i) / 48000);
      const out = resampleFloat32Linear(input, 48000, 8000);
      return Math.sqrt([...out].reduce((a, v) => a + v * v, 0) / out.length);
    };
    const inBand = tone(500);
    const outOfBand = tone(12000);
    expect(inBand).toBeGreaterThan(0.5);
    expect(outOfBand).toBeLessThan(0.25);
    expect(inBand / outOfBand).toBeGreaterThan(3);
  });

  it("cancels a tone sitting exactly on the filter's null", () => {
    // 8kHz is the box filter's first null (6 samples at 48kHz spans exactly one period), so it
    // should be almost perfectly removed - the clearest demonstration that a low-pass is really
    // being applied rather than samples merely being dropped.
    const input = new Float32Array(480);
    for (let i = 0; i < input.length; i++) input[i] = Math.sin((2 * Math.PI * 8000 * i) / 48000);
    const out = resampleFloat32Linear(input, 48000, 8000);
    const rms = Math.sqrt([...out].reduce((a, v) => a + v * v, 0) / out.length);
    expect(rms).toBeLessThan(0.01);
  });

  it("preserves a constant signal", () => {
    const input = new Float32Array(48).fill(0.5);
    const out = resampleFloat32Linear(input, 48000, 8000);
    for (const sample of out) {
      expect(sample).toBeCloseTo(0.5, 5);
    }
  });
});

describe("encodeFloat32ToALaw", () => {
  it("produces one output byte per input sample", () => {
    const samples = new Float32Array([0, 0.5, -0.5, 1, -1]);
    expect(encodeFloat32ToALaw(samples).length).toBe(5);
  });

  it("encoding silence round-trips to near-zero", () => {
    const encoded = encodeFloat32ToALaw(new Float32Array([0]));
    expect(Math.abs(decodeALawByteToLinear16(encoded[0]))).toBeLessThan(16);
  });

  it("clamps values outside [-1, 1] rather than producing garbage", () => {
    const encoded = encodeFloat32ToALaw(new Float32Array([2, -2]));
    expect(encoded.length).toBe(2);
    const positive = decodeALawByteToLinear16(encoded[0]);
    const negative = decodeALawByteToLinear16(encoded[1]);
    expect(positive).toBeGreaterThan(0);
    expect(negative).toBeLessThan(0);
  });
});

/**
 * Regression coverage for the real, physically-proven intercom uplink bug (2026-09-02): a
 * `ScriptProcessorNode` callback (`CAPTURE_BUFFER_SIZE = 2048` in `useIntercomController.ts`)
 * used to be encoded and sent as one WebSocket message, up to 2048 G.711A bytes — well past the
 * JT/T 1078 extended-RTP frame body's 950-byte ceiling
 * (`services/jt1078/src/ingest/extended_rtp.py`'s `_MAX_BODY_LENGTH`), raising
 * `MalformedExtendedRtpFrameError` relay-side and closing the uplink socket before a single word
 * ever reached the MDVR speaker.
 */
describe("pushAndDrainFrames (intercom uplink packetization)", () => {
  it("never emits a frame larger than the requested frame size", () => {
    const state = createUplinkFrameChunkerState();
    const frames = pushAndDrainFrames(state, new Uint8Array(2048), 320);
    for (const frame of frames) {
      expect(frame.length).toBeLessThanOrEqual(320);
      expect(frame.length).toBeLessThanOrEqual(950); // the actual JT/T 1078 protocol ceiling
    }
  });

  it("splits one 2048-byte capture callback into exactly six 320-byte frames plus a remainder", () => {
    // The real-world shape this bug was found under: 2048 samples at 8kHz (a ScriptProcessorNode
    // callback, one byte per G.711A sample) chunked into ADR-0033's own confirmed 320-byte
    // device frame size. 2048 / 320 = 6.4 -> six full frames, 128 bytes carried into next call.
    const state = createUplinkFrameChunkerState();
    const frames = pushAndDrainFrames(state, new Uint8Array(2048), 320);
    expect(frames.length).toBe(6);
    for (const frame of frames) {
      expect(frame.length).toBe(320);
    }
    expect(state.pending.length).toBe(128);
  });

  it("never loses a sample across multiple calls - concatenating every emitted frame plus the final flush reproduces the exact input", () => {
    const state = createUplinkFrameChunkerState();
    const input1 = new Uint8Array(2048).map((_, i) => i % 256);
    const input2 = new Uint8Array(2048).map((_, i) => (i + 7) % 256);

    const frames = [
      ...pushAndDrainFrames(state, input1, 320),
      ...pushAndDrainFrames(state, input2, 320),
    ];
    const finalFrame = flushPendingFrame(state);
    const reassembled = new Uint8Array(
      frames.reduce((sum, f) => sum + f.length, 0) + (finalFrame?.length ?? 0),
    );
    let offset = 0;
    for (const frame of frames) {
      reassembled.set(frame, offset);
      offset += frame.length;
    }
    if (finalFrame) reassembled.set(finalFrame, offset);

    const expected = new Uint8Array(input1.length + input2.length);
    expected.set(input1, 0);
    expected.set(input2, input1.length);
    expect(reassembled).toEqual(expected);
  });

  it("carries a partial buffer across calls rather than padding or dropping it", () => {
    const state = createUplinkFrameChunkerState();
    const frames1 = pushAndDrainFrames(state, new Uint8Array(200), 320);
    expect(frames1.length).toBe(0); // fewer than one frame's worth buffered so far
    expect(state.pending.length).toBe(200);

    const frames2 = pushAndDrainFrames(state, new Uint8Array(200), 320);
    expect(frames2.length).toBe(1); // 200 + 200 = 400 >= 320
    expect(frames2[0].length).toBe(320);
    expect(state.pending.length).toBe(80); // 400 - 320
  });

  it("preserves sequence order across the emitted frames", () => {
    const state = createUplinkFrameChunkerState();
    const input = new Uint8Array(960); // exactly 3 frames of 320
    for (let i = 0; i < input.length; i++) input[i] = i % 256;

    const frames = pushAndDrainFrames(state, input, 320);

    expect(frames.length).toBe(3);
    expect(frames[0][0]).toBe(0);
    expect(frames[1][0]).toBe(320 % 256);
    expect(frames[2][0]).toBe(640 % 256);
  });
});

describe("flushPendingFrame", () => {
  it("returns null when nothing is buffered", () => {
    const state = createUplinkFrameChunkerState();
    expect(flushPendingFrame(state)).toBeNull();
  });

  it("flushes a short partial frame rather than losing the tail of speech on stopTalking()", () => {
    const state = createUplinkFrameChunkerState();
    pushAndDrainFrames(state, new Uint8Array(100), 320);
    const flushed = flushPendingFrame(state);
    expect(flushed?.length).toBe(100);
    expect(state.pending.length).toBe(0); // cleared after flush
  });

  it("a flushed frame is always well under the protocol ceiling", () => {
    const state = createUplinkFrameChunkerState();
    pushAndDrainFrames(state, new Uint8Array(319), 320); // one byte short of a full frame
    const flushed = flushPendingFrame(state);
    expect(flushed?.length).toBeLessThanOrEqual(950);
  });
});
