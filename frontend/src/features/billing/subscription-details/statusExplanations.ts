import type { Subscription } from "../api";
import { formatDateTime } from "../format";

/**
 * Answers "why is this subscription in this status right now" in one sentence, using only the
 * lifecycle timestamps ADR-0039 added to `Subscription` (`pastDueSince`/`gracePeriodEndsAt`/
 * `suspendedAt`/`cancelledAt`/`expiredAt`) plus `currentPeriodEnd`/`autoRenew`. This is a plain-
 * language reading of facts the backend already computed and stored — never a client-side guess
 * at the domain's own transition rules — and it is the entire reason this page exists: a
 * Founder should never have to reconstruct the story from five raw dates by eye.
 */
export function explainSubscriptionStatus(subscription: Subscription): string {
  const periodEnd = subscription.currentPeriodEnd
    ? formatDateTime(subscription.currentPeriodEnd)
    : "an unset date";
  const graceEnd = subscription.gracePeriodEndsAt
    ? formatDateTime(subscription.gracePeriodEndsAt)
    : "an unset date";

  switch (subscription.status) {
    case "trial":
      return "On Trial — no billing period has been opened yet. It has full standing access; nothing about it is delinquent.";
    case "active":
      return subscription.autoRenew
        ? `Active because the current billing period runs until ${periodEnd} and has not lapsed. Auto-renew is on, so it should move straight into its next period.`
        : `Active because the current billing period runs until ${periodEnd} and has not lapsed. Auto-renew is off — it will need a manual renewal before that date, or it will move to Past due.`;
    case "past_due":
      return `In Past due because the billing period ended on ${periodEnd} with no confirmed payment. The automatic grace window runs until ${graceEnd} — access is not yet interrupted.`;
    case "grace_period":
      return `In Grace period because a platform admin explicitly extended access until ${graceEnd}, overriding the automatic past-due window. This is a deliberate decision, not an automatic state.`;
    case "suspended":
      return subscription.suspendedAt
        ? `Suspended since ${formatDateTime(subscription.suspendedAt)}. Every user of this organization is blocked from the dashboard until it is reactivated.`
        : "Suspended. Every user of this organization is blocked from the dashboard until it is reactivated.";
    case "expired":
      return subscription.expiredAt
        ? `Expired since ${formatDateTime(subscription.expiredAt)}. The grace window closed with no payment or renewal.`
        : "Expired. The grace window closed with no payment or renewal.";
    case "cancelled":
      return subscription.cancelledAt
        ? `Cancelled since ${formatDateTime(subscription.cancelledAt)}. This subscription will not renew.`
        : "Cancelled. This subscription will not renew.";
    default:
      return "";
  }
}
