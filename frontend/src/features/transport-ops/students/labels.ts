import type { BadgeVariant } from "../../../shared/components/Badge/Badge";
import type { StudentStatus } from "./api";

/** Display copy for `transport_ops.domain.value_objects.StudentStatus` — kept in one place so the
 * list table, the detail drawer, and the status-transition buttons all render the exact same
 * wording. */

export function statusLabel(status: StudentStatus): string {
  switch (status) {
    case "active":
      return "Active";
    case "disabled":
      return "Disabled";
    case "graduated":
      return "Graduated";
    case "transferred":
      return "Transferred";
    default:
      return status;
  }
}

export function statusTone(status: StudentStatus): BadgeVariant {
  switch (status) {
    case "active":
      return "success";
    case "disabled":
      return "neutral";
    case "graduated":
      return "info";
    case "transferred":
      return "warning";
    default:
      return "neutral";
  }
}
