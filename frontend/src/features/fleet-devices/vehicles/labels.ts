import type { BadgeVariant } from "../../../shared/components/Badge/Badge";
import type { VehicleStatus } from "./api";

/** Display copy for `fleet_device.domain.value_objects.VehicleStatus` — kept in one place so the
 * list table, the detail drawer, and the status-transition buttons all render the exact same
 * wording. */

export function statusLabel(status: VehicleStatus): string {
  switch (status) {
    case "active":
      return "Active";
    case "inactive":
      return "Inactive";
    case "maintenance":
      return "Under maintenance";
    default:
      return status;
  }
}

export function statusTone(status: VehicleStatus): BadgeVariant {
  switch (status) {
    case "active":
      return "success";
    case "inactive":
      return "neutral";
    case "maintenance":
      return "warning";
    default:
      return "neutral";
  }
}
