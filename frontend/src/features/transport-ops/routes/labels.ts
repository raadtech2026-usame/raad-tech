import type { BadgeVariant } from "../../../shared/components/Badge/Badge";
import type { RouteStatus } from "./api";

/** Display copy for `transport_ops.domain.value_objects.RouteStatus` — kept in one place so the
 * list table, the detail drawer, and the status-transition buttons all render the exact same
 * wording. */

export function statusLabel(status: RouteStatus): string {
  switch (status) {
    case "active":
      return "Active";
    case "inactive":
      return "Inactive";
    default:
      return status;
  }
}

export function statusTone(status: RouteStatus): BadgeVariant {
  switch (status) {
    case "active":
      return "success";
    case "inactive":
      return "neutral";
    default:
      return "neutral";
  }
}
