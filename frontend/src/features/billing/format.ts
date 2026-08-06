/** Shared formatting helpers for `billing` views — factored out of `BillingPage.tsx` (F9) so
 * `OrgBillingPage`/`PayInvoiceDialog` (ADR-0022) format the exact same way rather than each
 * re-implementing (and potentially drifting from) the same three functions. */

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** `Invoice.periodStart`/`periodEnd` are date-only (`YYYY-MM-DD`, no time component) — parsing
 * that through a plain `new Date(...)` and formatting in the viewer's local timezone can roll
 * the displayed day backward whenever the local offset is negative (a well-known JS gotcha for
 * date-only strings, which `Date` treats as UTC midnight). Formatting in UTC instead sidesteps
 * it, since there's no local "time of day" to convert in the first place. */
export function formatDateOnly(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function formatAmount(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}
