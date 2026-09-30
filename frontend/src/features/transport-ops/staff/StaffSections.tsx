import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { ConfirmDialog } from "../../../shared/components/ConfirmDialog/ConfirmDialog";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import {
  endCrewAssignment,
  listCrew,
  listStaffDocuments,
  listVehiclesForPicker,
  type CrewAssignment,
  type StaffDocument,
} from "./api";
import {
  assignmentKindLabel,
  assignmentPeriod,
  daysLeftLabel,
  documentStatusLabel,
  documentStatusTone,
  formatDay,
} from "./labels";
import styles from "./Staff.module.css";

function useEndAssignment(onEnded?: () => void) {
  const toast = useToast();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (assignment: CrewAssignment) => endCrewAssignment(assignment.id),
    onSuccess: (assignment) => {
      queryClient.invalidateQueries({ queryKey: ["transport-staff", "crew"] });
      toast.success("Assignment ended", `${assignment.staffName} — kept in the bus history.`);
      onEnded?.();
    },
    onError: (error) => {
      toast.error("Could not end the assignment", error instanceof ApiError ? error.message : "Please try again.");
    },
  });
}

/** An assignment is open (still shown as crew, now or later) until its end date has passed. */
function isOpen(assignment: CrewAssignment): boolean {
  if (!assignment.endsOn) return true;
  const today = new Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  return assignment.endsOn >= todayIso;
}

export interface StaffBusesSectionProps {
  staffId: string;
  organizationId: string;
  canManage: boolean;
  onAssign: () => void;
}

