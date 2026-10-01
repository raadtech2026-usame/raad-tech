import type { UncoveredReason, UnavailabilityReason } from "./api";

export const WEEKDAYS: { value: number; short: string }[] = [
  { value: 1, short: "Mon" },
  { value: 2, short: "Tue" },
  { value: 3, short: "Wed" },
  { value: 4, short: "Thu" },
  { value: 5, short: "Fri" },
  { value: 6, short: "Sat" },
  { value: 7, short: "Sun" },
];

export function weekdaysLabel(days: number[]): string {
  const set = new Set(days);
  if (set.size === 7) return "Every day";
  if ([1, 2, 3, 4, 5].every((d) => set.has(d)) && set.size === 5) return "Mon–Fri";
  return WEEKDAYS.filter((d) => set.has(d.value)).map((d) => d.short).join(", ");
}

export const UNAVAILABILITY_REASONS: { value: UnavailabilityReason; label: string }[] = [
  { value: "sick", label: "Sick" },
  { value: "personal", label: "Personal" },
  { value: "training", label: "Training" },
  { value: "other", label: "Other" },
];

export function reasonLabel(reason: UnavailabilityReason): string {
  return UNAVAILABILITY_REASONS.find((r) => r.value === reason)?.label ?? reason;
}

const UNCOVERED: Record<UncoveredReason, string> = {
  driver_unavailable: "Driver unavailable",
  driver_inactive: "Driver access inactive",
  driver_not_active: "Driver no longer active",
  driver_not_compliant: "Driver's documents not compliant",
};

export function uncoveredLabel(reason: UncoveredReason): string {
  return UNCOVERED[reason] ?? reason;
}

export function periodLabel(period: string): string {
  return period === "afternoon" ? "Afternoon" : "Morning";
}

/** Local calendar date as `YYYY-MM-DD` (not UTC). */
export function isoDay(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return isoDay(new Date(y, m - 1, d + days));
}

export function formatDay(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

export function formatPeriod(start: string, end: string): string {
  return start === end ? formatDay(start) : `${formatDay(start)} – ${formatDay(end)}`;
}

/** "06:45:00" → "06:45". */
export function formatTime(value: string | null): string {
  return value ? value.slice(0, 5) : "";
}
