import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ORGANIZATION_SUBSCRIPTION_INACTIVE,
  clearSubscriptionBlock,
  getSubscriptionBlockState,
  parseSubscriptionBlockDetails,
  reportSubscriptionBlocked,
  subscribeToSubscriptionBlock,
} from "./subscriptionStatusStore";

describe("subscriptionStatusStore (ADR-0039 §6)", () => {
  beforeEach(() => {
    clearSubscriptionBlock();
  });

  it("exposes the exact wire code the backend emits", () => {
    // Part of the API contract — `core/policies/organization_access.py` carries the matching
    // "must not be renamed without a version bump" note. A drift here silently stops the whole
    // suspension UX from ever rendering.
    expect(ORGANIZATION_SUBSCRIPTION_INACTIVE).toBe("ORGANIZATION_SUBSCRIPTION_INACTIVE");
  });

  it("starts unblocked", () => {
    expect(getSubscriptionBlockState().blocked).toBe(false);
  });

  it("records a block and notifies subscribers", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToSubscriptionBlock(listener);

    reportSubscriptionBlocked("Inactive.", { subscriptionStatus: "suspended" });

    expect(listener).toHaveBeenCalledTimes(1);
    const state = getSubscriptionBlockState();
    expect(state.blocked).toBe(true);
    expect(state.message).toBe("Inactive.");
    expect(state.details?.subscriptionStatus).toBe("suspended");
    unsubscribe();
  });

  it("does not re-notify for an unchanged repeat block", () => {
    // A page firing several parallel requests that all fail the same way must re-render once,
    // not once per request.
    const listener = vi.fn();
    const unsubscribe = subscribeToSubscriptionBlock(listener);

    reportSubscriptionBlocked("Inactive.", { subscriptionStatus: "suspended" });
    reportSubscriptionBlocked("Inactive.", { subscriptionStatus: "suspended" });
    reportSubscriptionBlocked("Inactive.", { subscriptionStatus: "suspended" });

    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("returns a stable reference while nothing changes", () => {
    // `useSyncExternalStore` re-renders forever if the snapshot identity changes on every read.
    expect(getSubscriptionBlockState()).toBe(getSubscriptionBlockState());
  });

  it("clears on a later success so a paying tenant is not stuck", () => {
    reportSubscriptionBlocked("Inactive.", null);
    expect(getSubscriptionBlockState().blocked).toBe(true);

    clearSubscriptionBlock();

    expect(getSubscriptionBlockState().blocked).toBe(false);
    expect(getSubscriptionBlockState().details).toBeNull();
  });

  it("parses the backend's snake_case admin detail payload", () => {
    const parsed = parseSubscriptionBlockDetails({
      subscription_status: "suspended",
      current_period_end: "2026-09-01T00:00:00",
      grace_period_ends_at: "2026-09-08T00:00:00",
    });

    expect(parsed).toEqual({
      subscriptionStatus: "suspended",
      currentPeriodEnd: "2026-09-01T00:00:00",
      gracePeriodEndsAt: "2026-09-08T00:00:00",
    });
  });

  it("returns null for the ordinary-member case where the backend sends no detail", () => {
    // Requirement 39K: a Driver/Parent is deliberately told nothing beyond the generic message.
    expect(parseSubscriptionBlockDetails(null)).toBeNull();
    expect(parseSubscriptionBlockDetails(undefined)).toBeNull();
  });
});
