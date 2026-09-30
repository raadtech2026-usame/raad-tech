import { useQuery } from "@tanstack/react-query";
import { FileWarning } from "lucide-react";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { ApiError } from "../../../shared/api/types";
import { listExpiringDocuments } from "./api";
import { daysLeftLabel, documentStatusLabel, documentStatusTone, formatDay } from "./labels";
import styles from "./Staff.module.css";

export interface ExpiringDocumentsPanelProps {
  onOpenStaff: (staffId: string) => void;
  /** Show at most this many rows (the dashboard card); all when absent. */
  limit?: number;
}

/**
 * Current staff documents that are expiring or already expired, soonest first (ADR-0051 §3).
 * Renewed documents never appear: recording the renewal is what clears a row.
 */
export function ExpiringDocumentsPanel({ onOpenStaff, limit }: ExpiringDocumentsPanelProps) {
  const query = useQuery({ queryKey: ["transport-staff", "expiring"], queryFn: listExpiringDocuments });

  if (query.isLoading) return <Skeleton height={96} />;
  if (query.isError) {
    return (
      <EmptyState
        icon={<FileWarning size={22} />}
        title="Could not load documents"
        description={query.error instanceof ApiError ? query.error.message : "Please try again."}
      />
    );
  }
  const documents = query.data ?? [];
  if (documents.length === 0) {
    return (
      <EmptyState
        icon={<FileWarning size={22} />}
        title="Nothing due"
        description="No staff document is expiring soon or has expired."
      />
    );
  }
  const shown = limit ? documents.slice(0, limit) : documents;
  return (
    <section className={styles.section} aria-label="Documents due">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Documents due</span>
        <span className={styles.itemMeta}>{documents.length} in total</span>
      </div>
      <ul className={styles.list}>
        {shown.map((document) => (
          <li key={document.id} className={styles.item}>
            <div className={styles.itemMain}>
              <span className={styles.itemTitle}>
                {document.staffName} · {document.typeName}
              </span>
              <span className={styles.itemMeta}>
                {daysLeftLabel(document.daysLeft)} · {formatDay(document.expiresOn)}
              </span>
            </div>
            <div className={styles.itemActions}>
              <Badge variant={documentStatusTone(document.status)}>{documentStatusLabel(document.status)}</Badge>
              <Button size="sm" variant="ghost" onClick={() => onOpenStaff(document.staffId)}>
                Open profile
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
