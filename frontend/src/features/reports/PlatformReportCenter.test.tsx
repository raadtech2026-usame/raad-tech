import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  listReportCatalog: vi.fn(),
  previewReport: vi.fn(),
  downloadReport: vi.fn(),
  listOrganizationsForReportPicker: vi.fn(),
}));

import {
  downloadReport,
  listOrganizationsForReportPicker,
  previewReport,
  type ReportDefinition,
} from "./api";
import { useToastStore } from "../../shared/components/Toast/toastStore";
import { PlatformReportCenter } from "./PlatformReportCenter";

const INVOICES_REPORT: ReportDefinition = {
  key: "platform.invoices",
  title: "Invoices",
  description: "RAAD invoices issued to organizations.",
  scope: "platform",
  accepts: ["organization_id"],
  category: "financial",
};

const SUBSCRIPTIONS_REPORT: ReportDefinition = {
  key: "platform.subscriptions",
  title: "Subscriptions",
  description: "Every organization subscription and its lifecycle state.",
  scope: "platform",
  accepts: ["organization_id", "subscription_status", "billing_cycle"],
  category: "subscriptions",
};

const AUDIT_LOGS_REPORT: ReportDefinition = {
  key: "platform.audit_logs",
  title: "Audit Logs",
  description: "Every recorded platform action.",
  scope: "platform",
  accepts: ["start", "end"],
  category: "platform",
};

