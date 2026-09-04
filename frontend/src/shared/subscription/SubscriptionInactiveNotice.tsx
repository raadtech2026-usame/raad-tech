import { useSyncExternalStore } from "react";
import { AlertTriangle } from "lucide-react";

import {
  getSubscriptionBlockState,
  subscribeToSubscriptionBlock,
} from "./subscriptionStatusStore";
import styles from "./SubscriptionInactiveNotice.module.css";

/**
 * ADR-0039 §6 / requirement 39K — what a user of a suspended organization actually sees.
 *
 * **Presentation only** (`.claude/rules/frontend.md` #2). This renders *because* the server
 * already refused a request; it is not a gate. Bypassing it in devtools grants nothing — every
 * subsequent API call is refused again by `interfaces/http/subscription_guard`, and both
 * WebSocket channels close with code 4402.
 *
 * **Disclosure is graded by the server, not here.** An ordinary member (Driver, Parent) receives
 * no `details` payload at all, so this renders the generic message alone — a driver has no
 * business reading their school's billing position. An Org Admin's response carries status and
 * deadline, so those render. The frontend never decides what to hide; it only displays what it
 * was given, which is what keeps the two from drifting.
 */
export function SubscriptionInactiveNotice() {
  const state = useSyncExternalStore(
    subscribeToSubscriptionBlock,
    getSubscriptionBlockState,
    getSubscriptionBlockState,
  );

  if (!state.blocked) {
    return null;
  }

  const details = state.details;
  const hasAdminDetail =
    details !== null &&
    (details.subscriptionStatus || details.gracePeriodEndsAt || details.currentPeriodEnd);

  return (
    <div className={styles.banner} role="alert" aria-live="assertive">
      <AlertTriangle className={styles.icon} aria-hidden="true" />
      <div className={styles.body}>
        <p className={styles.title}>
          {state.message ??
            "Your organization's RAAD subscription is inactive. Please contact your organization administrator or RAAD support."}
        </p>
        {hasAdminDetail && (
          <dl className={styles.detail}>
            {details?.subscriptionStatus && (
              <div className={styles.row}>
                <dt>Status</dt>
                <dd>{details.subscriptionStatus.replace(/_/g, " ")}</dd>
              </div>
            )}
            {details?.currentPeriodEnd && (
              <div className={styles.row}>
                <dt>Period ended</dt>
                <dd>{formatDate(details.currentPeriodEnd)}</dd>
              </div>
            )}
            {details?.gracePeriodEndsAt && (
              <div className={styles.row}>
                <dt>Grace ended</dt>
                <dd>{formatDate(details.gracePeriodEndsAt)}</dd>
              </div>
            )}
          </dl>
        )}
      </div>
    </div>
  );
}

/** Locale-default date only — the exact minute a grace window closed is not actionable, and a
 * timestamp reads as false precision on what is really "your account lapsed". */
function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString();
}
