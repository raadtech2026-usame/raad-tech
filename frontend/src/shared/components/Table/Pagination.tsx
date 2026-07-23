import { ChevronLeft, ChevronRight } from "lucide-react";
import { IconButton } from "../IconButton/IconButton";
import styles from "./Pagination.module.css";

export interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

/** Footer for `OffsetPage<T>`-backed tables (`core/pagination`'s offset envelope — API Contracts
 * §7/§8). Cursor-paginated views (`GET /tracking/trips/{id}/positions`, `GET /notifications`)
 * don't know a total and use a simpler "load more" affordance instead, not this component. */
export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);

  return (
    <div className={styles.bar}>
      <span>
        {total === 0 ? (
          "No results"
        ) : (
          <>
            <span className={styles.pageLabel}>
              {start}–{end}
            </span>{" "}
            of {total}
          </>
        )}
      </span>
      <div className={styles.controls}>
        <IconButton
          icon={<ChevronLeft size={16} />}
          aria-label="Previous page"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        />
        <span className={styles.pageLabel}>
          {page} / {pageCount}
        </span>
        <IconButton
          icon={<ChevronRight size={16} />}
          aria-label="Next page"
          size="sm"
          disabled={page >= pageCount}
          onClick={() => onPageChange(page + 1)}
        />
      </div>
    </div>
  );
}
