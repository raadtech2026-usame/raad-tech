import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BulkImportDialog } from "./BulkImportDialog";
import * as api from "./api";

vi.mock("./api", () => ({
  downloadImportTemplate: vi.fn(),
  validateImport: vi.fn(),
  commitImport: vi.fn(),
}));

const mockValidateResult: api.ImportValidationSummary = {
  resourceType: "students",
  totalRows: 2,
  validRows: 1,
  invalidRows: 1,
  errors: [
    {
      rowNumber: 3,
      column: "parent_phone",
      errorMessage: "Invalid Somali phone number '123'",
    },
  ],
  preview: [
    {
      rowNumber: 2,
      isValid: true,
      data: {
        full_name: "Ahmed Ali",
        admission_number: "ADM-001",
        parent_phone: "+252615123456",
      },
      errors: [],
    },
    {
      rowNumber: 3,
      isValid: false,
      data: {
        full_name: "Khadar Duale",
        admission_number: "ADM-002",
        parent_phone: "123",
      },
      errors: ["Invalid Somali phone number '123'"],
    },
  ],
};

const mockCommitResult: api.ImportCommitSummary = {
  resourceType: "students",
  createdCount: 1,
  updatedCount: 0,
  skippedCount: 1,
  totalProcessed: 2,
  errors: [],
};

describe("BulkImportDialog", () => {
  const onClose = vi.fn();
  const onSuccess = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not render when open is false", () => {
    render(
      <BulkImportDialog
        open={false}
        onClose={onClose}
        resourceType="students"
        onSuccess={onSuccess}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders upload step initially when open is true", () => {
    render(
      <BulkImportDialog
        open={true}
        onClose={onClose}
        resourceType="students"
        onSuccess={onSuccess}
      />,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Bulk Import Students")).toBeInTheDocument();
    expect(screen.getByText("Template (.xlsx)")).toBeInTheDocument();
    expect(screen.getByText("Template (.csv)")).toBeInTheDocument();
    expect(screen.getByText("Choose an Excel or CSV file")).toBeInTheDocument();
  });

  it("triggers template download on button click", async () => {
    render(
      <BulkImportDialog
        open={true}
        onClose={onClose}
        resourceType="students"
        onSuccess={onSuccess}
      />,
    );

    const xlsxBtn = screen.getByText("Template (.xlsx)");
    fireEvent.click(xlsxBtn);
    expect(api.downloadImportTemplate).toHaveBeenCalledWith("students", "xlsx");

    const csvBtn = screen.getByText("Template (.csv)");
    fireEvent.click(csvBtn);
    expect(api.downloadImportTemplate).toHaveBeenCalledWith("students", "csv");
  });

  it("handles file selection, validation dry-run, and commit flow", async () => {
    vi.mocked(api.validateImport).mockResolvedValue(mockValidateResult);
    vi.mocked(api.commitImport).mockResolvedValue(mockCommitResult);

    const user = userEvent.setup();

    render(
      <BulkImportDialog
        open={true}
        onClose={onClose}
        resourceType="students"
        onSuccess={onSuccess}
      />,
    );

    // Create a mock file
    const file = new File(["dummy content"], "students.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, file);

    // Selected file card should appear
    expect(screen.getByText("students.xlsx")).toBeInTheDocument();

    // Click validate
    const validateBtn = screen.getByText("Continue to Validate");
    await user.click(validateBtn);

    expect(api.validateImport).toHaveBeenCalledWith("students", file);

    // Step 2 should display validation preview
    await waitFor(() => {
      expect(screen.getByText("Valid Records")).toBeInTheDocument();
    });

    expect(screen.getByText("Ahmed Ali")).toBeInTheDocument();
    expect(screen.getByText("Khadar Duale")).toBeInTheDocument();
    expect(screen.getByText("Validation Issues (1) — These rows will be skipped")).toBeInTheDocument();

    // Click commit import
    const commitBtn = screen.getByText("Import 1 Students");
    await user.click(commitBtn);

    expect(api.commitImport).toHaveBeenCalledWith("students", file);

    // Step 3 should display success screen
    await waitFor(() => {
      expect(screen.getByText("Import Successfully Completed!")).toBeInTheDocument();
    });

    expect(onSuccess).toHaveBeenCalled();

    // Click Done to close
    const doneBtn = screen.getByText("Done");
    await user.click(doneBtn);
    expect(onClose).toHaveBeenCalled();
  });

  it("allows navigating back from Step 2 to Step 1", async () => {
    vi.mocked(api.validateImport).mockResolvedValue(mockValidateResult);
    const user = userEvent.setup();

    render(
      <BulkImportDialog
        open={true}
        onClose={onClose}
        resourceType="parents"
        onSuccess={onSuccess}
      />,
    );

    const file = new File(["dummy"], "parents.csv", { type: "text/csv" });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, file);

    const validateBtn = screen.getByText("Continue to Validate");
    await user.click(validateBtn);

    await waitFor(() => {
      expect(screen.getByText("Back")).toBeInTheDocument();
    });

    const backBtn = screen.getByText("Back");
    await user.click(backBtn);

    // Should be back to step 1
    expect(screen.getByText("Click or drag to replace file")).toBeInTheDocument();
  });
});
