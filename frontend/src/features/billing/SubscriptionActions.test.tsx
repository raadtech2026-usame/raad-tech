import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  suspendSubscription: vi.fn(),
  reactivateSubscription: vi.fn(),
  extendGracePeriod: vi.fn(),
}));

import { extendGracePeriod, reactivateSubscription, suspendSubscription, type Subscription } from "./api";
import { SubscriptionActions } from "./SubscriptionActions";

function subscription(status: Subscription["status"]): Subscription {
  return {
    id: "s1",
    organizationId: "org1",
    planId: "p1",
    status,
    currentPeriodStart: "2026-08-01T00:00:00Z",
    currentPeriodEnd: "2026-09-01T00:00:00Z",
    autoRenew: true,
    createdAt: "2026-08-01T00:00:00Z",
    updatedAt: "2026-08-01T00:00:00Z",
    pastDueSince: null,
    gracePeriodEndsAt: null,
    suspendedAt: null,
    cancelledAt: null,
    expiredAt: null,
  };
}

function renderActions(status: Subscription["status"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SubscriptionActions subscription={subscription(status)} />
    </QueryClientProvider>,
  );
}

describe("SubscriptionActions", () => {
  beforeEach(() => {
    vi.mocked(suspendSubscription).mockReset().mockResolvedValue(subscription("suspended"));
    vi.mocked(reactivateSubscription).mockReset().mockResolvedValue(subscription("active"));
    vi.mocked(extendGracePeriod).mockReset().mockResolvedValue(subscription("grace_period"));
  });

  it("offers Suspend and no Reactivate for an active subscription", () => {
    renderActions("active");

    expect(screen.getByRole("button", { name: "Suspend" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reactivate" })).not.toBeInTheDocument();
  });

  it("offers only Reactivate for a suspended subscription", () => {
    // The domain rejects suspending an already-suspended subscription, so offering the control
    // would guarantee a 400.
    renderActions("suspended");

    expect(screen.getByRole("button", { name: "Reactivate" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suspend" })).not.toBeInTheDocument();
  });

  it("offers Extend grace only in the two grace-bearing states", () => {
    const { unmount } = renderActions("past_due");
    expect(screen.getByRole("button", { name: "Extend grace" })).toBeInTheDocument();
    unmount();

    renderActions("active");
    expect(screen.queryByRole("button", { name: "Extend grace" })).not.toBeInTheDocument();
  });

  it("renders nothing actionable for a terminal subscription", () => {
    renderActions("cancelled");

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("requires confirmation before suspending", async () => {
    const user = userEvent.setup();
    renderActions("active");

    await user.click(screen.getByRole("button", { name: "Suspend" }));
    // Opening the dialog must not itself perform the action.
    expect(suspendSubscription).not.toHaveBeenCalled();

    // Two "Suspend" buttons exist once the dialog is open (the row trigger and the dialog's own
    // confirm); scope to the dialog so the assertion is about confirming, not re-opening.
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Suspend" }));
    await waitFor(() => expect(suspendSubscription).toHaveBeenCalledWith("s1"));
  });

  it("sends an absolute instant when extending grace", async () => {
    const user = userEvent.setup();
    renderActions("past_due");

    await user.click(screen.getByRole("button", { name: "Extend grace" }));
    const input = screen.getByLabelText("Grace period ends at");
    await user.type(input, "2026-10-01T12:00");
    await user.click(screen.getByRole("button", { name: "Extend" }));

    await waitFor(() => expect(extendGracePeriod).toHaveBeenCalled());
    const [, sent] = vi.mocked(extendGracePeriod).mock.calls[0];
    // ISO-8601 with an explicit offset, never the naive local string the input produces.
    expect(sent).toMatch(/Z$/);
  });

  it("does not allow extending grace with an empty date", async () => {
    const user = userEvent.setup();
    renderActions("past_due");

    await user.click(screen.getByRole("button", { name: "Extend grace" }));
    await user.click(screen.getByRole("button", { name: "Extend" }));

    expect(extendGracePeriod).not.toHaveBeenCalled();
  });
});
