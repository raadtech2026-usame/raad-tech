import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { EmptyState } from "../../../shared/components/EmptyState/EmptyState";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { ApiError } from "../../../shared/api/types";
import { listStaffCompliance, type Compliance } from "./api";
import { complianceLabel, complianceReasons, complianceTone } from "./labels";
import styles from "./Staff.module.css";

/** A person's document compliance (ADR-0058 §2): the status, then each reason on its own line.
 * Renders nothing for someone who has left (`null`) or when nothing is required of them. */
export function ComplianceSummary({ compliance }: { compliance: Compliance | null }) {
  if (!compliance) return null;
  const reasons = complianceReasons(compliance);
  if (compliance.status === "compliant" && reasons.length === 0) return null;
  return (
    <section className={styles.section} aria-label="Document compliance">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Document compliance</span>
        <Badge variant={complianceTone(compliance.status)} dot>
          {complianceLabel(compliance.status)}
        </Badge>
      </div>
      <ul className={styles.list}>
        {reasons.map((reason) => (
          <li key={reason} className={styles.itemMeta}>
            {reason}
          </li>
        ))}
      </ul>
      {compliance.isBlocked && (
        <p className={styles.warning}>
          Cannot be newly planned as a substitute, timetable driver or trip driver until this is recorded.
        </p>
      )}
    </section>
  );
}

/**
 * Staff who do not meet a document requirement, or are about to stop meeting one, worst first
 * (ADR-0058 §3). Empty, and hidden, until the organization marks a document type as required.
 */
export function CompliancePanel({ onOpenStaff }: { onOpenStaff: (staffId: string) => void }) {
  const query = useQuery({ queryKey: ["transport-staff", "compliance"], queryFn: listStaffCompliance });

  if (query.isLoading) return <Skeleton height={72} />;
  if (query.isError) {
    return (
      <EmptyState
        icon={<ShieldCheck size={22} />}
        title="Could not load compliance"
        description={query.error instanceof ApiError ? query.error.message : "Please try again."}
      />
    );
  }
  const rows = query.data ?? [];
  if (rows.length === 0) return null;
  const failing = rows.filter((r) => r.compliance.status === "not_compliant").length;
  return (
    <section className={styles.section} aria-label="Required documents">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Required documents</span>
        <span className={styles.itemMeta}>
          {failing} not compliant · {rows.length - failing} expiring
        </span>
      </div>
      <ul className={styles.list}>
        {rows.map((row) => (
          <li key={row.staffId} className={styles.item}>
            <div className={styles.itemMain}>
              <span className={styles.itemTitle}>
                {row.staffName}
                {row.roleName ? ` · ${row.roleName}` : ""}
              </span>
              {complianceReasons(row.compliance).map((reason) => (
                <span key={reason} className={styles.itemMeta}>
                  {reason}
                </span>
              ))}
            </div>
            <div className={styles.itemActions}>
              {row.compliance.isBlocked && <Badge variant="danger">Blocks planning</Badge>}
              <Badge variant={complianceTone(row.compliance.status)}>{complianceLabel(row.compliance.status)}</Badge>
              <Button size="sm" variant="ghost" onClick={() => onOpenStaff(row.staffId)}>
                Open profile
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
