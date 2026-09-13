import styles from "./ReportSummary.module.css";

export interface ReportSummaryProps {
  metadata: Record<string, string>;
}

/** The preview's metadata line — "Total Parents: 42", "Receivables: 1,204.00" — the same
 * key/value pairs `ReportTable.metadata` (`reporting.application.report_table`) already carries
 * server-side, rendered as-is rather than recomputed from the rows (ADR-0041 §3's single-source
 * discipline: preview and export must never disagree). */
export function ReportSummary({ metadata }: ReportSummaryProps) {
  const entries = Object.entries(metadata);
  if (entries.length === 0) return null;

  return (
    <div className={styles.row}>
      {entries.map(([key, value]) => (
        <span key={key} className={styles.item}>
          <strong>{key}:</strong> {value}
        </span>
      ))}
    </div>
  );
}