function renderCenter(catalogData: ReportDefinition[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const catalog = {
    data: catalogData,
    isPending: false,
    isLoading: false,
    isError: false,
    error: null,
  } as never;
  return render(
    <QueryClientProvider client={queryClient}>
      <PlatformReportCenter catalog={catalog} />
    </QueryClientProvider>,
  );
}

/**
 * Platform Report Center (Organization Management phase) — the Founder-facing counterpart to
 * the organization Report Center, sharing its design (category nav, filter toolbar, A4-style
 * preview) but with platform-specific filters: a searchable Organization selector (never a raw
 * UUID), subscription status, and billing cycle — each a real, additive backend query parameter,
 * never a client-side-only narrowing.
 */
describe("PlatformReportCenter", () => {
  beforeEach(() => {
    useToastStore.setState({ toasts: [] });
    vi.mocked(previewReport).mockReset();
    vi.mocked(downloadReport).mockReset().mockResolvedValue(undefined);
    vi.mocked(listOrganizationsForReportPicker)
      .mockReset()
      .mockResolvedValue([{ id: "org-1", label: "Green Valley School" }]);
  });

  it("renders Financial/Subscriptions/Platform as the category tabs", () => {
    renderCenter([INVOICES_REPORT, SUBSCRIPTIONS_REPORT, AUDIT_LOGS_REPORT]);

    expect(screen.getByRole("tab", { name: "Financial" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Subscriptions" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Platform" })).toBeInTheDocument();
  });

  it("keeps Organizations/Regions/Plans/Vehicles/Drivers/Devices/Audit Logs reachable under Platform", async () => {
    const user = userEvent.setup();
    renderCenter([INVOICES_REPORT, AUDIT_LOGS_REPORT]);

    // Audit Logs is category="platform" — invisible under the default Financial tab...
    expect(screen.queryByText("Audit Logs")).not.toBeInTheDocument();
    // ...until the Platform tab is selected, proving it was never dropped from the catalogue.
    await user.click(screen.getByRole("tab", { name: "Platform" }));
    expect(await screen.findByText("Audit Logs")).toBeInTheDocument();
  });

  it("offers a searchable Organization picker, never a raw id field", async () => {
    const user = userEvent.setup();
    renderCenter([INVOICES_REPORT]);

    await user.click(screen.getByText("Invoices"));
    const picker = await screen.findByLabelText(/Organization/);
    expect(picker).toHaveAttribute("placeholder", "All organizations");

    await user.type(picker, "Green");
    expect(await screen.findByText("Green Valley School")).toBeInTheDocument();
    await user.click(screen.getByText("Green Valley School"));

    // The picked option renders by name; the organization's own id is never shown to the user.
    expect(screen.queryByText("org-1")).not.toBeInTheDocument();
  });

  it("passes the selected organization through to preview and export", async () => {
    vi.mocked(previewReport).mockResolvedValue({
      title: "Invoices",
      subtitle: null,
      headers: ["Number"],
      rows: [["INV-0001"]],
      metadata: {},
      numericColumns: [],
      totalRow: null,
    });
    const user = userEvent.setup();
    renderCenter([INVOICES_REPORT]);

    await user.click(screen.getByText("Invoices"));
    await user.type(await screen.findByLabelText(/Organization/), "Green");
    await user.click(await screen.findByText("Green Valley School"));
    await user.click(screen.getByRole("button", { name: "View" }));

    await waitFor(() =>
      expect(previewReport).toHaveBeenCalledWith(
        "platform.invoices",
        expect.objectContaining({ organizationId: "org-1" }),
      ),
    );

    await screen.findByText("INV-0001");
    await user.click(screen.getByRole("button", { name: "PDF" }));

    await waitFor(() =>
      expect(downloadReport).toHaveBeenCalledWith(
        "platform.invoices",
        "pdf",
        expect.objectContaining({ organizationId: "org-1" }),
      ),
    );
  });

  it("shows subscription status and billing cycle filters only for reports that accept them", async () => {
    const user = userEvent.setup();
    renderCenter([INVOICES_REPORT, SUBSCRIPTIONS_REPORT]);

    await user.click(screen.getByText("Invoices"));
    expect(screen.queryByLabelText("Subscription status")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Billing cycle")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Subscriptions" }));
    const listbox = await screen.findByRole("listbox");
    await user.click(await within(listbox).findByText("Subscriptions"));

    expect(await screen.findByLabelText("Subscription status")).toBeInTheDocument();
    expect(screen.getByLabelText("Billing cycle")).toBeInTheDocument();
  });

  it("passes subscription status and billing cycle through to preview", async () => {
    vi.mocked(previewReport).mockResolvedValue({
      title: "Subscriptions",
      subtitle: null,
      headers: ["Organization"],
      rows: [["org-1"]],
      metadata: {},
      numericColumns: [],
      totalRow: null,
    });
    const user = userEvent.setup();
    renderCenter([SUBSCRIPTIONS_REPORT]);

    await user.click(screen.getByRole("tab", { name: "Subscriptions" }));
    const listbox = await screen.findByRole("listbox");
    await user.click(await within(listbox).findByText("Subscriptions"));
    await user.selectOptions(screen.getByLabelText("Subscription status"), "past_due");
    await user.selectOptions(screen.getByLabelText("Billing cycle"), "annual");
    await user.click(screen.getByRole("button", { name: "View" }));

    await waitFor(() =>
      expect(previewReport).toHaveBeenCalledWith(
        "platform.subscriptions",
        expect.objectContaining({ subscriptionStatus: "past_due", billingCycle: "annual" }),
      ),
    );
  });

  it("switching reports resets filters and clears the previous preview", async () => {
    vi.mocked(previewReport).mockResolvedValue({
      title: "Invoices",
      subtitle: null,
      headers: ["Number"],
      rows: [["INV-0001"]],
      metadata: {},
      numericColumns: [],
      totalRow: null,
    });
    const user = userEvent.setup();
    renderCenter([INVOICES_REPORT, AUDIT_LOGS_REPORT]);

    await user.click(screen.getByText("Invoices"));
    await user.click(screen.getByRole("button", { name: "View" }));
    await screen.findByText("INV-0001");

    await user.click(screen.getByRole("tab", { name: "Platform" }));
    await user.click(await screen.findByText("Audit Logs"));

    expect(screen.queryByText("INV-0001")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Organization/)).not.toBeInTheDocument();
  });
});
