import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./importApi", () => ({
  downloadPlatformImportTemplate: vi.fn(),
  validatePlatformImport: vi.fn(),
  commitPlatformImport: vi.fn(),
  listPlatformImportBatches: vi.fn(),
}));

import {
  commitPlatformImport,
  downloadPlatformImportTemplate,
  listPlatformImportBatches,
  validatePlatformImport,
} from "./importApi";
import { OrganizationDataImportPanel } from "./OrganizationDataImportPanel";

const mockBatches = [
  {
    id: "batch-01",
    organizationId: "01J8Z3K9G6X8YV5T4N2R7QW001",
    actorUserId: "usr-founder-1",
    resourceType: "students" as const,
    status: "committed" as const,
    originalFilename: "students_roster.xlsx",
    fileSizeBytes: 24500,
    totalRows: 150,
    createdCount: 145,
    updatedCount: 5,
    skippedCount: 0,
    failedCount: 0,
    conflictStrategy: "skip" as const,
    errorReportAvailable: false,
    committedAt: "2026-11-05T09:00:00Z",
    createdAt: "2026-11-05T08:55:00Z",
  },
];

describe("OrganizationDataImportPanel", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    vi.mocked(listPlatformImportBatches).mockResolvedValue({
      items: mockBatches,
      total: 1,
    });
  });

  function renderPanel() {
    return render(
      <QueryClientProvider client={queryClient}>
        <OrganizationDataImportPanel
          organizationId="01J8Z3K9G6X8YV5T4N2R7QW001"
          organizationName="Mogadishu International School"
        />
      </QueryClientProvider>,
    );
  }

  it("renders the platform governance banner, template downloads, and past batch history", async () => {
    renderPanel();

    expect(
      screen.getByText(/Enterprise Centralized Data Import — Mogadishu International School/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/1. Official Excel & CSV Templates/i)).toBeInTheDocument();
    expect(screen.getByText(/2. Upload & Execute Bulk Import/i)).toBeInTheDocument();
    expect(screen.getByText(/3. Import Batch Audit History/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("batch-01")).toBeInTheDocument();
      expect(screen.getByText("+145")).toBeInTheDocument();
    });
  });

  it("triggers template download with correct organization scope", async () => {
    const user = userEvent.setup();
    renderPanel();

    const excelDownloadButtons = screen.getAllByRole("button", { name: /Excel \(\.xlsx\)/i });
    expect(excelDownloadButtons.length).toBeGreaterThanOrEqual(1);

    // First card is the recommended bus manifest template
    await user.click(excelDownloadButtons[0]);
    expect(downloadPlatformImportTemplate).toHaveBeenCalledWith(
      "01J8Z3K9G6X8YV5T4N2R7QW001",
      "bus_manifest",
      "xlsx",
    );
  });

  it("validates an uploaded file and displays validation diagnostics and preview", async () => {
    const user = userEvent.setup();
    vi.mocked(validatePlatformImport).mockResolvedValueOnce({
      resourceType: "bus_manifest",
      organizationId: "01J8Z3K9G6X8YV5T4N2R7QW001",
      totalRows: 2,
      validRows: 2,
      invalidRows: 0,
      errors: [],
      preview: [
        {
          rowNumber: 2,
          isValid: true,
          data: { bus_name: "Bus Route 1", parent_name: "Ahmed Ali", parent_phone: "+252615112233" },
          errors: [],
        },
        {
          rowNumber: 3,
          isValid: true,
          data: { bus_name: "Bus Route 1", parent_name: "Fatima Omar", parent_phone: "+252615445566" },
          errors: [],
        },
      ],
    });

    renderPanel();

    const file = new File(["dummy"], "bus_manifest.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, file);

    expect(screen.getByText("bus_manifest.xlsx")).toBeInTheDocument();

    const validateBtn = screen.getByRole("button", { name: /Validate Spreadsheet/i });
    await user.click(validateBtn);

    expect(validatePlatformImport).toHaveBeenCalledWith(
      "01J8Z3K9G6X8YV5T4N2R7QW001",
      "bus_manifest",
      file,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Total Rows").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("Valid Rows")).toBeInTheDocument();
      expect(screen.getByText(/Commit 2 Record\(s\) to Tenant/i)).toBeInTheDocument();
    });
  });

  it("executes atomic commit and displays success summary", async () => {
    const user = userEvent.setup();
    vi.mocked(validatePlatformImport).mockResolvedValueOnce({
      resourceType: "bus_manifest",
      organizationId: "01J8Z3K9G6X8YV5T4N2R7QW001",
      totalRows: 1,
      validRows: 1,
      invalidRows: 0,
      errors: [],
      preview: [{ rowNumber: 2, isValid: true, data: { bus_name: "Bus 1", parent_name: "Hassan Ali" }, errors: [] }],
    });

    vi.mocked(commitPlatformImport).mockResolvedValueOnce({
      batchId: "batch-99",
      resourceType: "bus_manifest",
      organizationId: "01J8Z3K9G6X8YV5T4N2R7QW001",
      createdCount: 1,
      updatedCount: 0,
      skippedCount: 0,
      totalProcessed: 1,
      status: "committed",
      errors: [],
    });

    renderPanel();

    const file = new File(["dummy"], "bus_manifest.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, file);

    const validateBtn = screen.getByRole("button", { name: /Validate Spreadsheet/i });
    await user.click(validateBtn);

    const commitBtn = await screen.findByRole("button", {
      name: /Commit 1 Record\(s\) to Tenant/i,
    });
    await user.click(commitBtn);

    expect(commitPlatformImport).toHaveBeenCalledWith(
      "01J8Z3K9G6X8YV5T4N2R7QW001",
      "bus_manifest",
      file,
      "skip",
    );

    await waitFor(() => {
      expect(
        screen.getByText(/Bulk Import Executed Successfully \(Batch #batch-99\)/i),
      ).toBeInTheDocument();
      expect(screen.getByText(/1 created/i)).toBeInTheDocument();
    });
  });

  it("displays children and monthly fee preview for bus manifest", async () => {
    const user = userEvent.setup();
    vi.mocked(validatePlatformImport).mockResolvedValueOnce({
      resourceType: "bus_manifest",
      organizationId: "01J8Z3K9G6X8YV5T4N2R7QW001",
      totalRows: 1,
      validRows: 1,
      invalidRows: 0,
      errors: [],
      preview: [
        {
          rowNumber: 3,
          isValid: true,
          data: {
            bus_name: "Buska goofoow",
            parent_name: "maryan",
            parent_phone: "+252616650292",
            children: [{ name: "cabdalla", fee: "30.00" }],
          },
          errors: [],
        },
      ],
    });

    renderPanel();

    const file = new File(["dummy"], "bus_manifest.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, file);

    const validateBtn = screen.getByRole("button", { name: /Validate Spreadsheet/i });
    await user.click(validateBtn);

    await waitFor(() => {
      expect(screen.getByText("Buska goofoow")).toBeInTheDocument();
      expect(screen.getByText(/cabdalla \(\$30\.00\)/)).toBeInTheDocument();
    });
  });
});
