import type { BadgeVariant } from "../../shared/components/Badge/Badge";
import type { AlertStatus, IncidentCategory, IncidentSeverity, IncidentStatus, NoteKind } from "./api";

/** The alarm types the device gateway maps from the JT/T 808 alarm word (ADR-0055 §1). */
const ALARM_LABELS: Record<string, string> = {
  sos: "SOS / panic button",
  overspeed: "Overspeed",
  fatigue: "Driver fatigue",
  power_cut: "Main power cut",
  camera_fault: "Camera fault",
  collision: "Collision",
  rollover: "Rollover",
  illegal_door_open: "Door opened while moving",
};

export function alarmLabel(type: string): string {
  return ALARM_LABELS[type] ?? type;
}

export const ALERT_STATUS: Record<AlertStatus, { label: string; variant: BadgeVariant }> = {
  open: { label: "Open", variant: "danger" },
  acknowledged: { label: "Acknowledged", variant: "warning" },
  resolved: { label: "Resolved", variant: "success" },
  false_alarm: { label: "False alarm", variant: "neutral" },
};

export const CATEGORIES: { value: IncidentCategory; label: string }[] = [
  { value: "accident", label: "Accident" },
  { value: "breakdown", label: "Breakdown" },
  { value: "medical", label: "Medical" },
  { value: "behaviour", label: "Behaviour" },
  { value: "near_miss", label: "Near miss" },
  { value: "delay", label: "Serious delay" },
  { value: "student_left_behind", label: "Student left behind" },
  { value: "other", label: "Other" },
];

export function categoryLabel(value: IncidentCategory): string {
  return CATEGORIES.find((c) => c.value === value)?.label ?? value;
}

export const SEVERITIES: { value: IncidentSeverity; label: string; variant: BadgeVariant }[] = [
  { value: "low", label: "Low", variant: "neutral" },
  { value: "medium", label: "Medium", variant: "info" },
  { value: "high", label: "High", variant: "warning" },
  { value: "critical", label: "Critical", variant: "danger" },
];

export function severity(value: IncidentSeverity) {
  return SEVERITIES.find((s) => s.value === value) ?? SEVERITIES[0];
}

export const INCIDENT_STATUS: Record<IncidentStatus, { label: string; variant: BadgeVariant }> = {
  open: { label: "Open", variant: "danger" },
  investigating: { label: "Investigating", variant: "warning" },
  resolved: { label: "Resolved", variant: "success" },
  closed: { label: "Closed", variant: "neutral" },
};

/** Mirrors the domain's `_INCIDENT_TRANSITIONS`; the server refuses anything else. */
export const NEXT_STATUSES: Record<IncidentStatus, IncidentStatus[]> = {
  open: ["investigating", "resolved", "closed"],
  investigating: ["resolved", "closed"],
  resolved: ["investigating", "closed"],
  closed: [],
};

export const NOTE_KIND: Record<NoteKind, string> = {
  note: "Note",
  status_change: "Status",
  parent_notice: "Sent to parents",
};

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** `<input type="datetime-local">` value for a Date, in local time. */
export function toLocalInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Local midnight-to-midnight bounds of a `YYYY-MM-DD` day, as ISO datetimes. */
export function dayBounds(day: string): { start: string; end: string } {
  const [y, m, d] = day.split("-").map(Number);
  return { start: new Date(y, m - 1, d).toISOString(), end: new Date(y, m - 1, d + 1).toISOString() };
}
