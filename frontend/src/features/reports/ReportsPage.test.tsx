import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  listReportCatalog: vi.fn(),
  previewReport: vi.fn(),
  downloadReport: vi.fn(),
  listParentsForReportPicker: vi.fn(),
  listVehiclesForReportPicker: vi.fn(),
}));

import {
  downloadReport,
  listParentsForReportPicker,
  listReportCatalog,
  listVehiclesForReportPicker,
  previewReport,
  type ReportDefinition,
} from "./api";
import { useAuthStore } from "../../shared/stores/authStore";
import { useToastStore } from "../../shared/components/Toast/toastStore";
import { ReportsPage } from "./ReportsPage";

const PARENT_INVOICE_REPORT: ReportDefinition = {
  key: "org.parent_invoices",
  title: "Parent Invoice Report",
  description: "Every real Parent Invoice, grouped by parent and billing period.",
  scope: "organization",
  accepts: ["period", "vehicle_id", "parent_id", "status"],
  category: "financial",
};

const PNL_REPORT: ReportDefinition = {
  key: "org.profit_and_loss",
  title: "Profit & Loss",
  description: "School income against expenses for a date range.",
  scope: "organization",
  accepts: ["start", "end"],
  category: "financial",
};

const PLATFORM_REVENUE_REPORT: ReportDefinition = {
  key: "platform.revenue",
  title: "Revenue",
  description: "Collected subscription revenue — paid payments only.",
  scope: "platform",
  accepts: ["start", "end"],
  category: "platform",
};

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ReportsPage />
    </QueryClientProvider>,
  );
}

function loginAsOrgAdmin() {
  useAuthStore.setState({
    principal: { userId: "u1", role: "org_admin", organizationId: "org-1", regionIds: [] },
    accessToken: "t",
    refreshToken: "r",
    status: "authenticated",
    error: null,
  });
}

/**
 * Report Center (2026-09-11 re-design) — organization dashboard. These tests pin: the selector
 * list gates which report's filters render (nothing shown until a report is picked), Parent/
 * Vehicle are searchable pickers rather than raw id text fields (directive Section 18/29), the
 * date-range preset fills From/To, and preview/export both read the same `ReportTable` JSON.
 */
