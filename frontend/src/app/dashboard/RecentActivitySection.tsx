import { useQuery } from "@tanstack/react-query";
import { ScrollText } from "lucide-react";
import { Card, CardHeader } from "../../shared/components/Card/Card";
import { EmptyState } from "../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../shared/components/Skeleton/Skeleton";
import { ApiError } from "../../shared/api/types";
import { listAuditEntries } from "../../features/platform-analytics/api";
import { formatRelativeTime, humanizeEventName } from "./formatRelativeTime";
import styles from "./RecentActivitySection.module.css";

const PAGE_SIZE = 8;

/**
 * A read-only preview of `GET /admin/audit` (ADR-0007's shared-kernel `audit_entries` ledger) —
 * the first frontend consumer of this route; the full `/platform/audit` page itself remains an
 * honest placeholder (not this session's scope). Shows only `action`/`entityType`/`createdAt` —
 * no actor *name* is resolvable here (`AuditEntry`'s own docstring: only a raw `actorUserId`
 * ULID is available, and a per-row user lookup to resolve it would be a second, unbounded query
 * this widget doesn't perform), so this never fabricates a "by <name>" line.
 */
export function RecentActivitySection() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["dashboard", "recent-activity"],
    queryFn: () =>
      listAuditEntries({
        page: 1,
        pageSize: PAGE_SIZE,
        sort: { field: "created_at", direction: "desc" },
        filters: {},
        search: "",
      }),
    staleTime: 30_000,
  });

  return (
    <Card>
      <CardHeader title="Recent Activity" />
      <div className={styles.body}>
        {isError ? (
          <EmptyState
            icon={<ScrollText size={22} />}
            title="Could not load recent activity"
            description={error instanceof ApiError ? error.message : "Something went wrong. Please try again."}
          />
        ) : isLoading ? (
          <ul className={styles.list}>
            {Array.from({ length: 5 }, (_, i) => (
              <li key={i} className={styles.row}>
                <Skeleton width="70%" height={13} />
                <Skeleton width={60} height={11} />
              </li>
            ))}
          </ul>
        ) : data && data.data.length > 0 ? (
          <ul className={styles.list}>
            {data.data.map((entry) => (
              <li key={entry.id} className={styles.row}>
                <div className={styles.rowMain}>
                  <span className={styles.action}>{humanizeEventName(entry.action)}</span>
                  {entry.entityType && <span className={styles.entity}>{entry.entityType}</span>}
                </div>
                <span className={styles.time}>{formatRelativeTime(entry.createdAt)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            icon={<ScrollText size={22} />}
            title="No activity yet"
            description="Actions taken across the platform will appear here."
          />
        )}
      </div>
    </Card>
  );
}
