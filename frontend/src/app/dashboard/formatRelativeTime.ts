/** "3m ago" / "2h ago" / "5d ago", falling back to a plain date beyond a week — no existing
 * helper for this anywhere in the frontend (checked before writing one), and pulling in a date
 * library for one small function isn't warranted (`.claude/rules/workflow.md` #1/#2). */
export function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) {
    return iso;
  }

  const diffSeconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (diffSeconds < 60) {
    return "just now";
  }
  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`;
  }
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }
  const diffDays = Math.round(diffHours / 24);
  if (diffDays < 7) {
    return `${diffDays}d ago`;
  }
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** "VehicleActivated" -> "Vehicle Activated" — `AuditEntry.action` is a raw PascalCase domain
 * event type verbatim (`core/audit/writer.py`'s own docstring), never pre-formatted for display. */
export function humanizeEventName(action: string): string {
  return action.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
}
