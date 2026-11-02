import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  FileText,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import { Button } from "../../../shared/components/Button/Button";
import { Badge } from "../../../shared/components/Badge/Badge";
import {
  commitImport,
  downloadImportTemplate,
  validateImport,
  type ImportCommitSummary,
  type ImportValidationSummary,
} from "./api";
import styles from "./BulkImportDialog.module.css";

export interface BulkImportDialogProps {
  open: boolean;
  onClose: () => void;
  resourceType: "students" | "parents";
  onSuccess?: () => void;
}

type WizardStep = 1 | 2 | 3;

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function BulkImportDialog({
  open,
  onClose,
  resourceType,
  onSuccess,
}: BulkImportDialogProps) {
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<WizardStep>(1);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);

  const [validationResult, setValidationResult] = useState<ImportValidationSummary | null>(null);
  const [commitResult, setCommitResult] = useState<ImportCommitSummary | null>(null);

  useEffect(() => {
    if (open) {
      setStep(1);
      setSelectedFile(null);
      setValidationResult(null);
      setCommitResult(null);
    }
  }, [open]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !isCommitting) {
        onClose();
      }
    }
    if (open) {
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, isCommitting, onClose]);

  if (!open) return null;

  const resourceTitle = resourceType === "students" ? "Students" : "Parents";

  const handleDownloadTemplate = async (format: "xlsx" | "csv") => {
    try {
      await downloadImportTemplate(resourceType, format);
      toast.success(
        "Template downloaded",
        `Sample ${format.toUpperCase()} template for ${resourceTitle} is ready.`,
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
    }
  };

  const handleStartValidation = async () => {
    if (!selectedFile) return;
    setIsValidating(true);
    try {
      const summary = await validateImport(resourceType, selectedFile);
      setValidationResult(summary);
      setStep(2);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "File validation failed. Please check format.";
      toast.error("Validation error", msg);
    } finally {
      setIsValidating(false);
    }
  };

  const handleCommit = async () => {
    if (!selectedFile) return;
    setIsCommitting(true);
    setStep(3);
    try {
      const summary = await commitImport(resourceType, selectedFile);
      setCommitResult(summary);
      toast.success(
        "Import succeeded",
        `Successfully imported ${summary.createdCount + summary.updatedCount} ${resourceTitle.toLowerCase()}.`,
      );
      if (onSuccess) {
        onSuccess();
      }
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Import transaction failed and rolled back cleanly.";
      toast.error("Import failed", msg);
      // Stay on step 2 on failure so user can review/edit
      setStep(2);
    } finally {
      setIsCommitting(false);
    }
  };

  return (
    <>
      <div className={styles.scrim} onClick={isCommitting ? undefined : onClose} />
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="bulk-import-title">
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <div className={styles.headerIcon}>
              <UploadCloud size={22} />
            </div>
            <div>
              <div id="bulk-import-title" className={styles.title}>
                Bulk Import {resourceTitle}
              </div>
              <div className={styles.description}>
                Ingest {resourceTitle.toLowerCase()} seamlessly from Excel (.xlsx) or CSV (.csv) spreadsheets.
              </div>
            </div>
          </div>
          {!isCommitting && (
            <button
              type="button"
              className={styles.closeButton}
              onClick={onClose}
              aria-label="Close dialog"
            >
              <X size={18} />
            </button>
          )}
        </div>

        {/* Stepper */}
        <div className={styles.stepper}>
          <div
            className={`${styles.stepItem} ${
              step === 1 ? styles.stepActive : step > 1 ? styles.stepDone : ""
            }`}
          >
            <span className={styles.stepBadge}>{step > 1 ? "✓" : "1"}</span>
            <span>1. Upload File</span>
          </div>
          <div className={styles.stepDivider} />
          <div
            className={`${styles.stepItem} ${
              step === 2 ? styles.stepActive : step > 2 ? styles.stepDone : ""
            }`}
          >
            <span className={styles.stepBadge}>{step > 2 ? "✓" : "2"}</span>
            <span>2. Preview & Validate</span>
          </div>
          <div className={styles.stepDivider} />
          <div className={`${styles.stepItem} ${step === 3 ? styles.stepActive : ""}`}>
            <span className={styles.stepBadge}>3</span>
            <span>3. Import Summary</span>
          </div>
        </div>

        {/* Step 1: Upload */}
        {step === 1 && (
          <div className={styles.body}>
            <div className={styles.templateCard}>
              <div className={styles.templateHeader}>
                <div>
                  <div className={styles.templateTitle}>Starter Templates with Example Rows</div>
                  <div className={styles.description}>
                    Download our pre-formatted template with all documented columns and Somali phone number guidelines.
                  </div>
                </div>
                <div className={styles.templateButtons}>
                  <Button
                    size="sm"
                    variant="secondary"
                    leadingIcon={<FileSpreadsheet size={14} />}
                    onClick={() => handleDownloadTemplate("xlsx")}
                  >
                    Template (.xlsx)
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    leadingIcon={<Download size={14} />}
                    onClick={() => handleDownloadTemplate("csv")}
                  >
                    Template (.csv)
                  </Button>
                </div>
              </div>
            </div>

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
                accept=".xlsx,.csv,.xls"
                style={{ display: "none" }}
                onChange={handleFileChange}
              />
              <UploadCloud size={40} className={styles.dropzoneIcon} />
              <div className={styles.dropzoneTitle}>
                {selectedFile ? "Click or drag to replace file" : "Choose an Excel or CSV file"}
              </div>
              <div className={styles.dropzoneHint}>
                Drag & drop your file here, or click to browse. Somali phone numbers will be automatically normalized to +252.
              </div>
            </div>

            {selectedFile && (
              <div className={styles.selectedFileCard}>
                <div className={styles.fileInfo}>
                  <FileText size={20} color="var(--color-brand-primary)" />
                  <div>
                    <div className={styles.fileName}>{selectedFile.name}</div>
                    <div className={styles.fileSize}>{formatFileSize(selectedFile.size)}</div>
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  leadingIcon={<Trash2 size={14} />}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedFile(null);
                    if (fileInputRef.current) fileInputRef.current.value = "";
                  }}
                >
                  Remove
                </Button>
              </div>
            )}

            <div className={styles.actions}>
              <Button variant="secondary" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={!selectedFile || isValidating}
                loading={isValidating}
                leadingIcon={<ArrowRight size={15} />}
                onClick={handleStartValidation}
              >
                Continue to Validate
              </Button>
            </div>
          </div>
        )}

        {/* Step 2: Preview & Validate */}
        {step === 2 && validationResult && (
          <div className={styles.body}>
            <div className={styles.summaryMetrics}>
              <div className={styles.metricCard}>
                <span className={styles.metricLabel}>Total Rows</span>
                <span className={styles.metricValue}>{validationResult.totalRows}</span>
              </div>
              <div className={styles.metricCard}>
                <span className={styles.metricLabel}>Valid Records</span>
                <span className={`${styles.metricValue} ${styles.metricValueSuccess}`}>
                  {validationResult.validRows}
                </span>
              </div>
              <div className={styles.metricCard}>
                <span className={styles.metricLabel}>Flagged / Invalid</span>
                <span
                  className={`${styles.metricValue} ${
                    validationResult.invalidRows > 0 ? styles.metricValueDanger : ""
                  }`}
                >
                  {validationResult.invalidRows}
                </span>
              </div>
            </div>

            {validationResult.errors.length > 0 && (
              <div className={styles.errorsContainer}>
                <div className={styles.errorsTitle}>
                  <AlertCircle size={15} />
                  <span>Validation Issues ({validationResult.errors.length}) — These rows will be skipped</span>
                </div>
                <ul className={styles.errorsList}>
                  {validationResult.errors.slice(0, 10).map((err, idx) => (
                    <li key={idx}>
                      <strong>Row {err.rowNumber}</strong> ({err.column}): {err.errorMessage}
                    </li>
                  ))}
                  {validationResult.errors.length > 10 && (
                    <li>…and {validationResult.errors.length - 10} more issues.</li>
                  )}
                </ul>
              </div>
            )}

            <div className={styles.previewTableWrapper}>
              <table className={styles.previewTable}>
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Row</th>
                    <th>Full Name</th>
                    {resourceType === "students" ? (
                      <>
                        <th>Admission #</th>
                        <th>Grade</th>
                        <th>Parent Phone</th>
                      </>
                    ) : (
                      <>
                        <th>Phone</th>
                        <th>Email</th>
                        <th>Address</th>
                      </>
                    )}
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {validationResult.preview.slice(0, 25).map((row) => (
                    <tr
                      key={row.rowNumber}
                      className={row.isValid ? styles.rowValid : styles.rowInvalid}
                    >
                      <td>
                        {row.isValid ? (
                          <Badge variant="success">
                            Valid
                          </Badge>
                        ) : (
                          <Badge variant="danger">
                            Invalid
                          </Badge>
                        )}
                      </td>
                      <td>{row.rowNumber}</td>
                      <td>
                        <strong>{row.data.full_name || "—"}</strong>
                      </td>
                      {resourceType === "students" ? (
                        <>
                          <td>{row.data.admission_number || "—"}</td>
                          <td>{row.data.grade_level || "—"}</td>
                          <td>{row.data.parent_phone || "—"}</td>
                        </>
                      ) : (
                        <>
                          <td>{row.data.phone || "—"}</td>
                          <td>{row.data.email || "—"}</td>
                          <td>{row.data.address || "—"}</td>
                        </>
                      )}
                      <td>
                        {row.errors.length > 0 ? (
                          <span style={{ color: "var(--color-danger)" }}>{row.errors[0]}</span>
                        ) : (
                          <span style={{ color: "var(--color-text-muted)" }}>Ready to import</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className={styles.actions}>
              <Button
                variant="secondary"
                leadingIcon={<ArrowLeft size={15} />}
                onClick={() => setStep(1)}
              >
                Back
              </Button>
              <Button
                variant="primary"
                disabled={validationResult.validRows === 0 || isCommitting}
                loading={isCommitting}
                onClick={handleCommit}
              >
                Import {validationResult.validRows} {resourceTitle}
              </Button>
            </div>
          </div>
        )}

        {/* Step 3: Commit Progress / Success Summary */}
        {step === 3 && (
          <div className={styles.body}>
            {isCommitting ? (
              <div className={styles.successContainer}>
                <div className={styles.successTitle}>Importing {resourceTitle}…</div>
                <div className={styles.successDescription}>
                  Persisting batch in an atomic database transaction. Please do not close this window.
                </div>
              </div>
            ) : commitResult ? (
              <div className={styles.successContainer}>
                <div className={styles.successIcon}>
                  <CheckCircle2 size={36} />
                </div>
                <div className={styles.successTitle}>Import Successfully Completed!</div>
                <div className={styles.successDescription}>
                  {resourceTitle} have been ingested and linked cleanly in your organization scope.
                </div>

                <div className={styles.summaryMetrics} style={{ width: "100%", maxWidth: 540 }}>
                  <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>Created</span>
                    <span className={`${styles.metricValue} ${styles.metricValueSuccess}`}>
                      {commitResult.createdCount}
                    </span>
                  </div>
                  <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>Updated</span>
                    <span className={styles.metricValue}>{commitResult.updatedCount}</span>
                  </div>
                  <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>Skipped</span>
                    <span className={styles.metricValue}>{commitResult.skippedCount}</span>
                  </div>
                </div>

                <div className={styles.actions} style={{ width: "100%" }}>
                  <Button variant="primary" onClick={onClose}>
                    Done
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </>
  );
}
