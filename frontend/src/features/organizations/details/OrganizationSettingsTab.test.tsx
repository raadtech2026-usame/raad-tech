import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Organization } from "../api";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  updateOrganizationStatus: vi.fn(),
  renameOrganization: vi.fn(),
}));

import { renameOrganization, updateOrganizationStatus } from "../api";
import { OrganizationSettingsTab } from "./OrganizationSettingsTab";

const ORGANIZATION: Organization = {
  id: "org-1",
  name: "Green Valley School",
  orgType: "school",
  parentOrgId: null,
  regionId: "region-1",
  status: "active",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  trialStartedAt: null,
  trialEndsAt: null,
  trialState: "not_started",
};

function renderTab(onSelectTab = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    onSelectTab,
    ...render(
      <QueryClientProvider client={queryClient}>
        <OrganizationSettingsTab organization={ORGANIZATION} onSelectTab={onSelectTab} />
      </QueryClientProvider>,
    ),
  };
}

/**
 * Organization Settings, reorganized into General/Billing/Lifecycle (Organization Management
 * phase). Only controls with a real backend endpoint behind them may ever appear — these tests
 * pin that Save actually calls the rename endpoint, that Billing navigates rather than
 * duplicating subscription controls, and that region/type stay non-editable.
 */
describe("OrganizationSettingsTab", () => {
  beforeEach(() => {
    vi.mocked(updateOrganizationStatus).mockReset();
    vi.mocked(renameOrganization).mockReset();
  });

  it("renders General/Billing/Lifecycle as named sections", () => {
    renderTab();

    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("Billing")).toBeInTheDocument();
    expect(screen.getByText("Lifecycle")).toBeInTheDocument();
  });

  it("saves a renamed organization", async () => {
    const user = userEvent.setup();
    vi.mocked(renameOrganization).mockResolvedValue({ ...ORGANIZATION, name: "Blue Valley School" });
    renderTab();

    const input = screen.getByLabelText("Organization name");
    await user.clear(input);
    await user.type(input, "Blue Valley School");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(renameOrganization).toHaveBeenCalledWith("org-1", "Blue Valley School"),
    );
  });

  it("disables Save when the name is unchanged or empty", async () => {
    const user = userEvent.setup();
    renderTab();

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    const input = screen.getByLabelText("Organization name");
    await user.clear(input);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("navigates to the Subscription tab from Billing rather than duplicating its controls", async () => {
    const user = userEvent.setup();
    const { onSelectTab } = renderTab();

    await user.click(screen.getByRole("button", { name: "Open Subscription →" }));

    expect(onSelectTab).toHaveBeenCalledWith("subscription");
  });

  it("offers no control for region or type — both are constructor-set-only", () => {
    renderTab();

    expect(screen.queryByLabelText(/region/i)).not.toBeInTheDocument();
    expect(screen.getByText(/no edit endpoint/i)).toBeInTheDocument();
  });

  it("frames deactivation as the safe alternative to deletion", async () => {
    const user = userEvent.setup();
    vi.mocked(updateOrganizationStatus).mockResolvedValue({ ...ORGANIZATION, status: "inactive" });
    renderTab();

    await user.click(screen.getByRole("button", { name: "Deactivate (Archive)" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/nothing is deleted/i);

    await user.click(within(dialog).getByRole("button", { name: "Deactivate (Archive)" }));

    await waitFor(() => expect(updateOrganizationStatus).toHaveBeenCalledWith("org-1", "inactive"));
  });
});
