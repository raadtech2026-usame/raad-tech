import type { BadgeVariant } from "../../../shared/components/Badge/Badge";
import type { TripStatus, TripType } from "./api";

/** Display copy for `transport_ops.domain.value_objects.TripStatus`/`TripType` — kept in one
 * place so the list table, the detail drawer, and the status-transition buttons all render the
 * exact same wording. */

export function statusLabel(status: TripStatus): string {
  switch (status) {
    case "scheduled":
      return "Scheduled";
    case "in_progress":
      return "In progress";
    case "interrupted":
      return "Interrupted";
    case "completed":
      return "Completed";
    default:
      return status;
  }
}

export function statusTone(status: TripStatus): BadgeVariant {
  switch (status) {
    case "scheduled":
      return "info";
    case "in_progress":
      return "success";
    case "interrupted":
      return "warning";
    case "completed":
      return "neutral";
    default:
      return "neutral";
  }
}

export function tripTypeLabel(tripType: TripType): string {
  switch (tripType) {
    case "morning":
      return "Morning";
    case "afternoon":
      return "Afternoon";
    default:
      return tripType;
  }
}
