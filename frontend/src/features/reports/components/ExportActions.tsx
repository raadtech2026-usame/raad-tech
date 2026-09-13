import { FileSpreadsheet, FileText, Printer } from "lucide-react";
import { Button } from "../../../shared/components/Button/Button";
import type { ReportFormat } from "../api";
import styles from "./ExportActions.module.css";

export interface ExportActionsProps {
  /** `null` when nothing is exporting, otherwise the format currently in flight — disables the
   * other two buttons so a caller can't queue a second export mid-request. */
  busy: ReportFormat | null;
  /** Export is only ever offered once a preview has rendered (directive: "Do not immediately
   * download a file when the user clicks View" / preview-before-export) — the caller passes
   * `false` until `previewReport` has succeeded for the current filters. */
  enabled: boolean;
  onExport: (format: ReportFormat, print?: boolean) => void;
}

/** PDF / Excel / Print — the same three actions every one of the 13 reports offers, in one place
 * rather than duplicated per report. Print reuses the PDF (the artifact a user would print
 * anyway), matching the pre-redesign card grid's own behavior. */
export function ExportActions({ busy, enabled, onExport }: ExportActionsProps) {
  return (
    <div className={styles.row}>
      <Button
        variant="secondary"
        size="sm"
        loading={busy === "pdf"}
        disabled={!enabled || (busy !== null && busy !== "pdf")}
        onClick={() => onExport("pdf")}
      >
        <FileText size={14} /> PDF
      </Button>
      <Button
        variant="secondary"
        size="sm"
        loading={busy === "xlsx"}
        disabled={!enabled || (busy !== null && busy !== "xlsx")}
        onClick={() => onExport("xlsx")}
      >
        <FileSpreadsheet size={14} /> Excel
      </Button>
      <Button
        variant="ghost"
        size="sm"
        disabled={!enabled || busy !== null}
        onClick={() => onExport("pdf", true)}
        title="Downloads the PDF — open it to print"
      >
        <Printer size={14} /> Print
      </Button>
    </div>
  );
}
