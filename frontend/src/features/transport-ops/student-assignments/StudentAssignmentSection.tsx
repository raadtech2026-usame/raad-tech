import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigation } from "lucide-react";
import { Badge } from "../../../shared/components/Badge/Badge";
import { Button } from "../../../shared/components/Button/Button";
import { Select } from "../../../shared/components/Select/Select";
import { Skeleton } from "../../../shared/components/Skeleton/Skeleton";
import { useToast } from "../../../shared/components/Toast/toastStore";
import { ApiError } from "../../../shared/api/types";
import {
  endStudentAssignment,
  findActiveAssignmentForStudent,
  getRouteWithStops,
  listVehiclesForPicker,
  type StudentAssignmentStatus,
} from "./api";
import { statusLabel, statusTone } from "./labels";
import styles from "./StudentAssignmentSection.module.css";

const END_STATUS_OPTIONS: Exclude<StudentAssignmentStatus, "active">[] = [
  "removed",
  "transferred",
  "graduated",
  "disabled",
];

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export interface StudentAssignmentSectionProps {
  studentId: string;
  organizationId: string;
  canManage: boolean;
  onAssign: () => void;
}

/**
 * The "Route Assignment" section of the student detail drawer — this codebase's CR-1 access
 * gate, `StudentAssignment` (Backend LLD §5.4), surfaced the way `StudentsPage`'s own docstring
 * anticipated it would be (Phase F6). Rendered through `DetailDrawer`'s `mapSlot`, stacked
 * alongside `GuardiansSection` (`StudentsPage.tsx`), the same slot-sharing precedent that
 * component already establishes.
 *
 * **No separate "Student Assignments" nav page exists** — the approved design mockup shows
 * route/stop assignment as columns on the Student table itself, not a dedicated screen, and
 * `navConfig.ts` has never had a nav entry for it; see `router.tsx`'s own Phase F6 note for the
 * full reasoning behind folding this into `StudentsPage` instead of inventing one.
 *
 * **Shows only the student's current active assignment, not a history list** — `Database Design
 * §6.7`'s "one active assignment per student" invariant means at most one `ACTIVE` row can ever
 * exist; once ended, a `StudentAssignmentSummaryResponse` carries no `assignedAt`/`endedAt` to
 * order past rows by (see `./api.ts`'s own docstring), so a "previous assignments" list would
 * need an N+1 detail fetch per historical row for no clearly-scoped benefit this phase — flagged
 * as a real, deliberate scope limit, not silently omitted.
 *
 * **Ending an assignment dispatches to one of four terminal statuses** (`removed`/`transferred`/
 * `graduated`/`disabled`, mirroring `Student`'s own four-way status field) via
 * `POST /student-assignments/{id}/end` — the CR-1 revocation event API Contracts §4.3 line 128
 * documents. This directly determines whether a parent can see this student's live bus location,
 * so the status badge below reflects exactly what the backend returns, never a locally-guessed
 * value.
 */
export function StudentAssignmentSection({
  studentId,
  organizationId,
  canManage,
  onAssign,
}: StudentAssignmentSectionProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [endStatus, setEndStatus] = useState<Exclude<StudentAssignmentStatus, "active">>("removed");

  const assignmentQuery = useQuery({
    queryKey: ["student-assignments", "active-for-student", studentId],
    queryFn: () => findActiveAssignmentForStudent(studentId),
  });

  const assignment = assignmentQuery.data ?? null;

  const routeQuery = useQuery({
    queryKey: ["routes", "for-student-assignment", assignment?.routeId],
    queryFn: () => getRouteWithStops(assignment!.routeId),
    enabled: assignment !== null,
  });

  const vehiclesQuery = useQuery({
    queryKey: ["vehicles", "for-student-assignment-lookup", organizationId],
    queryFn: () => listVehiclesForPicker(organizationId, ""),
    enabled: assignment !== null && !!assignment.vehicleId,
    staleTime: 60_000,
  });

  const stopNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const stop of routeQuery.data?.stops ?? []) {
      map.set(stop.id, stop.name);
    }
    return map;
  }, [routeQuery.data]);

  const vehiclePlate = useMemo(() => {
    if (!assignment?.vehicleId) {
      return null;
    }
    return (vehiclesQuery.data ?? []).find((vehicle) => vehicle.id === assignment.vehicleId)?.plateNo ?? null;
  }, [vehiclesQuery.data, assignment]);

  const endMutation = useMutation({
    mutationFn: (status: Exclude<StudentAssignmentStatus, "active">) => {
      if (!assignment) {
        return Promise.reject(new Error("No active assignment."));
      }
      return endStudentAssignment(assignment.id, status);
    },
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["student-assignments", "active-for-student", studentId] });
      toast.success("Assignment ended", `This student's route assignment is now ${statusLabel(updated.status).toLowerCase()}.`);
    },
    onError: (error) => {
      const message = error instanceof ApiError ? error.message : "Could not end this route assignment.";
      toast.error("End assignment failed", message);
    },
  });

  return (
    <div className={styles.assignment}>
      <div className={styles.assignmentHeader}>
        <span className={styles.assignmentTitle}>Route Assignment</span>
        {canManage && assignment === null && !assignmentQuery.isLoading && (
          <Button size="sm" variant="secondary" leadingIcon={<Navigation size={13} />} onClick={onAssign}>
            Assign to route
          </Button>
        )}
      </div>

      {assignmentQuery.isLoading && <Skeleton height={36} />}
      {assignmentQuery.isError && (
        <span className={styles.assignmentEmpty}>Could not load this student's route assignment.</span>
      )}
      {assignmentQuery.isSuccess && assignment === null && (
        <span className={styles.assignmentEmpty}>No active route assignment.</span>
      )}

      {assignment && (
        <div className={styles.assignmentBody}>
          <div className={styles.assignmentRow}>
            <div>
              <div className={styles.assignmentRoute}>{routeQuery.data?.name ?? assignment.routeId}</div>
              <div className={styles.assignmentMeta}>
                Pickup: {stopNameById.get(assignment.pickupStopId) ?? assignment.pickupStopId} · Dropoff:{" "}
                {stopNameById.get(assignment.dropoffStopId) ?? assignment.dropoffStopId}
              </div>
              <div className={styles.assignmentMeta}>
                Vehicle: {assignment.vehicleId ? (vehiclePlate ?? assignment.vehicleId) : "Not assigned"} · Since{" "}
                {formatDate(assignment.assignedAt)}
              </div>
            </div>
            <Badge variant={statusTone(assignment.status)} dot>
              {statusLabel(assignment.status)}
            </Badge>
          </div>

          {canManage && (
            <div className={styles.endRow}>
              <Select
                value={endStatus}
                onChange={(event) => setEndStatus(event.target.value as Exclude<StudentAssignmentStatus, "active">)}
                aria-label="End assignment reason"
                disabled={endMutation.isPending}
              >
                {END_STATUS_OPTIONS.map((status) => (
                  <option key={status} value={status}>
                    Mark {statusLabel(status).toLowerCase()}
                  </option>
                ))}
              </Select>
              <Button
                size="sm"
                variant="danger"
                loading={endMutation.isPending}
                disabled={endMutation.isPending}
                onClick={() => endMutation.mutate(endStatus)}
              >
                End assignment
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
