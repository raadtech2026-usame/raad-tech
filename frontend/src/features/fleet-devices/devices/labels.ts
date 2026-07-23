import type { BadgeVariant } from "../../../shared/components/Badge/Badge";
import type { DeviceLifecycleState } from "./api";

/** Display copy for `fleet_device.domain.value_objects.DeviceLifecycleState` — kept in one place
 * so the list table, the detail drawer, and the lifecycle-transition buttons all render the exact
 * same wording. */

export function lifecycleLabel(state: DeviceLifecycleState): string {
  switch (state) {
    case "registered":
      return "Registered";
    case "activated":
      return "Activated";
    case "assigned":
      return "Assigned";
    case "suspended":
      return "Suspended";
    case "retired":
      return "Retired";
    default:
      return state;
  }
}

export function lifecycleTone(state: DeviceLifecycleState): BadgeVariant {
  switch (state) {
    case "registered":
      return "neutral";
    case "activated":
      return "info";
    case "assigned":
      return "success";
    case "suspended":
      return "warning";
    case "retired":
      return "danger";
    default:
      return "neutral";
  }
}
