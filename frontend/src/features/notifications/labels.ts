import type { BadgeVariant } from "../../shared/components/Badge/Badge";
import type { NotificationType } from "./api";

/** Display copy for `NotificationType` — kept in one place so the list and its filter chips
 * render the exact same wording, mirroring `features/organizations/labels.ts`'s own convention. */

export function typeLabel(type: NotificationType): string {
  switch (type) {
    case "trip_started":
      return "Trip Started";
    case "approaching_stop":
      return "Approaching Stop";
    case "arrived_org":
      return "Arrived";
    case "trip_completed":
      return "Trip Completed";
    case "subscription":
      return "Subscription";
    case "system":
      return "System";
    default:
      return type;
  }
}

export function typeTone(type: NotificationType): BadgeVariant {
  switch (type) {
    case "trip_started":
      return "info";
    case "approaching_stop":
      return "warning";
    case "arrived_org":
    case "trip_completed":
      return "success";
    case "subscription":
      return "purple";
    case "system":
      return "neutral";
    default:
      return "neutral";
  }
}
