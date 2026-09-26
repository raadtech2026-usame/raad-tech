/**
 * ADR-0046 §6 — per-viewer main→sub fallback policy. Pure (clock passed in), so every threshold
 * below is unit-tested without timers.
 *
 * **Why the browser decides.** Only the player can see what the viewer actually gets: whether the
 * picture is frozen and how far playback has fallen behind what is buffered. Production showed the
 * main stream falling 4–29 s behind on the cameras actually connected while the sub stream stayed
 * near real time (2026-09-23/25), so a tile that wants main switches to sub when main is visibly
 * failing *this viewer* — never on a fixed timer, and never for other viewers: the relay runs a
 * channel on main while any session still wants it (ADR-0046 §2).
 *
 * **Health.** Sampled once a second after a warm-up: a sample is unhealthy when the picture is
 * frozen or the buffered latency exceeds `latencyThresholdSeconds`. Falls back after
 * `unhealthyThreshold` unhealthy samples in the last `windowSamples`, or when a main session is lost
 * unexpectedly shortly after unhealthy samples — which is what the relay's stuck-viewer close
 * (93ded1b, 30 s) looks like from here, so a closed-for-being-stuck viewer reconnects on sub instead
 * of looping on main.
 *
 * **Anti-flapping.** Sub is held for `baseHoldMs`, then main is probed. A probe that falls back again
 * within `probeFailWindowMs` doubles the hold (capped at `maxHoldMs`); `stableResetMs` of healthy main
 * resets it.
 */

export interface FallbackPolicy {
  warmupMs: number;
  windowSamples: number;
  unhealthyThreshold: number;
  latencyThresholdSeconds: number;
  /** A lost main session falls back only with at least this many unhealthy samples in the window. */
  lostSessionUnhealthyThreshold: number;
  baseHoldMs: number;
  maxHoldMs: number;
  probeFailWindowMs: number;
  stableResetMs: number;
}

export const DEFAULT_FALLBACK_POLICY: FallbackPolicy = {
  warmupMs: 10_000,
  windowSamples: 20,
  unhealthyThreshold: 8,
  latencyThresholdSeconds: 3,
  lostSessionUnhealthyThreshold: 3,
  baseHoldMs: 2 * 60_000,
  maxHoldMs: 30 * 60_000,
  probeFailWindowMs: 60_000,
  stableResetMs: 5 * 60_000,
};

export interface HealthSample {
  /** The picture is frozen (the player's own stall detection). */
  stalled: boolean;
  /** Seconds buffered ahead of the playhead; `null` when unknown. */
  bufferedAheadSeconds: number | null;
}

export class MainStreamFallback {
  private samples: boolean[] = [];
  private mainConnectedAt: number | null = null;
  private healthySince: number | null = null;
  private holdMs: number;
  private holdUntil = 0;
  private lastProbeAt: number | null = null;
  private active = false;

  constructor(private readonly policy: FallbackPolicy = DEFAULT_FALLBACK_POLICY) {
    this.holdMs = policy.baseHoldMs;
  }

  get isActive(): boolean {
    return this.active;
  }

  /** How long sub is currently held after a fallback (grows with repeated failed probes). */
  get currentHoldMs(): number {
    return this.holdMs;
  }

  /** A main-stream session delivered its first frame. */
  onMainConnected(now: number): void {
    this.mainConnectedAt = now;
    this.healthySince = null;
    this.samples = [];
  }

  /** One per-second sample of a connected main-stream session. Returns `true` when this viewer
   * should fall back to sub now. */
  sample(now: number, health: HealthSample): boolean {
    if (this.active || this.mainConnectedAt === null) return false;
    if (now - this.mainConnectedAt < this.policy.warmupMs) return false;
    const unhealthy =
      health.stalled ||
      (health.bufferedAheadSeconds !== null &&
        health.bufferedAheadSeconds > this.policy.latencyThresholdSeconds);
    this.samples.push(unhealthy);
    if (this.samples.length > this.policy.windowSamples) this.samples.shift();
    if (unhealthy) {
      this.healthySince = null;
    } else {
      this.healthySince ??= now;
      if (now - this.healthySince >= this.policy.stableResetMs) {
        this.holdMs = this.policy.baseHoldMs;
        this.lastProbeAt = null;
      }
    }
    if (this.unhealthyCount() >= this.policy.unhealthyThreshold) {
      this.fallBack(now);
      return true;
    }
    return false;
  }

  /** A main-stream session closed or errored unexpectedly. Returns `true` when the reconnect should
   * use sub: main was already visibly failing this viewer just before. */
  onMainSessionLost(now: number): boolean {
    if (this.active) return false;
    const failing = this.unhealthyCount() >= this.policy.lostSessionUnhealthyThreshold;
    this.mainConnectedAt = null;
    if (!failing) {
      this.samples = [];
      return false;
    }
    this.fallBack(now);
    return true;
  }

  /** While fallen back: has the hold expired, so main may be tried again? Starting the probe is the
   * caller's `onProbe`. */
  shouldProbeMain(now: number): boolean {
    return this.active && now >= this.holdUntil;
  }

  onProbe(now: number): void {
    this.active = false;
    this.lastProbeAt = now;
    this.mainConnectedAt = null;
    this.samples = [];
  }

  /** The user (or the camera wall) no longer wants main for this tile: nothing to decide. The hold
   * is kept, so refocusing the same failing camera within it stays on sub. */
  reset(): void {
    this.active = false;
    this.samples = [];
    this.mainConnectedAt = null;
    this.healthySince = null;
    this.holdMs = this.policy.baseHoldMs;
    this.holdUntil = 0;
    this.lastProbeAt = null;
  }

  private unhealthyCount(): number {
    return this.samples.reduce((n, bad) => n + (bad ? 1 : 0), 0);
  }

  private fallBack(now: number): void {
    const probeFailed =
      this.lastProbeAt !== null && now - this.lastProbeAt <= this.policy.probeFailWindowMs;
    if (probeFailed) {
      this.holdMs = Math.min(this.holdMs * 2, this.policy.maxHoldMs);
    }
    this.active = true;
    this.holdUntil = now + this.holdMs;
    this.samples = [];
    this.mainConnectedAt = null;
    this.healthySince = null;
  }
}
