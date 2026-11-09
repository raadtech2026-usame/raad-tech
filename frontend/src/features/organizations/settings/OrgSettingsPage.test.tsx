import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  getOrganization: vi.fn(),
  updateOrganizationSettings: vi.fn(),
}));

import * as orgApi from "../api";
import { useAuthStore } from "../../../shared/stores/authStore";
import { OrgSettingsPage } from "./OrgSettingsPage";

const MOCK_ORG: orgApi.Organization = {
  id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
  name: "Green Valley School",
  orgType: "school",
  parentOrgId: null,
  regionId: "01ARZ3NDEKTSV4RRFFQ69G5FBW",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-02T00:00:00Z",
  latitude: 2.046934,
  longitude: 45.318162,
  geofenceRadiusM: 250,
  approachingDistanceM: 300,
  trialStartedAt: null,
  trialEndsAt: null,
  trialState: "not_started",
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <OrgSettingsPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("OrgSettingsPage", () => {
  beforeEach(() => {
    vi.mocked(orgApi.getOrganization).mockReset();
    vi.mocked(orgApi.updateOrganizationSettings).mockReset();

    useAuthStore.setState({
      token: "test-token",
      principal: {
        userId: "01ARZ3NDEKTSV4RRFFQ69G5FBM",
        role: "org_admin",
        organizationId: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        permissions: ["organization.organizations.read", "organization.organizations.update"],
      },
    });

    vi.mocked(orgApi.getOrganization).mockResolvedValue(MOCK_ORG);
  });

  it("renders school profile tab with organization details", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Organization Settings")).toBeInTheDocument();
    });

    expect(screen.getByDisplayValue("Green Valley School")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "School Profile" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Transportation & Geofence" })).toBeInTheDocument();
  });

  it("switches to transportation and geofence tab", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Organization Settings")).toBeInTheDocument();
    });

    const geofenceTab = screen.getByRole("tab", { name: "Transportation & Geofence" });
    await user.click(geofenceTab);

    expect(screen.getByText("School Campus Geofence")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2.046934")).toBeInTheDocument();
    expect(screen.getByDisplayValue("45.318162")).toBeInTheDocument();
    expect(screen.getByDisplayValue("250")).toBeInTheDocument();
    expect(screen.getByText("Approaching Stop Threshold")).toBeInTheDocument();
  });

  it("switches to safety alerts and notifications tabs", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Organization Settings")).toBeInTheDocument();
    });

    const safetyTab = screen.getByRole("tab", { name: "Safety & Speed Alerts" });
    await user.click(safetyTab);

    expect(screen.getByText("Fleet Safety Rules & Speed Limits")).toBeInTheDocument();

    const notifTab = screen.getByRole("tab", { name: "Notifications" });
    await user.click(notifTab);

    expect(screen.getByText("Parent Notification Preferences")).toBeInTheDocument();
  });
});
