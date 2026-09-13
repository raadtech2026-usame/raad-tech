import clsx from "clsx";
import type { ReportTablePreview } from "../api";
import styles from "./ReportResultTable.module.css";

export interface ReportResultTableProps {
  table: ReportTablePreview;
}

/** The Report Center's one table renderer — used for every one of the 13 organization reports'
 * previews, never a per-report table layout. Column alignment (`numericColumns`) and the total
 * row are both driven entirely by what the server already computed
 * (`ReportExportService.build_table`), the same data PDF/Excel export renders. */
export function ReportResultTable({ table }: ReportResultTableProps) {
  if (table.rows.length === 0) {
    return <p className={styles.empty}>No rows for this selection.</p>;
  }

  return (
    <div className={styles.scroll}>
      <table className={styles.table}>
        <thead>
          <tr>
            {table.headers.map((header, index) => (
              <th key={header + index} className={table.numericColumns.includes(index) ? styles.alignRight : undefined}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className={table.numericColumns.includes(cellIndex) ? styles.alignRight : undefined}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {table.totalRow && (
          <tfoot>
            <tr>
              {table.totalRow.map((cell, index) => (
                <td
                  key={index}
                  className={clsx(styles.total, table.numericColumns.includes(index) && styles.alignRight)}
                >
                  {cell}
                </td>
              ))}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}
