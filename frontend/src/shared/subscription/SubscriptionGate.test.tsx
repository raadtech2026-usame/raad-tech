import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Subscription, SubscriptionStatus } from "../../features/billing/api";

vi.mock("../../features/billing/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../features/billing/api")>()),
  getCurrentSubscription: vi.fn(),
}));

import { getCurrentSubscription } from "../../features/billing/api";
import { useAuthStore } from "../stores/authStore";
import { SubscriptionGate, SUBSCRIPTION_REQUIRED_PATH } from "./SubscriptionGate";

/**
 * ADR-0039, amended 2026-09-09.
 *
 * The rule these tests pin: an organization without a usable subscription must not reach the
 * dashboard, and must be moved *before* any protected page mounts. Presentation only — the
 * server refuses every `/api/v1` route regardless — but the difference between a clear payment
 * page and a dashboard of red toasts is entirely this component.
 *
 * The decision table is the server's; `useSubscriptionGate` mirrors it, and mirroring is safe
 * only in one direction, so `grace_period` granting and `past_due` blocking are both asserted
 * explicitly rather than assumed.
 */

function subscription(status: SubscriptionStatus): Subscription {
  return {
    id: "sub-1",
    organizationId: "org-1",
    planId: "plan-1",
    status,
    currentPeriodStart: "2026-09-01T00:00:00Z",
    currentPeriodEnd: "2026-10-01T00:00:00Z",
    autoRenew: true,
    createdAt: "2026-09-01T00:00:00Z",
    updatedAt: "2026-09-01T00:00:00Z",
    pastDueSince: null,
    gracePeriodEndsAt: null,
    suspendedAt: null,
    cancelledAt: null,
    expiredAt: null,
  };
}

function renderGate() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/org"]}>
        <Routes>
          <Route
            path="/org"
            element={
              <SubscriptionGate>
                <div>DASHBOARD</div>
              </SubscriptionGate>
            }
          />
          <Route path={SUBSCRIPTION_REQUIRED_PATH} element={<div>PAYMENT PAGE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function signInAs(role: "org_admin" | "founder") {
  useAuthStore.setState({
    status: "authenticated",
    principal: {
      userId: "u-1",
      role,
      organizationId: role === "org_admin" ? "org-1" : null,
      isPasswordChangeRequired: false,
    },
  } as never);
}

describe("SubscriptionGate", () => {
  beforeEach(() => {
    vi.mocked(getCurrentSubscription).mockReset();
    signInAs("org_admin");
  });

  it.each<SubscriptionStatus>(["trial", "active", "grace_period"])(
    "opens the dashboard when the subscription is %s",
    async (status) => {
      vi.mocked(getCurrentSubscription).mockResolvedValue(subscription(status));
      renderGate();
      expect(await screen.findByText("DASHBOARD")).toBeInTheDocument();
    },
  );

  it.each<SubscriptionStatus>(["past_due", "suspended", "expired", "cancelled"])(
    "redirects to the payment page when the subscription is %s",
    async (status) => {
      vi.mocked(getCurrentSubscription).mockResolvedValue(subscription(status));
      renderGate();
      expect(await screen.findByText("PAYMENT PAGE")).toBeInTheDocument();
      expect(screen.queryByText("DASHBOARD")).not.toBeInTheDocument();
    },
  );

  it("redirects when the organization has no subscription at all", async () => {
    // The state every organization on the platform was in while provisioning was broken, and
    // the one the old policy allowed through.
    vi.mocked(getCurrentSubscription).mockResolvedValue(null);
    renderGate();
    expect(await screen.findByText("PAYMENT PAGE")).toBeInTheDocument();
  });

  it("never mounts the dashboard while the check is still in flight", async () => {
    // The whole point of gating above `AppShell`: mounting first and reacting to 403s later
    // means the user watches a dashboard fill with errors before being moved.
    vi.mocked(getCurrentSubscription).mockReturnValue(new Promise(() => {}));
    renderGate();
    expect(screen.queryByText("DASHBOARD")).not.toBeInTheDocument();
    expect(screen.queryByText("PAYMENT PAGE")).not.toBeInTheDocument();
  });

  it("does not gate a platform role", async () => {
    // RAAD staff are not members of any tenant. Blocking them would make suspension
    // irreversible — nobody could inspect or reactivate a suspended school.
    signInAs("founder");
    renderGate();
    expect(await screen.findByText("DASHBOARD")).toBeInTheDocument();
    expect(getCurrentSubscription).not.toHaveBeenCalled();
  });

  it("fails open when the subscription lookup itself errors", async () => {
    // A transient network error must not look like a lapsed subscription — and the payment page
    // could not load either, so blocking would strand the user. The server remains the gate.
    vi.mocked(getCurrentSubscription).mockRejectedValue(new Error("network down"));
    renderGate();
    expect(await screen.findByText("DASHBOARD")).toBeInTheDocument();
  });
});
