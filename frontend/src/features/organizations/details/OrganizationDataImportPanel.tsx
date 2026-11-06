import { useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  FileText,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import {
  commitPlatformImport,
  downloadPlatformImportTemplate,
  listPlatformImportBatches,
  validatePlatformImport,
  type ImportCommitSummary,
  type ImportConflictStrategy,
  type ImportResourceType,
  type ImportValidationSummary,
} from "./importApi";
import styles from "./OrganizationDataImportPanel.module.css";

interface Props {
  organizationId: string;
  organizationName: string;
}

function formatBytes(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function OrganizationDataImportPanel({
  organizationId,
  organizationName,
}: Props) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Import workflow state
  const [resourceType, setResourceType] = useState<ImportResourceType>("bus_manifest");
  const [conflictStrategy, setConflictStrategy] = useState<ImportConflictStrategy>("skip");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);

  const [validationResult, setValidationResult] = useState<ImportValidationSummary | null>(null);
  const [commitResult, setCommitResult] = useState<ImportCommitSummary | null>(null);

  // Batch history query
  const batchesQueryKey = ["organization-imports", organizationId];
  const batchesQuery = useQuery({
    queryKey: batchesQueryKey,
    queryFn: () => listPlatformImportBatches(organizationId),
  });

  const handleDownloadTemplate = async (
    targetResource: ImportResourceType,
    format: "xlsx" | "csv",
  ) => {
    try {
      await downloadPlatformImportTemplate(organizationId, targetResource, format);
      toast.success(
        "Template downloaded",
        `Standard ${format.toUpperCase()} template for ${targetResource} generated for ${organizationName}.`,
      );
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to download template.";
      toast.error("Download failed", msg);
    }
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setValidationResult(null);
      setCommitResult(null);
    }
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      setSelectedFile(file);
      setValidationResult(null);
      setCommitResult(null);
    }
  };

  const handleValidate = async () => {
    if (!selectedFile) return;
    setIsValidating(true);
    setCommitResult(null);
    try {
      const summary = await validatePlatformImport(organizationId, resourceType, selectedFile);
      setValidationResult(summary);
      if (summary.invalidRows === 0) {
        toast.success(
          "Validation passed",
          `All ${summary.validRows} rows in ${selectedFile.name} are syntactically valid and ready to commit.`,
        );
      } else {
        toast.info(
          "Validation issues found",
          `${summary.invalidRows} row(s) contain format or required-value errors. Review diagnostics below.`,
        );
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Spreadsheet validation failed.";
      toast.error("Validation error", msg);
    } finally {
      setIsValidating(false);
    }
  };

  const handleCommit = async () => {
    if (!selectedFile) return;
    setIsCommitting(true);
    try {
      const summary = await commitPlatformImport(
        organizationId,
        resourceType,
        selectedFile,
        conflictStrategy,
      );
      setCommitResult(summary);
      toast.success(
        "Bulk import completed",
        `Successfully committed ${summary.createdCount} new, ${summary.updatedCount} updated, ${summary.skippedCount} skipped record(s).`,
      );
      queryClient.invalidateQueries({ queryKey: batchesQueryKey });
      queryClient.invalidateQueries({ queryKey: ["organization-details", organizationId] });
      queryClient.invalidateQueries({ queryKey: ["students"] });
      queryClient.invalidateQueries({ queryKey: ["parents"] });
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.message : "Import transaction failed and rolled back cleanly.";
      toast.error("Import failed", msg);
    } finally {
      setIsCommitting(false);
    }
  };

  const handleClearFile = () => {
    setSelectedFile(null);
    setValidationResult(null);
    setCommitResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <div className={styles.panel}>
      {/* Enterprise Platform Governance Banner */}
      <div className={styles.banner}>
        <ShieldCheck size={24} className={styles.bannerIcon} />
        <div className={styles.bannerContent}>
          <div className={styles.bannerTitle}>
            Enterprise Centralized Data Import — {organizationName}
          </div>
          <div className={styles.bannerText}>
            This interface is restricted exclusively to RAAD-TECH Platform Administration. Client
            organizations prepare their data using standardized Excel templates and return them to
            RAAD-TECH staff. All imports are validated, previewed, and transacted within this
            organization's isolated tenant scope.
          </div>
        </div>
      </div>

      {/* Section 1: Standardized Templates */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionHeaderLeft}>
            <div className={styles.sectionTitle}>
              <Download size={18} />
              1. Official Excel & CSV Templates
            </div>
            <div className={styles.sectionSubtitle}>
              Provide these pre-formatted workbooks to the client organization's administrative team.
            </div>
          </div>
        </div>

        <div className={styles.templateGrid}>
          {/* Unified Bus Manifest Template Card */}
          <div className={styles.templateCard} style={{ borderColor: "var(--color-brand-primary)" }}>
            <div className={styles.templateCardTop}>
              <div className={styles.templateCardIcon}>
                <FileSpreadsheet size={20} color="var(--color-brand-primary)" />
              </div>
              <div className={styles.templateCardMeta}>
                <div className={styles.templateCardTitle}>🚌 Bus Manifest Template (Recommended)</div>
                <div className={styles.templateCardDesc}>
                  Unified template per bus: bus name, parent full name &amp; Somali phone (auto password: 1234), and all children with their monthly transport fees. No class/grade required.
                </div>
              </div>
            </div>
            <div className={styles.templateActions}>
              <Button
                variant="primary"
                size="sm"
                leadingIcon={<Download size={14} />}
                onClick={() => handleDownloadTemplate("bus_manifest", "xlsx")}
              >
                Excel (.xlsx)
              </Button>
              <Button
                variant="secondary"
                size="sm"
                leadingIcon={<FileText size={14} />}
                onClick={() => handleDownloadTemplate("bus_manifest", "csv")}
              >
                CSV (.csv)
              </Button>
            </div>
          </div>

          {/* Students Template Card */}
          <div className={styles.templateCard}>
            <div className={styles.templateCardTop}>
              <div className={styles.templateCardIcon}>
                <FileSpreadsheet size={20} />
              </div>
              <div className={styles.templateCardMeta}>
                <div className={styles.templateCardTitle}>Student Enrollment Template</div>
                <div className={styles.templateCardDesc}>
                  Includes student full name, date of birth, gender, external reference (student ID),
                  and parent contact links.
                </div>
              </div>
            </div>
            <div className={styles.templateActions}>
              <Button
                variant="secondary"
                size="sm"
                leadingIcon={<Download size={14} />}
                onClick={() => handleDownloadTemplate("students", "xlsx")}
              >
                Excel (.xlsx)
              </Button>
              <Button
                variant="secondary"
                size="sm"
                leadingIcon={<FileText size={14} />}
                onClick={() => handleDownloadTemplate("students", "csv")}
              >
                CSV (.csv)
              </Button>
            </div>
          </div>

          {/* Parents Template Card */}
          <div className={styles.templateCard}>
            <div className={styles.templateCardTop}>
              <div className={styles.templateCardIcon}>
                <FileSpreadsheet size={20} />
              </div>
              <div className={styles.templateCardMeta}>
                <div className={styles.templateCardTitle}>Parents & Guardians Template</div>
                <div className={styles.templateCardDesc}>
                  Includes parent full name, primary phone (+252 Somali normalization), secondary
                  phone, email, and address.
                </div>
              </div>
            </div>
            <div className={styles.templateActions}>
              <Button
                variant="secondary"
                size="sm"
                leadingIcon={<Download size={14} />}
                onClick={() => handleDownloadTemplate("parents", "xlsx")}
              >
                Excel (.xlsx)
              </Button>
              <Button
                variant="secondary"
                size="sm"
                leadingIcon={<FileText size={14} />}
                onClick={() => handleDownloadTemplate("parents", "csv")}
              >
                CSV (.csv)
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* Section 2: Upload, Validation & Execution */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionHeaderLeft}>
            <div className={styles.sectionTitle}>
              <UploadCloud size={18} />
              2. Upload & Execute Bulk Import
            </div>
            <div className={styles.sectionSubtitle}>
              Select target entity, configure conflict policy, validate rows, and execute atomic commit.
            </div>
          </div>
        </div>

        {/* Controls: Resource & Conflict Strategy */}
        <div className={styles.controlsRow}>
          <div className={styles.controlGroup}>
            <span className={styles.controlLabel}>Entity Type</span>
            <div className={styles.segmentedControl}>
              <button
                type="button"
                className={`${styles.segmentedButton} ${
                  resourceType === "bus_manifest" ? styles.segmentedButtonActive : ""
                }`}
                onClick={() => {
                  setResourceType("bus_manifest");
                  setValidationResult(null);
                  setCommitResult(null);
                }}
              >
                🚌 Bus Manifest (Recommended)
              </button>
              <button
                type="button"
                className={`${styles.segmentedButton} ${
                  resourceType === "students" ? styles.segmentedButtonActive : ""
                }`}
                onClick={() => {
                  setResourceType("students");
                  setValidationResult(null);
                  setCommitResult(null);
                }}
              >
                Students
              </button>
              <button
                type="button"
                className={`${styles.segmentedButton} ${
                  resourceType === "parents" ? styles.segmentedButtonActive : ""
                }`}
                onClick={() => {
                  setResourceType("parents");
                  setValidationResult(null);
                  setCommitResult(null);
                }}
              >
                Parents
              </button>
            </div>
          </div>

          <div className={styles.controlGroup}>
            <span className={styles.controlLabel}>Conflict Resolution</span>
            <select
              className={styles.selectInput}
              value={conflictStrategy}
              onChange={(e) => setConflictStrategy(e.target.value as ImportConflictStrategy)}
            >
              <option value="skip">Skip duplicates (preserve existing records)</option>
              <option value="overwrite">Overwrite / update existing matching records</option>
            </select>
          </div>
        </div>

        {/* File Drag and Drop Zone */}
        {!selectedFile ? (
          <div
            className={`${styles.dropzone} ${isDragOver ? styles.dropzoneActive : ""}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls,.csv"
              style={{ display: "none" }}
              onChange={handleFileChange}
            />
            <UploadCloud size={32} className={styles.dropzoneIcon} />
            <div className={styles.dropzoneTitle}>
              Click to browse or drag and drop completed workbook
            </div>
            <div className={styles.dropzoneSubtitle}>
              Supports Microsoft Excel (.xlsx, .xls) and standard Comma-Separated Values (.csv)
            </div>
          </div>
        ) : (
          <div className={styles.selectedFileBar}>
            <div className={styles.fileMeta}>
              <FileSpreadsheet size={22} color="var(--color-brand-primary)" />
              <div>
                <div className={styles.fileName}>{selectedFile.name}</div>
                <div className={styles.fileSize}>{formatBytes(selectedFile.size)}</div>
              </div>
            </div>
            <Button
              variant="secondary"
              size="sm"
              leadingIcon={<Trash2 size={14} />}
              onClick={handleClearFile}
              disabled={isValidating || isCommitting}
            >
              Remove
            </Button>
          </div>
        )}

        {/* Validation Trigger Button */}
        {selectedFile && !validationResult && !commitResult && (
          <div className={styles.actionRow}>
            <Button
              leadingIcon={<CheckCircle2 size={16} />}
              onClick={handleValidate}
              loading={isValidating}
            >
              Validate Spreadsheet
            </Button>
          </div>
        )}

        {/* Validation Diagnostics Output */}
        {validationResult && (
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
            <div className={styles.metricsGrid}>
              <div className={styles.metricCard}>
                <span className={styles.metricLabel}>Total Rows</span>
                <span className={styles.metricValue}>{validationResult.totalRows}</span>
              </div>
              <div className={styles.metricCard}>
                <span className={styles.metricLabel}>Valid Rows</span>
                <span className={`${styles.metricValue} ${styles.metricSuccess}`}>
                  {validationResult.validRows}
                </span>
              </div>
              <div className={styles.metricCard}>
                <span className={styles.metricLabel}>Invalid Rows</span>
                <span
                  className={`${styles.metricValue} ${
                    validationResult.invalidRows > 0 ? styles.metricDanger : ""
                  }`}
                >
                  {validationResult.invalidRows}
                </span>
              </div>
            </div>

            {/* Error Diagnostics List */}
            {validationResult.errors.length > 0 && (
              <div className={styles.errorBox}>
                <div className={styles.errorBoxHeader}>
                  <AlertCircle size={16} />
                  Validation Diagnostics ({validationResult.errors.length} issue(s))
                </div>
                <div className={styles.errorList}>
                  {validationResult.errors.map((err, idx) => (
                    <div key={idx} className={styles.errorItem}>
                      <span className={styles.errorRowBadge}>Row {err.rowNumber}:</span>
                      <span>
                        [{err.column}] {err.errorMessage}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Data Preview Table */}
            {validationResult.preview.length > 0 && (
              <div className={styles.previewWrapper}>
                <table className={styles.previewTable}>
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Status</th>
                      <th>Data Preview</th>
                      <th>Notes / Issues</th>
                    </tr>
                  </thead>
                  <tbody>
                    {validationResult.preview.slice(0, 15).map((row) => (
                      <tr
                        key={row.rowNumber}
                        className={!row.isValid ? styles.previewTableRowInvalid : undefined}
                      >
                        <td className={styles.mono}>#{row.rowNumber}</td>
                        <td>
                          {row.isValid ? (
                            <Badge variant="success">Valid</Badge>
                          ) : (
                            <Badge variant="danger">Invalid</Badge>
                          )}
                        </td>
                        <td>
                          {Object.entries(row.data)
                            .slice(0, 4)
                            .map(([k, v]) => `${k}: ${String(v ?? "—")}`)
                            .join(" | ")}
                        </td>
                        <td>
                          {row.errors.length > 0 ? (
                            <span style={{ color: "var(--color-danger)" }}>
                              {row.errors.join("; ")}
                            </span>
                          ) : (
                            <span style={{ color: "var(--color-text-muted)" }}>None</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Execution Confirmation Actions */}
            {!commitResult && (
              <div className={styles.actionRow}>
                <Button
                  variant="secondary"
                  onClick={handleClearFile}
                  disabled={isCommitting}
                >
                  Cancel
                </Button>
                <Button
                  leadingIcon={<UploadCloud size={16} />}
                  onClick={handleCommit}
                  loading={isCommitting}
                  disabled={validationResult.validRows === 0}
                >
                  Commit {validationResult.validRows} Record(s) to Tenant
                </Button>
              </div>
            )}
          </div>
        )}

        {/* Post-Commit Summary Success Box */}
        {commitResult && (
          <div className={styles.successBox}>
            <CheckCircle2 size={24} className={styles.successIcon} />
            <div>
              <div className={styles.successTitle}>
                Bulk Import Executed Successfully (Batch #{commitResult.batchId})
              </div>
              <div className={styles.successStats}>
                Processed {commitResult.totalProcessed} records:{" "}
                <strong>{commitResult.createdCount} created</strong>,{" "}
                <strong>{commitResult.updatedCount} updated</strong>,{" "}
                <strong>{commitResult.skippedCount} skipped</strong>.
              </div>
              <div style={{ marginTop: "var(--space-3)" }}>
                <Button size="sm" variant="secondary" onClick={handleClearFile}>
                  Import Another File
                </Button>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Section 3: Import Batch Audit History */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionHeaderLeft}>
            <div className={styles.sectionTitle}>
              <RefreshCw size={18} />
              3. Import Batch Audit History
            </div>
            <div className={styles.sectionSubtitle}>
              Persistent history of all bulk ingestions committed to this organization.
            </div>
          </div>
          <Button
            size="sm"
            variant="secondary"
            leadingIcon={<RefreshCw size={13} />}
            onClick={() => batchesQuery.refetch()}
            loading={batchesQuery.isFetching}
          >
            Refresh
          </Button>
        </div>

        {batchesQuery.isLoading ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            <Skeleton height={32} />
            <Skeleton height={32} />
            <Skeleton height={32} />
          </div>
        ) : batchesQuery.isError ? (
          <EmptyState
            icon={<AlertCircle size={22} />}
            title="Could not load batch history"
            description="Failed to retrieve past import logs for this organization."
          />
        ) : (batchesQuery.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            icon={<FileSpreadsheet size={22} />}
            title="No imports recorded yet"
            description="When platform staff execute imports for this organization, batch logs and audit metrics will appear here."
          />
        ) : (
          <div className={styles.batchTableWrapper}>
            <table className={styles.batchTable}>
              <thead>
                <tr>
                  <th>Batch ID</th>
                  <th>Entity</th>
                  <th>Status</th>
                  <th>Total Rows</th>
                  <th>Created</th>
                  <th>Updated</th>
                  <th>Skipped</th>
                  <th>Strategy</th>
                  <th>Committed At</th>
                  <th>Operator</th>
                </tr>
              </thead>
              <tbody>
                {batchesQuery.data?.items.map((batch) => (
                  <tr key={batch.id}>
                    <td className={styles.mono}>{batch.id}</td>
                    <td>
                      <Badge variant="neutral">
                        {batch.resourceType.toUpperCase()}
                      </Badge>
                    </td>
                    <td>
                      <Badge
                        variant={
                          batch.status === "committed"
                            ? "success"
                            : batch.status === "failed"
                              ? "danger"
                              : "neutral"
                        }
                      >
                        {batch.status}
                      </Badge>
                    </td>
                    <td>{batch.totalRows}</td>
                    <td style={{ color: "var(--color-success)" }}>+{batch.createdCount}</td>
                    <td style={{ color: "var(--color-brand-primary)" }}>{batch.updatedCount}</td>
                    <td style={{ color: "var(--color-text-muted)" }}>{batch.skippedCount}</td>
                    <td className={styles.mono}>{batch.conflictStrategy ?? "default"}</td>
                    <td>{formatDate(batch.committedAt ?? batch.createdAt)}</td>
                    <td className={styles.mono}>{batch.actorUserId}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