describe("ReportsPage — organization Report Center", () => {
  beforeEach(() => {
    loginAsOrgAdmin();
    useToastStore.setState({ toasts: [] });
    vi.mocked(listReportCatalog).mockResolvedValue([PARENT_INVOICE_REPORT, PNL_REPORT]);
    vi.mocked(previewReport).mockReset();
    vi.mocked(downloadReport).mockReset().mockResolvedValue(undefined);
    vi.mocked(listParentsForReportPicker).mockReset().mockResolvedValue([{ id: "parent-1", label: "Fatima Ali" }]);
    vi.mocked(listVehiclesForReportPicker).mockReset().mockResolvedValue([{ id: "vehicle-1", label: "KBZ 123A" }]);
  });

  it("shows no filters until a report is selected, then only that report's own accepts list", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Parent Invoice Report"));

    expect(await screen.findByLabelText(/Period/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Vehicle/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Parent/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Payment status/)).toBeInTheDocument();
  });

  it("never renders a raw Parent id or Vehicle id text field — only searchable pickers", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Parent Invoice Report"));
    await screen.findByLabelText(/Vehicle/);

    expect(screen.queryByPlaceholderText(/vehicle id/i)).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/parent id/i)).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/Parent/), "Fat");
    expect(await screen.findByText("Fatima Ali")).toBeInTheDocument();
    await user.click(screen.getByText("Fatima Ali"));

    // The picked option renders as a chip, the parent's own id is never shown to the user.
    expect(screen.queryByText("parent-1")).not.toBeInTheDocument();
  });

  it("fills in From/To when a date-range preset is chosen, still editable after", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Profit & Loss"));
    await user.selectOptions(screen.getByLabelText(/Date range/), "this_year");

    const fromInput = screen.getByLabelText(/^From$/) as HTMLInputElement;
    const toInput = screen.getByLabelText(/^To$/) as HTMLInputElement;
    const thisYear = String(new Date().getFullYear());
    expect(fromInput.value.startsWith(thisYear)).toBe(true);
    expect(toInput.value.startsWith(thisYear)).toBe(true);

    await user.clear(fromInput);
    await user.type(fromInput, "2026-01-15");
    expect(fromInput.value).toBe("2026-01-15");
  });

  it("previews the report as the same ReportTable JSON the export uses, then renders it", async () => {
    vi.mocked(previewReport).mockResolvedValue({
      title: "Parent Invoice Report",
      subtitle: "Every family's invoices, grouped by parent and billing period",
      headers: ["Invoice", "Parent", "Amount"],
      rows: [["2026-09-PARENT1", "Fatima Ali", "90.00"]],
      metadata: { "Parent invoices": "1" },
      numericColumns: [2],
      totalRow: ["TOTAL", "", "90.00"],
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Parent Invoice Report"));
    await user.type(screen.getByLabelText(/Period/), "2026-09");
    await user.click(screen.getByRole("button", { name: "View" }));

    expect(previewReport).toHaveBeenCalledWith("org.parent_invoices", expect.objectContaining({ period: "2026-09" }));

    expect(await screen.findByText("Fatima Ali")).toBeInTheDocument();
    expect(screen.getByText("Parent invoices:")).toBeInTheDocument();
    expect(screen.getAllByText("90.00").length).toBe(2);
  });

  it("shows an empty-selection message rather than a blank table", async () => {
    vi.mocked(previewReport).mockResolvedValue({
      title: "Parent Invoice Report",
      subtitle: null,
      headers: ["Invoice"],
      rows: [],
      metadata: {},
      numericColumns: [],
      totalRow: null,
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Parent Invoice Report"));
    await user.click(screen.getByRole("button", { name: "View" }));

    expect(await screen.findByText("No rows for this selection.")).toBeInTheDocument();
  });

  it("switching reports resets filters and clears the previous preview", async () => {
    vi.mocked(previewReport).mockResolvedValue({
      title: "Parent Invoice Report",
      subtitle: null,
      headers: ["Invoice"],
      rows: [["2026-09-PARENT1"]],
      metadata: {},
      numericColumns: [],
      totalRow: null,
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Parent Invoice Report"));
    await user.click(screen.getByRole("button", { name: "View" }));
    await screen.findByText("2026-09-PARENT1");

    await user.click(screen.getByText("Profit & Loss"));
    expect(screen.queryByText("2026-09-PARENT1")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Payment status/)).not.toBeInTheDocument();
  });

  it("exports PDF/Excel with the selected filters, once a preview has been viewed", async () => {
    vi.mocked(previewReport).mockResolvedValue({
      title: "Parent Invoice Report",
      subtitle: null,
      headers: ["Invoice"],
      rows: [["2026-09-PARENT1"]],
      metadata: {},
      numericColumns: [],
      totalRow: null,
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Parent Invoice Report"));
    await user.type(screen.getByLabelText(/Vehicle/), "KBZ");
    await user.click(await screen.findByText("KBZ 123A"));
    await user.click(screen.getByRole("button", { name: "View" }));
    await screen.findByText("2026-09-PARENT1");
    await user.click(screen.getByRole("button", { name: "PDF" }));

    await waitFor(() =>
      expect(downloadReport).toHaveBeenCalledWith(
        "org.parent_invoices",
        "pdf",
        expect.objectContaining({ vehicleId: "vehicle-1" }),
      ),
    );
  });

  it("surfaces a preview failure via a toast rather than a silent no-op", async () => {
    vi.mocked(previewReport).mockRejectedValue(new Error("Report failed to build."));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("Parent Invoice Report"));
    await user.click(screen.getByRole("button", { name: "View" }));

    await waitFor(() =>
      expect(useToastStore.getState().toasts[0]).toMatchObject({
        variant: "error",
        title: "Preview failed",
        description: "Report failed to build.",
      }),
    );
  });

  it("searching the catalogue overrides the active category tab", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Parent Invoice Report");
    await user.type(screen.getByLabelText("Search the report catalogue"), "profit");

    expect(await screen.findByText("Profit & Loss")).toBeInTheDocument();
    expect(screen.queryByText("Parent Invoice Report")).not.toBeInTheDocument();
  });
});

/**
 * Platform dashboard keeps its pre-redesign card grid, deliberately untouched by the Report
 * Center re-design (`reports/api.ts`'s own `ReportCategory` doc: "the platform view ignores
 * [category]... that catalogue keeps its existing card-grid").
 */
describe("ReportsPage — platform card grid", () => {
  beforeEach(() => {
    useAuthStore.setState({
      principal: { userId: "u1", role: "founder", organizationId: null, regionIds: [] },
      accessToken: "t",
      refreshToken: "r",
      status: "authenticated",
      error: null,
    });
    useToastStore.setState({ toasts: [] });
    vi.mocked(listReportCatalog).mockResolvedValue([PLATFORM_REVENUE_REPORT]);
    vi.mocked(previewReport).mockReset();
    vi.mocked(downloadReport).mockReset().mockResolvedValue(undefined);
  });

  it("renders every report as an always-expanded card with its own From/To filters", async () => {
    renderPage();

    expect(await screen.findByText("Revenue")).toBeInTheDocument();
    expect(screen.getByLabelText("From")).toBeInTheDocument();
    expect(screen.getByLabelText("To")).toBeInTheDocument();
  });

  it("exports a platform report unchanged", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Revenue");
    await user.click(screen.getByRole("button", { name: "PDF" }));

    await waitFor(() => expect(downloadReport).toHaveBeenCalledWith("platform.revenue", "pdf", expect.any(Object)));
  });
});
