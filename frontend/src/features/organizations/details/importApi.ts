import { apiRequest, downloadFile } from "../../../shared/api/client";

export type ImportResourceType = "bus_manifest" | "students" | "parents";
export type ImportConflictStrategy =
  | "skip"
  | "overwrite"
  | "skip_invalid"
  | "upsert"
  | "strict";

export interface ImportRowError {
  rowNumber: number;
  column: string;
  errorMessage: string;
}

export interface ImportRowPreview {
  rowNumber: number;
  isValid: boolean;
  data: Record<string, unknown>;
  errors: string[];
}

export interface ImportValidationSummary {
  resourceType: ImportResourceType;
  organizationId: string;
  totalRows: number;
  validRows: number;
  invalidRows: number;
  errors: ImportRowError[];
  preview: ImportRowPreview[];
}

export interface ImportCommitSummary {
  batchId: string;
  resourceType: ImportResourceType;
  organizationId: string;
  createdCount: number;
  updatedCount: number;
  skippedCount: number;
  totalProcessed: number;
  status: string;
  errors: string[];
}

export interface ImportBatchItem {
  id: string;
  organizationId: string;
  actorUserId: string;
  resourceType: ImportResourceType;
  status: "pending" | "committed" | "failed";
  originalFilename: string | null;
  fileSizeBytes: number | null;
  totalRows: number;
  createdCount: number;
  updatedCount: number;
  skippedCount: number;
  failedCount: number;
  conflictStrategy: ImportConflictStrategy | null;
  errorReportAvailable: boolean;
  committedAt: string | null;
  createdAt: string;
}

export interface ImportBatchListResponse {
  items: ImportBatchItem[];
  total: number;
}

// Wire structures matching backend Pydantic schemas
interface ImportRowErrorWire {
  row_number: number;
  column: string;
  error_message: string;
}

interface ImportRowPreviewWire {
  row_number: number;
  is_valid: boolean;
  data: Record<string, unknown>;
  errors?: string[];
}

interface ImportValidationSummaryWire {
  resource_type: ImportResourceType;
  organization_id: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  errors: ImportRowErrorWire[];
  preview: ImportRowPreviewWire[];
}

interface ImportCommitSummaryWire {
  batch_id: string;
  resource_type: ImportResourceType;
  organization_id: string;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  total_processed: number;
  status: string;
  errors: string[];
}

interface ImportBatchWire {
  id: string;
  organization_id: string;
  actor_user_id: string;
  resource_type: ImportResourceType;
  status: "pending" | "committed" | "failed";
  original_filename: string | null;
  file_size_bytes: number | null;
  total_rows: number;
  created_count: number;
  updated_count: number;
  skipped_count: number;
  failed_count: number;
  conflict_strategy: ImportConflictStrategy | null;
  error_report_available: boolean;
  committed_at: string | null;
  created_at: string;
}

interface ImportBatchListWire {
  items: ImportBatchWire[];
  total: number;
}

export async function downloadPlatformImportTemplate(
  organizationId: string,
  resourceType: ImportResourceType,
  format: "xlsx" | "csv" = "xlsx",
): Promise<void> {
  const filename = `${resourceType}_template_${organizationId}.${format}`;
  await downloadFile(
    `/admin/organizations/${encodeURIComponent(organizationId)}/imports/templates/${resourceType}?format=${format}`,
    filename,
  );
}

export async function validatePlatformImport(
  organizationId: string,
  resourceType: ImportResourceType,
  file: File,
): Promise<ImportValidationSummary> {
  const formData = new FormData();
  formData.append("file", file, file.name);

  const wire = await apiRequest<ImportValidationSummaryWire>(
    `/admin/organizations/${encodeURIComponent(organizationId)}/imports/validate?resource_type=${resourceType}`,
    {
      method: "POST",
      body: formData,
    },
  );

  return {
    resourceType: wire.resource_type,
    organizationId: wire.organization_id,
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

export async function commitPlatformImport(
  organizationId: string,
  resourceType: ImportResourceType,
  file: File,
  conflictStrategy: ImportConflictStrategy = "skip",
): Promise<ImportCommitSummary> {
  const formData = new FormData();
  formData.append("file", file, file.name);

  // Normalize client aliases ("skip" -> "skip_invalid", "overwrite" -> "upsert")
  const normalizedStrategy =
    conflictStrategy === "skip"
      ? "skip_invalid"
      : conflictStrategy === "overwrite"
      ? "upsert"
      : conflictStrategy;

  const wire = await apiRequest<ImportCommitSummaryWire>(
    `/admin/organizations/${encodeURIComponent(
      organizationId,
    )}/imports/commit?resource_type=${resourceType}&conflict_strategy=${encodeURIComponent(
      normalizedStrategy,
    )}`,
    {
      method: "POST",
      body: formData,
    },
  );

  return {
    batchId: wire.batch_id,
    resourceType: wire.resource_type,
    organizationId: wire.organization_id,
    createdCount: wire.created_count,
    updatedCount: wire.updated_count,
    skippedCount: wire.skipped_count,
    totalProcessed: wire.total_processed,
    status: wire.status,
    errors: wire.errors ?? [],
  };
}

export async function listPlatformImportBatches(
  organizationId: string,
): Promise<ImportBatchListResponse> {
  const wire = await apiRequest<ImportBatchListWire>(
    `/admin/organizations/${encodeURIComponent(organizationId)}/imports/batches`,
  );

  return {
    total: wire.total,
    items: (wire.items ?? []).map((b) => ({
      id: b.id,
      organizationId: b.organization_id,
      actorUserId: b.actor_user_id,
      resourceType: b.resource_type,
      status: b.status,
      originalFilename: b.original_filename,
      fileSizeBytes: b.file_size_bytes,
      totalRows: b.total_rows,
      createdCount: b.created_count,
      updatedCount: b.updated_count,
      skippedCount: b.skipped_count,
      failedCount: b.failed_count,
      conflictStrategy: b.conflict_strategy,
      errorReportAvailable: b.error_report_available,
      committedAt: b.committed_at,
      createdAt: b.created_at,
    })),
  };
}
