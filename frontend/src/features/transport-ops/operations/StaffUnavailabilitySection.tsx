import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "../../../shared/components/Button/Button";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { listUnavailability, type Unavailability } from "./api";
import { CoverForm, UnavailabilityForm } from "./OperationsForms";
import { UnavailabilityList } from "./DailyOperationsPage";
import styles from "./Operations.module.css";

export interface StaffUnavailabilitySectionProps {
  staffId: string;
  staffName: string;
  canManage: boolean;
}

/** The Unavailability section of a staff profile (ADR-0053). Imported by the Transport Staff
 * page — a component import, the same narrow cross-folder precedent as the vehicle Crew
 * section. */
export function StaffUnavailabilitySection({ staffId, staffName, canManage }: StaffUnavailabilitySectionProps) {
  const [recording, setRecording] = useState(false);
  const [covering, setCovering] = useState<Unavailability | null>(null);
  const query = useQuery({
    queryKey: ["operations", "unavailability", "staff", staffId],
    queryFn: () => listUnavailability({ staffId }),
  });
  return (
    <section className={styles.section} aria-label="Unavailability">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Unavailability</span>
        {canManage && (
          <Button size="sm" variant="secondary" onClick={() => setRecording(true)}>
            Record
          </Button>
        )}
      </div>
      {query.isLoading ? (
        <Skeleton height={40} />
      ) : query.isError ? (
        <p className={styles.empty}>Could not load unavailability.</p>
      ) : (
        <UnavailabilityList items={query.data ?? []} canManage={canManage} showStaff={false} onCover={setCovering} />
      )}
      <UnavailabilityForm open={recording} onClose={() => setRecording(false)} staffId={staffId} staffName={staffName} />
      <CoverForm unavailability={covering} onClose={() => setCovering(null)} />
    </section>
  );
}
