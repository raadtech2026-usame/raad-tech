import { ReportSummary } from "./ReportSummary";
import { ReportResultTable } from "./ReportResultTable";
import type { ReportTablePreview } from "../api";
import styles from "./ReportPreviewDocument.module.css";

export interface ReportFilterSummaryItem {
  label: string;
  value: string;
}

export interface ReportPreviewDocumentProps {
  preview: ReportTablePreview;
  /** The human-readable reporting period line (e.g. "March 1 → July 31, 2026", "September 2026",
   * or "All time") — already formatted by the caller from the same filter state used to build the
   * request, never recomputed from the rows. */
  period: string | null;
  /** The report's own applied-filter recap (Parent/Vehicle/Payment status…) — only the filters
   * this report's `accepts` list actually offers, each already resolved to a human-readable label
   * (never a raw id). */
  filters: ReportFilterSummaryItem[];
}

/**
 * A professional, print-friendly document-style rendering of a `ReportTablePreview` — an A4-style
 * report a bursar could review on screen or print, rather than another dashboard widget card.
 *
 * Deliberately its own component (org Report Center only) rather than a restyle of the shared
 * `.previewPanel`/`.previewBody` classes `ReportsPage.module.css` also uses for the platform
 * dashboard's card grid — that grid is explicitly out of this redesign's scope, and reusing its
 * classes here would have changed its look too. Renders the exact same `ReportSummary`/
 * `ReportResultTable` the platform grid uses, unmodified, so the two never disagree on what a row
 * or a total means.
 */
export function ReportPreviewDocument({ preview, period, filters }: ReportPreviewDocumentProps) {
  return (
    <div className={styles.sheet}>
      <header className={styles.header}>
        <h2 className={styles.title}>{preview.title}</h2>
        {preview.subtitle && <p className={styles.subtitle}>{preview.subtitle}</p>}
        {period && <p className={styles.period}>{period}</p>}
      </header>

      {filters.length > 0 && (
        <dl className={styles.filterRecap}>
          {filters.map((item) => (
            <div key={item.label} className={styles.filterRecapItem}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      )}

      <ReportSummary metadata={preview.metadata} />

      <div className={styles.tableWrap}>
        <ReportResultTable table={preview} />
      </div>
    </div>
  );
}
