import type { BadgeVariant } from "../../../shared/components/Badge/Badge";
import type {
  AssignmentKind,
  Compliance,
  ComplianceStatus,
  DocumentEnforcement,
  DocumentRequirement,
  DocumentStatus,
  StaffStatus,
} from "./api";

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

// ---- ADR-0058: document compliance ------------------------------------------------------------

const COMPLIANCE: Record<ComplianceStatus, { label: string; tone: BadgeVariant }> = {
  compliant: { label: "Compliant", tone: "success" },
  expiring: { label: "Expiring soon", tone: "warning" },
  not_compliant: { label: "Not compliant", tone: "danger" },
};

export function complianceLabel(status: ComplianceStatus): string {
  return COMPLIANCE[status]?.label ?? status;
}

export function complianceTone(status: ComplianceStatus): BadgeVariant {
  return COMPLIANCE[status]?.tone ?? "neutral";
}

/** One line per reason: "Driving licence missing", "Medical certificate expired on 3 Oct 2026". */
export function complianceReasons(compliance: Compliance): string[] {
  return [
    ...compliance.gaps.map((g) =>
      g.reason === "expired" && g.expiredOn ? `${g.typeName} expired on ${formatDay(g.expiredOn)}` : `${g.typeName} missing`,
    ),
    ...compliance.expiring.map((e) => `${e.typeName} expires on ${formatDay(e.expiresOn)}`),
  ];
}

export const REQUIREMENTS: { value: DocumentRequirement; label: string }[] = [
  { value: "none", label: "Not required" },
  { value: "drivers", label: "Required for drivers" },
  { value: "all_staff", label: "Required for all staff" },
];

export function requirementLabel(value: DocumentRequirement): string {
  return REQUIREMENTS.find((r) => r.value === value)?.label ?? value;
}

export function enforcementLabel(value: DocumentEnforcement): string {
  return value === "block" ? "Blocks new planning" : "Warns only";
}