/** The buses a staff member is on now, is planned for, and was on before (ADR-0050). */
export function StaffBusesSection({ staffId, organizationId, canManage, onAssign }: StaffBusesSectionProps) {
  const [confirming, setConfirming] = useState<CrewAssignment | null>(null);
  const crewQuery = useQuery({
    queryKey: ["transport-staff", "crew", "staff", staffId],
    queryFn: () => listCrew({ staffId }),
  });
  const vehiclesQuery = useQuery({
    queryKey: ["transport-staff", "vehicle-picker", organizationId],
    queryFn: () => listVehiclesForPicker(organizationId),
    staleTime: 60_000,
  });
  const endMutation = useEndAssignment(() => setConfirming(null));
  const plate = new Map((vehiclesQuery.data ?? []).map((v) => [v.id, v.plateNo]));
  const rows = crewQuery.data ?? [];

  return (
    <section className={styles.section} aria-label="Buses">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Buses</span>
        {canManage && (
          <Button size="sm" variant="secondary" onClick={onAssign}>
            Assign to bus
          </Button>
        )}
      </div>
      {crewQuery.isLoading ? (
        <Skeleton height={48} />
      ) : crewQuery.isError ? (
        <p className={styles.empty}>Could not load bus assignments.</p>
      ) : rows.length === 0 ? (
        <p className={styles.empty}>Not assigned to any bus.</p>
      ) : (
        <ul className={styles.list}>
          {rows.map((assignment) => (
            <li key={assignment.id} className={styles.item}>
              <div className={styles.itemMain}>
                <span className={styles.itemTitle}>
                  {plate.get(assignment.vehicleId) ?? assignment.vehicleId}
                  {assignment.roleName ? ` · ${assignment.roleName}` : ""}
                </span>
                <span className={styles.itemMeta}>
                  {assignmentPeriod(assignment.startsOn, assignment.endsOn)} · {assignmentKindLabel(assignment.kind)}
                  {assignment.reason ? ` · ${assignment.reason}` : ""}
                </span>
              </div>
              <div className={styles.itemActions}>
                {assignment.isCurrent ? (
                  <Badge variant="success" dot>
                    Current
                  </Badge>
                ) : isOpen(assignment) ? (
                  <Badge variant="info">Planned</Badge>
                ) : (
                  <Badge variant="neutral">Ended</Badge>
                )}
                {canManage && isOpen(assignment) && (
                  <Button size="sm" variant="ghost" onClick={() => setConfirming(assignment)}>
                    End
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={confirming !== null}
        title="End this bus assignment?"
        description="It ends today and stays in the bus history. A planned assignment is cancelled."
        confirmLabel="End assignment"
        tone="danger"
        loading={endMutation.isPending}
        onConfirm={() => confirming && endMutation.mutate(confirming)}
        onCancel={() => setConfirming(null)}
      />
    </section>
  );
}

export interface VehicleCrewSectionProps {
  vehicleId: string;
  canManage: boolean;
  onAddCrew: () => void;
}

/**
 * The Crew section of a bus's drawer (ADR-0050): who is on it today, with a toggle for its
 * history. Imported by `VehiclesPage` — a component import, the same narrow cross-folder
 * precedent `StudentAssignmentSection` set, not a duplicated data read.
 */
export function VehicleCrewSection({ vehicleId, canManage, onAddCrew }: VehicleCrewSectionProps) {
  const [showHistory, setShowHistory] = useState(false);
  const [confirming, setConfirming] = useState<CrewAssignment | null>(null);
  const crewQuery = useQuery({
    queryKey: ["transport-staff", "crew", "vehicle", vehicleId],
    queryFn: () => listCrew({ vehicleId }),
  });
  const endMutation = useEndAssignment(() => setConfirming(null));
  const all = crewQuery.data ?? [];
  const current = all.filter((a) => a.isCurrent);
  const rows = showHistory ? all : current;

  return (
    <section className={styles.section} aria-label="Crew">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Crew</span>
        <div className={styles.itemActions}>
          {all.length > current.length && (
            <Button size="sm" variant="ghost" onClick={() => setShowHistory((value) => !value)}>
              {showHistory ? "Current only" : "Show history"}
            </Button>
          )}
          {canManage && (
            <Button size="sm" variant="secondary" onClick={onAddCrew}>
              Add crew member
            </Button>
          )}
        </div>
      </div>
      {crewQuery.isLoading ? (
        <Skeleton height={48} />
      ) : crewQuery.isError ? (
        <p className={styles.empty}>Could not load the crew.</p>
      ) : rows.length === 0 ? (
        <p className={styles.empty}>{showHistory ? "Nobody has been assigned to this bus." : "No crew assigned today."}</p>
      ) : (
        <ul className={styles.list}>
          {rows.map((assignment) => (
            <li key={assignment.id} className={styles.item}>
              <div className={styles.itemMain}>
                <span className={styles.itemTitle}>{assignment.staffName}</span>
                <span className={styles.itemMeta}>
                  {assignment.roleName ?? "No title"} · {assignmentPeriod(assignment.startsOn, assignment.endsOn)} ·{" "}
                  {assignmentKindLabel(assignment.kind)}
                </span>
              </div>
              {canManage && isOpen(assignment) && (
                <div className={styles.itemActions}>
                  <Button size="sm" variant="ghost" onClick={() => setConfirming(assignment)}>
                    End
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={confirming !== null}
        title={`Take ${confirming?.staffName ?? "this person"} off the bus?`}
        description="The assignment ends today and stays in the bus history."
        confirmLabel="End assignment"
        tone="danger"
        loading={endMutation.isPending}
        onConfirm={() => confirming && endMutation.mutate(confirming)}
        onCancel={() => setConfirming(null)}
      />
    </section>
  );
}

export interface StaffDocumentsSectionProps {
  staffId: string;
  canManage: boolean;
  onAdd: () => void;
  onRenew: (document: StaffDocument) => void;
}

/** A staff member's documents, current first, renewed ones kept as history (ADR-0051). */
export function StaffDocumentsSection({ staffId, canManage, onAdd, onRenew }: StaffDocumentsSectionProps) {
  const [showRenewed, setShowRenewed] = useState(false);
  const documentsQuery = useQuery({
    queryKey: ["transport-staff", "documents", staffId],
    queryFn: () => listStaffDocuments(staffId),
  });
  const all = documentsQuery.data ?? [];
  const current = all.filter((d) => d.status !== "superseded");
  const rows = showRenewed ? all : current;

  return (
    <section className={styles.section} aria-label="Documents">
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Documents</span>
        <div className={styles.itemActions}>
          {all.length > current.length && (
            <Button size="sm" variant="ghost" onClick={() => setShowRenewed((value) => !value)}>
              {showRenewed ? "Hide renewed" : "Show renewed"}
            </Button>
          )}
          {canManage && (
            <Button size="sm" variant="secondary" onClick={onAdd}>
              Add document
            </Button>
          )}
        </div>
      </div>
      {documentsQuery.isLoading ? (
        <Skeleton height={48} />
      ) : documentsQuery.isError ? (
        <p className={styles.empty}>Could not load documents.</p>
      ) : rows.length === 0 ? (
        <p className={styles.empty}>No documents recorded.</p>
      ) : (
        <ul className={styles.list}>
          {rows.map((document) => (
            <li key={document.id} className={styles.item}>
              <div className={styles.itemMain}>
                <span className={styles.itemTitle}>{document.typeName}</span>
                <span className={styles.itemMeta}>
                  {document.privateFieldsVisible
                    ? document.number
                      ? `No. ${document.number} · `
                      : ""
                    : "Number visible to Org Admins · "}
                  {document.expiresOn ? `Expires ${formatDay(document.expiresOn)}` : "No expiry"}
                  {document.status === "expiring" || document.status === "expired"
                    ? ` · ${daysLeftLabel(document.daysLeft)}`
                    : ""}
                </span>
              </div>
              <div className={styles.itemActions}>
                <Badge variant={documentStatusTone(document.status)}>{documentStatusLabel(document.status)}</Badge>
                {canManage && document.status !== "superseded" && (
                  <Button size="sm" variant="ghost" onClick={() => onRenew(document)}>
                    Renew
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
