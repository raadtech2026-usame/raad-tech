import type { BadgeVariant } from "../../../shared/components/Badge/Badge";
import type { StudentAssignmentStatus } from "./api";

/** Display copy for `transport_ops.domain.value_objects.StudentAssignmentStatus` — kept in one
 * place so `StudentAssignmentSection` and `AssignStudentForm` render the exact same wording. */

export function statusLabel(status: StudentAssignmentStatus): string {
  switch (status) {
    case "active":
      return "Active";
    case "removed":
      return "Removed";
    case "transferred":
      return "Transferred";
    case "graduated":
      return "Graduated";
    case "disabled":
      return "Disabled";
    default:
      return status;
  }
}

export function statusTone(status: StudentAssignmentStatus): BadgeVariant {
  switch (status) {
    case "active":
      return "success";
    case "removed":
      return "danger";
    case "transferred":
      return "warning";
    case "graduated":
      return "info";
    case "disabled":
      return "neutral";
    default:
      return "neutral";
  }
}
