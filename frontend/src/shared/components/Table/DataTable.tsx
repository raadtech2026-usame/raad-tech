import { useReactTable, getCoreRowModel, flexRender, type ColumnDef } from "@tanstack/react-table";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import clsx from "clsx";
import { Skeleton } from "../Skeleton/Skeleton";
import styles from "./DataTable.module.css";

/** Column-level metadata beyond what `@tanstack/react-table`'s `ColumnDef` covers natively.
 * `sortField` names the backend `SortSpec` field this column sorts by (`?sort=field`) — sorting
 * is always server-side (API Contracts §7/§8's pagination envelope), never client-side, so this
 * table never re-sorts `data` itself, only reports which field/direction the user asked for. */
export interface DataTableColumnMeta {
  sortField?: string;
  align?: "left" | "right";
}

export interface SortState {
  field: string;
  direction: "asc" | "desc";
}

export interface DataTableProps<T> {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  getRowId: (row: T) => string;
  onRowClick?: (row: T) => void;
  isLoading?: boolean;
  skeletonRows?: number;
  emptyState?: React.ReactNode;
  sort?: SortState | null;
  onSortChange?: (field: string) => void;
}

export function DataTable<T>({
  columns,
  data,
  getRowId,
  onRowClick,
  isLoading,
  skeletonRows = 6,
  emptyState,
  sort,
  onSortChange,
}: DataTableProps<T>) {
  const table = useReactTable({
    data,
    columns,
    getRowId: (row) => getRowId(row),
    getCoreRowModel: getCoreRowModel(),
  });

  const showEmpty = !isLoading && data.length === 0;

  return (
    <div className={styles.wrap}>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className={styles.headRow}>
                {headerGroup.headers.map((header) => {
                  const meta = header.column.columnDef.meta as DataTableColumnMeta | undefined;
                  const sortField = meta?.sortField;
                  const isSorted = sortField && sort?.field === sortField;

                  return (
                    <th
                      key={header.id}
                      className={styles.headCell}
                      style={meta?.align === "right" ? { textAlign: "right" } : undefined}
                    >
                      {sortField ? (
                        <button
                          type="button"
                          className={styles.sortable}
                          onClick={() => onSortChange?.(sortField)}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {isSorted ? (
                            sort?.direction === "asc" ? (
                              <ChevronUp size={12} />
                            ) : (
                              <ChevronDown size={12} />
                            )
                          ) : (
                            <ChevronsUpDown size={12} opacity={0.5} />
                          )}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {isLoading &&
              Array.from({ length: skeletonRows }).map((_, rowIndex) => (
                <tr key={`skeleton-${rowIndex}`} className={styles.bodyRow}>
                  {columns.map((_, colIndex) => (
                    <td key={colIndex} className={styles.skeletonCell}>
                      <Skeleton height={16} width={colIndex === 0 ? "70%" : "50%"} />
                    </td>
                  ))}
                </tr>
              ))}

            {!isLoading &&
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className={clsx(styles.bodyRow, onRowClick && styles.clickable)}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                >
                  {row.getVisibleCells().map((cell) => {
                    const meta = cell.column.columnDef.meta as DataTableColumnMeta | undefined;
                    return (
                      <td
                        key={cell.id}
                        className={styles.bodyCell}
                        style={meta?.align === "right" ? { textAlign: "right" } : undefined}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    );
                  })}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {showEmpty && emptyState}
    </div>
  );
}
