import type { BadgeVariant } from "../../../shared/components/Badge/Badge";
import type { RegionStatus } from "./api";

/** Display copy for `organization.domain.value_objects.RegionStatus` — kept in one place so the
 * list table, the detail drawer, and the status-transition buttons all render the exact same
 * wording. */

export function statusLabel(status: RegionStatus): string {
  switch (status) {
    case "active":
      return "Active";
    case "inactive":
      return "Inactive";
    default:
      return status;
  }
}

export function statusTone(status: RegionStatus): BadgeVariant {
  switch (status) {
    case "active":
      return "success";
    case "inactive":
      return "neutral";
    default:
      return "neutral";
  }
}
