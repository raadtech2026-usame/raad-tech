import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationsPage } from "./NotificationsPage";
import type { Notification } from "./api";

vi.mock("./api", () => ({ listNotifications: vi.fn(), markNotificationRead: vi.fn() }));
vi.mock("../../shared/hooks/useWebSocket", () => ({
  useWebSocketChannel: () => ({ status: "closed", lastCloseCode: null, send: vi.fn() }),
}));

import { listNotifications, markNotificationRead } from "./api";

function notification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    organizationId: "org1",
    recipientUserId: "u1",
    type: "trip_started",
    title: "Trip started",
    body: "Bus 12 has started its morning trip.",
    data: null,
    tripId: "t1",
    status: "unread",
    createdAt: "2026-08-05T08:00:00Z",
    readAt: null,
    ...overrides,
  };
}

function pageOf(data: Notification[], hasMore = false, nextCursor: string | null = null) {
  return { data, page: { limit: 20, nextCursor, hasMore } };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <NotificationsPage />
    </QueryClientProvider>,
  );
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    vi.mocked(listNotifications).mockReset();
    vi.mocked(markNotificationRead).mockReset();
  });

  it("shows an empty state when there are no notifications", async () => {
    vi.mocked(listNotifications).mockResolvedValue(pageOf([]));

    renderPage();

    expect(await screen.findByText("No notifications yet")).toBeInTheDocument();
  });

  it("shows a visible error (not a silent blank) when the list fails to load", async () => {
    vi.mocked(listNotifications).mockRejectedValue(new Error("network down"));

    renderPage();

    expect(await screen.findByText("Could not load notifications")).toBeInTheDocument();
  });

  it("renders notifications with type/title/body and a Mark as read action for unread ones", async () => {
    vi.mocked(listNotifications).mockResolvedValue(
      pageOf([
        notification({ id: "n1", status: "unread" }),
        notification({
          id: "n2",
          status: "read",
          title: "Trip completed",
          type: "trip_completed",
          body: "Bus 12 has arrived at school.",
        }),
      ]),
    );

    renderPage();

    expect(await screen.findByText("Trip started")).toBeInTheDocument();
    expect(screen.getByText("Bus 12 has started its morning trip.")).toBeInTheDocument();
    expect(screen.getByText("Trip completed")).toBeInTheDocument();
    // Only the unread row gets a "Mark as read" button.
    expect(screen.getAllByRole("button", { name: /mark as read/i })).toHaveLength(1);
  });

  it("marks a notification read and refetches the list", async () => {
    vi.mocked(listNotifications).mockResolvedValue(pageOf([notification({ id: "n1", status: "unread" })]));
    vi.mocked(markNotificationRead).mockResolvedValue(notification({ id: "n1", status: "read" }));

    const user = userEvent.setup();
    renderPage();

    const button = await screen.findByRole("button", { name: /mark as read/i });
    await user.click(button);

    // react-query v5 calls `mutationFn` with an internal context object as a second argument —
    // asserting only the first (the id our own code actually passes) rather than an exact call
    // shape that would break on an unrelated react-query internal.
    await waitFor(() => expect(vi.mocked(markNotificationRead).mock.calls[0]?.[0]).toBe("n1"));
    await waitFor(() => expect(listNotifications).toHaveBeenCalledTimes(2));
  });

  it("filters by type via the filter chips", async () => {
    vi.mocked(listNotifications).mockResolvedValue(pageOf([]));

    const user = userEvent.setup();
    renderPage();

    await screen.findByText("No notifications yet");
    await user.click(screen.getByRole("tab", { name: "System" }));

    await waitFor(() =>
      expect(listNotifications).toHaveBeenCalledWith(
        expect.objectContaining({ filters: { type: "system" } }),
      ),
    );
  });

  it("shows a Load more button when another page exists, and fetches it on click", async () => {
    vi.mocked(listNotifications)
      .mockResolvedValueOnce(pageOf([notification({ id: "n1" })], true, "cursor-2"))
      .mockResolvedValueOnce(pageOf([notification({ id: "n2", title: "Second page item" })], false, null));

    const user = userEvent.setup();
    renderPage();

    const loadMore = await screen.findByRole("button", { name: /load more/i });
    await user.click(loadMore);

    expect(await screen.findByText("Second page item")).toBeInTheDocument();
    expect(listNotifications).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: "cursor-2" }),
    );
  });
});
