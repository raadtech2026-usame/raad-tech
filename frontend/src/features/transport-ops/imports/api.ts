import { apiRequest, downloadFile } from "../../../shared/api/client";

export interface ImportRowError {
  rowNumber: number;
  column: string;
  errorMessage: string;
}

export interface ImportRowPreview {
  rowNumber: number;
  isValid: boolean;
  data: Record<string, string>;
  errors: string[];
}

export interface ImportValidationSummary {
  resourceType: "students" | "parents";
  totalRows: number;
  validRows: number;
  invalidRows: number;
  errors: ImportRowError[];
  preview: ImportRowPreview[];
}

export interface ImportCommitSummary {
  resourceType: "students" | "parents";
  createdCount: number;
  updatedCount: number;
  skippedCount: number;
  totalProcessed: number;
  errors: string[];
}

interface ImportRowErrorWire {
  row_number: number;
  column: string;
  error_message: string;
}

interface ImportRowPreviewWire {
  row_number: number;
  is_valid: boolean;
  data: Record<string, string>;
  errors?: string[];
}

interface ImportValidationSummaryWire {
  resource_type: "students" | "parents";
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  errors: ImportRowErrorWire[];
  preview: ImportRowPreviewWire[];
}

interface ImportCommitSummaryWire {
  resource_type: "students" | "parents";
  created_count: number;
  updated_count: number;
  skipped_count: number;
  total_processed: number;
  errors: string[];
}

export async function downloadImportTemplate(
  resourceType: "students" | "parents",
  format: "xlsx" | "csv" = "xlsx",
): Promise<void> {
  const defaultFilename = `${resourceType}_import_template.${format}`;
  await downloadFile(`/imports/${resourceType}/template?format=${format}`, defaultFilename);
}

export async function validateImport(
  resourceType: "students" | "parents",
  file: File,
): Promise<ImportValidationSummary> {
  const formData = new FormData();
  formData.append("file", file, file.name);

  const wire = await apiRequest<ImportValidationSummaryWire>(
    `/imports/${resourceType}/validate?filename=${encodeURIComponent(file.name)}`,
    {
      method: "POST",
      body: formData,
    },
  );

  return {
    resourceType: wire.resource_type,
    totalRows: wire.total_rows,
    validRows: wire.valid_rows,
    invalidRows: wire.invalid_rows,
    errors: (wire.errors ?? []).map((e) => ({
      rowNumber: e.row_number,
      column: e.column,
      errorMessage: e.error_message,
    })),
    preview: (wire.preview ?? []).map((p) => ({
      rowNumber: p.row_number,
      isValid: p.is_valid,
      data: p.data ?? {},
      errors: p.errors ?? [],
    })),
  };
}

export async function commitImport(
  resourceType: "students" | "parents",
  file: File,
): Promise<ImportCommitSummary> {
  const formData = new FormData();
  formData.append("file", file, file.name);

  const wire = await apiRequest<ImportCommitSummaryWire>(
    `/imports/${resourceType}/commit?filename=${encodeURIComponent(file.name)}`,
    {
      method: "POST",
      body: formData,
    },
  );

  return {
    resourceType: wire.resource_type,
    createdCount: wire.created_count,
    updatedCount: wire.updated_count,
    skippedCount: wire.skipped_count,
    totalProcessed: wire.total_processed,
    errors: wire.errors ?? [],
  };
}
