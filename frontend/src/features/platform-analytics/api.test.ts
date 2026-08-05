import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../shared/api/client";
import { getPlatformStats } from "./api";

const STATS_WIRE = {
  organizations: { total: 3, by_status: { active: 2, suspended: 1 }, created_today: 1 },
  vehicles: { total: 8 },
  devices: { total: 5, online: 4, offline: 1 },
  users: { total: 20, by_status: { active: 18, invited: 2 }, monthly_active: 12, created_today: 2 },
  billing: { subscription_by_status: { active: 3 }, expiring_soon: 1, revenue: 4500 },
  system_health: { database: "ok", broker: "down" },
};

describe("platform-analytics api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("getPlatformStats maps the snake_case wire shape to camelCase", async () => {
    vi.mocked(apiRequest).mockResolvedValue(STATS_WIRE);

    const stats = await getPlatformStats();

    expect(apiRequest).toHaveBeenCalledWith("/admin/platform-stats");
    expect(stats).toEqual({
      organizations: { total: 3, byStatus: { active: 2, suspended: 1 }, createdToday: 1 },
      vehicles: { total: 8 },
      devices: { total: 5, online: 4, offline: 1 },
      users: {
        total: 20,
        byStatus: { active: 18, invited: 2 },
        monthlyActive: 12,
        createdToday: 2,
      },
      billing: { subscriptionByStatus: { active: 3 }, expiringSoon: 1, revenue: 4500 },
      systemHealth: { database: "ok", broker: "down" },
    });
  });
});
