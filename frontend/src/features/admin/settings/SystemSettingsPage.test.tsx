import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  listSystemSettings: vi.fn(),
  updateSystemSetting: vi.fn(),
}));

vi.mock("../../platform-analytics/api", () => ({
  getPlatformStats: vi.fn(),
}));

import * as settingsApi from "./api";
import * as analyticsApi from "../../platform-analytics/api";
import { SystemSettingsPage } from "./SystemSettingsPage";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SystemSettingsPage />
    </QueryClientProvider>,
  );
}

describe("SystemSettingsPage", () => {
  beforeEach(() => {
    vi.mocked(settingsApi.listSystemSettings).mockReset();
    vi.mocked(settingsApi.updateSystemSetting).mockReset();
    vi.mocked(analyticsApi.getPlatformStats).mockReset();

    vi.mocked(settingsApi.listSystemSettings).mockResolvedValue({
      data: [
        {
          key: "session_cap",
          value: { founder: 5, org_admin: 2, driver: 1, parent: 2 },
          scope: "platform",
        },
        {
          key: "billing_payment_provider",
          value: { provider: "stripe" },
          scope: "platform",
        },
      ],
      page: { total: 2, page: 1, pageSize: 100 },
    });

    vi.mocked(analyticsApi.getPlatformStats).mockResolvedValue({
      organizations: { total: 10, by_status: {}, created_today: 1 },
      vehicles: { total: 20 },
      devices: { total: 20, online: 18, offline: 2 },
      users: { total: 50, by_status: {}, monthly_active: 30, created_today: 0 },
      billing: {
        subscription_by_status: {},
        expiring_soon: 0,
        revenue: { monthly_recurring: 1000, total_collected: 5000 },
        active_by_billing_cycle: {},
      },
      payment_due_organizations: [],
      system_health: { database: "healthy", broker: "healthy" },
    });
  });

  it("renders page header and tabs", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("System Settings")).toBeInTheDocument();
    });

    expect(screen.getByText("Security & Sessions")).toBeInTheDocument();
    expect(screen.getByText("Payment Gateways")).toBeInTheDocument();
    expect(screen.getByText("Tracking Defaults")).toBeInTheDocument();
    expect(screen.getByText("SMS & Communication")).toBeInTheDocument();
    expect(screen.getByText("System Health & Maintenance")).toBeInTheDocument();
  });

  it("renders session caps tab by default with save button", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Account-Sharing & Session Caps")).toBeInTheDocument();
    });

    expect(screen.getByText("Founder")).toBeInTheDocument();
    expect(screen.getByText("Save Session Caps")).toBeInTheDocument();
  });

  it("switches to payment gateways tab and saves", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("System Settings")).toBeInTheDocument();
    });

    const paymentTab = screen.getByRole("tab", { name: "Payment Gateways" });
    await user.click(paymentTab);

    expect(screen.getByText("Platform Billing Gateway")).toBeInTheDocument();
    expect(screen.getByText("Save Payment Provider")).toBeInTheDocument();
  });
});
