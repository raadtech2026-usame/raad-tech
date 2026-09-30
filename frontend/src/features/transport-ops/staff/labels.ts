import type { BadgeVariant } from "../../../shared/components/Badge/Badge";
import type { AssignmentKind, DocumentStatus, StaffStatus } from "./api";

const STAFF_STATUS: Record<StaffStatus, { label: string; tone: BadgeVariant }> = {
  active: { label: "Active", tone: "success" },
  inactive: { label: "Inactive", tone: "neutral" },
  left: { label: "Left", tone: "danger" },
};

export function staffStatusLabel(status: StaffStatus): string {
  return STAFF_STATUS[status]?.label ?? status;
}

export function staffStatusTone(status: StaffStatus): BadgeVariant {
  return STAFF_STATUS[status]?.tone ?? "neutral";
}

const DOCUMENT_STATUS: Record<DocumentStatus, { label: string; tone: BadgeVariant }> = {
  valid: { label: "Valid", tone: "success" },
  expiring: { label: "Expiring", tone: "warning" },
  expired: { label: "Expired", tone: "danger" },
  no_expiry: { label: "No expiry", tone: "neutral" },
  superseded: { label: "Renewed", tone: "neutral" },
};

export function documentStatusLabel(status: DocumentStatus): string {
  return DOCUMENT_STATUS[status]?.label ?? status;
}

export function documentStatusTone(status: DocumentStatus): BadgeVariant {
  return DOCUMENT_STATUS[status]?.tone ?? "neutral";
}

export function assignmentKindLabel(kind: AssignmentKind): string {
  return kind === "temporary" ? "Temporary" : "Permanent";
}

/** "in 12 days" / "today" / "3 days ago" for a document's days left. */
export function daysLeftLabel(daysLeft: number | null): string {
  if (daysLeft === null) return "No expiry";
  if (daysLeft === 0) return "Expires today";
  if (daysLeft === 1) return "Expires tomorrow";
  if (daysLeft > 1) return `Expires in ${daysLeft} days`;
  if (daysLeft === -1) return "Expired yesterday";
  return `Expired ${-daysLeft} days ago`;
}

/** Dates arrive as `YYYY-MM-DD`; parse them as local calendar dates, not UTC midnight. */
export function formatDay(value: string | null): string {
  if (!value) return "—";
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function assignmentPeriod(startsOn: string, endsOn: string | null): string {
  return endsOn ? `${formatDay(startsOn)} – ${formatDay(endsOn)}` : `Since ${formatDay(startsOn)}`;
}
