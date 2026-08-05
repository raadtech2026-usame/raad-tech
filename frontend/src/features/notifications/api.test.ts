import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../shared/api/client";
import { listNotifications, markNotificationRead } from "./api";

const NOTIFICATION_WIRE = {
  id: "n1",
  organization_id: "org1",
  recipient_user_id: "u1",
  type: "trip_started",
  title: "Trip started",
  body: "Bus 12 has started its morning trip.",
  data: null,
  trip_id: "t1",
  status: "unread",
  created_at: "2026-08-05T08:00:00Z",
  read_at: null,
};

describe("notifications api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listNotifications maps the cursor page and snake_case wire shape to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      data: [NOTIFICATION_WIRE],
      page: { limit: 20, next_cursor: "abc123", has_more: true },
    });

    const page = await listNotifications({ limit: 20, cursor: null, filters: {} });

    expect(apiRequest).toHaveBeenCalledWith("/notifications?limit=20");
    expect(page).toEqual({
      data: [
        {
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
        },
      ],
      page: { limit: 20, nextCursor: "abc123", hasMore: true },
    });
  });

  it("listNotifications sends the cursor and type filter when provided", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ data: [], page: { limit: 20, next_cursor: null, has_more: false } });

    await listNotifications({ limit: 20, cursor: "abc123", filters: { type: "system" } });

    expect(apiRequest).toHaveBeenCalledWith("/notifications?limit=20&cursor=abc123&filter%5Btype%5D=system");
  });

  it("markNotificationRead posts to the read endpoint and maps the response", async () => {
    vi.mocked(apiRequest).mockResolvedValue({ ...NOTIFICATION_WIRE, status: "read", read_at: "2026-08-05T09:00:00Z" });

    const notification = await markNotificationRead("n1");

    expect(apiRequest).toHaveBeenCalledWith("/notifications/n1/read", { method: "POST" });
    expect(notification.status).toBe("read");
    expect(notification.readAt).toBe("2026-08-05T09:00:00Z");
  });
});
