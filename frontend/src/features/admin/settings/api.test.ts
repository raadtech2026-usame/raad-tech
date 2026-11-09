import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

import { apiRequest } from "../../../shared/api/client";
import { listSystemSettings, updateSystemSetting } from "./api";

const SETTING_WIRE = {
  key: "session_cap",
  value: { founder: 5, org_admin: 2, driver: 1, parent: 2 },
  scope: "platform",
};

describe("system settings api", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
  });

  it("listSystemSettings calls /admin/settings with query parameters", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce({
      data: [SETTING_WIRE],
      page: { total: 1, page: 1, page_size: 50 },
    });

    const result = await listSystemSettings({ page: 1, pageSize: 50 });

    expect(apiRequest).toHaveBeenCalledWith(
      expect.stringContaining("/admin/settings?page=1&page_size=50"),
    );
    expect(result.data).toHaveLength(1);
    expect(result.data[0].key).toBe("session_cap");
    expect(result.data[0].value).toEqual({ founder: 5, org_admin: 2, driver: 1, parent: 2 });
    expect(result.data[0].scope).toBe("platform");
  });

  it("updateSystemSetting patches /admin/settings with key, value, and scope", async () => {
    vi.mocked(apiRequest).mockResolvedValueOnce(SETTING_WIRE);

    const result = await updateSystemSetting("session_cap", { founder: 10 }, "platform");

    expect(apiRequest).toHaveBeenCalledWith("/admin/settings", {
      method: "PATCH",
      body: {
        key: "session_cap",
        value: { founder: 10 },
        scope: "platform",
      },
    });
    expect(result.key).toBe("session_cap");
  });
});
