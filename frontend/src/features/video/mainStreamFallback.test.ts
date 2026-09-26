import { describe, expect, it } from "vitest";
import { DEFAULT_FALLBACK_POLICY, MainStreamFallback } from "./mainStreamFallback";

const HEALTHY = { stalled: false, bufferedAheadSeconds: 0.6 };
const FROZEN = { stalled: true, bufferedAheadSeconds: 0.2 };
const BEHIND = { stalled: false, bufferedAheadSeconds: 7 };

/** Feeds one sample per second starting at `start`; returns the time of the first `true`. */
function run(fallback: MainStreamFallback, start: number, samples: typeof HEALTHY[]): number | null {
  let now = start;
  for (const sample of samples) {
    if (fallback.sample(now, sample)) return now;
    now += 1000;
  }
  return null;
}

describe("MainStreamFallback (ADR-0046 §6)", () => {
  it("never falls back during the warm-up after a main session connects", () => {
    const fallback = new MainStreamFallback();
    fallback.onMainConnected(0);
    expect(run(fallback, 0, Array(9).fill(FROZEN))).toBeNull();
  });

  it("falls back after sustained trouble: 8 unhealthy samples in the last 20", () => {
    const fallback = new MainStreamFallback();
    fallback.onMainConnected(0);
    const at = run(fallback, 10_000, [...Array(7).fill(FROZEN), HEALTHY, FROZEN]);
    expect(at).toBe(18_000);
    expect(fallback.isActive).toBe(true);
  });

  it("counts a playback latency beyond 3 s as unhealthy, not only a frozen picture", () => {
    const fallback = new MainStreamFallback();
    fallback.onMainConnected(0);
    expect(run(fallback, 10_000, Array(8).fill(BEHIND))).toBe(17_000);
  });

  it("tolerates ordinary jitter: brief freezes spread over time never trigger it", () => {
    const fallback = new MainStreamFallback();
    fallback.onMainConnected(0);
    const pattern = [FROZEN, FROZEN, ...Array(8).fill(HEALTHY)]; // 2 bad in every 10
    expect(run(fallback, 10_000, Array(10).fill(pattern).flat())).toBeNull();
  });

  it("falls back when main is lost right after unhealthy samples (the relay closed a stuck viewer)", () => {
    const fallback = new MainStreamFallback();
    fallback.onMainConnected(0);
    run(fallback, 10_000, Array(4).fill(FROZEN));
    expect(fallback.onMainSessionLost(14_500)).toBe(true);
    expect(fallback.isActive).toBe(true);
  });

  it("does not fall back when main is lost while it was healthy (e.g. the device dropped)", () => {
    const fallback = new MainStreamFallback();
    fallback.onMainConnected(0);
    run(fallback, 10_000, Array(10).fill(HEALTHY));
    expect(fallback.onMainSessionLost(20_000)).toBe(false);
    expect(fallback.isActive).toBe(false);
  });

  it("holds sub for two minutes, then probes main", () => {
    const fallback = new MainStreamFallback();
    fallback.onMainConnected(0);
    const at = run(fallback, 10_000, Array(8).fill(FROZEN)) as number;
    expect(fallback.shouldProbeMain(at + 119_000)).toBe(false);
    expect(fallback.shouldProbeMain(at + DEFAULT_FALLBACK_POLICY.baseHoldMs)).toBe(true);
    fallback.onProbe(at + DEFAULT_FALLBACK_POLICY.baseHoldMs);
    expect(fallback.isActive).toBe(false);
  });

  it("doubles the hold when a probe of main fails again quickly (anti-flapping), capped", () => {
    const fallback = new MainStreamFallback();
    let now = 0;
    const holds: number[] = [];
    for (let i = 0; i < 6; i++) {
      fallback.onMainConnected(now);
      now = run(fallback, now + 10_000, Array(8).fill(FROZEN)) as number;
      holds.push(fallback.currentHoldMs);
      now += fallback.currentHoldMs;
      fallback.onProbe(now);
    }
    expect(holds).toEqual([120_000, 240_000, 480_000, 960_000, 1_800_000, 1_800_000]);
  });

  it("five healthy minutes on main reset the hold to its base", () => {
    const fallback = new MainStreamFallback();
    fallback.onMainConnected(0);
    let now = run(fallback, 10_000, Array(8).fill(FROZEN)) as number;
    now += fallback.currentHoldMs;
    fallback.onProbe(now);
    fallback.onMainConnected(now);
    now = run(fallback, now + 10_000, Array(8).fill(FROZEN)) as number; // failed probe: 4 min
    expect(fallback.currentHoldMs).toBe(240_000);
    now += fallback.currentHoldMs;
    fallback.onProbe(now);
    fallback.onMainConnected(now);
    expect(run(fallback, now + 10_000, Array(301).fill(HEALTHY))).toBeNull();
    expect(fallback.currentHoldMs).toBe(DEFAULT_FALLBACK_POLICY.baseHoldMs);
  });

  it("reset() forgets everything (the tile was pointed at another camera)", () => {
    const fallback = new MainStreamFallback();
    fallback.onMainConnected(0);
    run(fallback, 10_000, Array(8).fill(FROZEN));
    fallback.reset();
    expect(fallback.isActive).toBe(false);
    expect(fallback.currentHoldMs).toBe(DEFAULT_FALLBACK_POLICY.baseHoldMs);
  });
});
